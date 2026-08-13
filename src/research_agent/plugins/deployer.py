"""Isolated, non-shell deployment plans for bioinformatics plugins."""

from __future__ import annotations

import asyncio
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select, update

from ..core.app import settings
from ..core.models.db import Plugin, PluginInstallation
from .lifecycle import (
    DEPLOYED,
    DEPLOYING,
    ENABLED,
    ERROR,
    INSTALLED_STATES,
    UNINSTALLED,
    VERIFIED,
    VERIFIED_STATES,
    latest_installation,
    transition,
)
from .manifest import pinned_package_spec


class DeployResult:
    def __init__(
        self,
        plugin_id: int,
        name: str,
        ok: bool,
        steps: List[Dict[str, Any]],
        message: str = "",
        deployed_version: str = "",
        is_simulated: bool = True,
        requires_manual_download: bool = False,
        environment_prefix: str = "",
    ):
        self.plugin_id = plugin_id
        self.name = name
        self.ok = ok
        self.steps = steps
        self.message = message
        self.deployed_version = deployed_version
        self.is_simulated = is_simulated
        self.requires_manual_download = requires_manual_download
        self.environment_prefix = environment_prefix

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "ok": self.ok,
            "steps": self.steps,
            "message": self.message,
            "deployed_version": self.deployed_version,
            "is_simulated": self.is_simulated,
            "requires_manual_download": self.requires_manual_download,
            "environment_prefix": self.environment_prefix,
        }


class Deployer:
    """Deploy one plugin per isolated prefix without invoking a command shell."""

    CMD_TIMEOUT = 600
    _SAFE_CHANNEL = re.compile(r"^[A-Za-z0-9_.:/-]{1,200}$")
    _SAFE_SPEC = re.compile(r"^[A-Za-z0-9_.:+*<>=!~\-\[\],@/]{1,500}$")

    def __init__(self, db_session, user_id: Optional[int] = None):
        self.db = db_session
        self.user_id = user_id
        self.os_name = platform.system().lower()
        self.env_root = self._default_env_root()

    @staticmethod
    def _default_env_root() -> Path:
        configured = os.environ.get("RESEARCH_AGENT_DATA_DIR")
        if configured:
            return (Path(configured).expanduser().resolve() / "plugin-envs")
        prefix = "sqlite+aiosqlite:///"
        if settings.database_url.startswith(prefix):
            database_path = Path(settings.database_url[len(prefix):]).expanduser().resolve()
            return database_path.parent / "plugin-envs"
        return (Path.cwd() / ".research-agent" / "plugin-envs").resolve()

    def current_os(self) -> str:
        return {"windows": "windows", "darwin": "macos"}.get(self.os_name, "linux")

    def is_supported(self, os_list: List[str]) -> Tuple[bool, str]:
        current = self.current_os()
        normalized = [item.lower() for item in (os_list or []) if item]
        if not normalized:
            return True, f"未声明平台限制，按 {current} 处理"
        for item in normalized:
            if item == current or (item == "darwin" and current == "macos"):
                return True, f"支持当前平台 {current}"
        return False, f"不支持当前平台 {current}；支持: {', '.join(normalized)}"

    def tools_available(self) -> Dict[str, bool]:
        return {
            "micromamba": shutil.which("micromamba") is not None,
            "mamba": shutil.which("mamba") is not None,
            "conda": shutil.which("conda") is not None,
            "python": bool(sys.executable),
            "git": shutil.which("git") is not None,
        }

    def _environment_prefix(self, plugin: Plugin) -> Path:
        root = getattr(self, "env_root", None) or self._default_env_root()
        identifier = plugin.id if plugin.id is not None else plugin.name
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"plugin-{identifier}-{plugin.version}").strip(".-")
        return (Path(root).resolve() / slug[:120]).resolve()

    @staticmethod
    def _display_command(argv: Sequence[str]) -> str:
        return subprocess.list2cmdline(list(argv)) if os.name == "nt" else shlex.join(argv)

    @classmethod
    def _validate_package_spec(cls, value: str, label: str) -> str:
        value = value.strip()
        if not cls._SAFE_SPEC.fullmatch(value):
            raise ValueError(f"Invalid {label} in plugin catalog")
        return value

    def build_plan(self, plugin: Plugin) -> Dict[str, Any]:
        method = plugin.install_method or {}
        method_name = str(method.get("method", "manual")).lower()
        supported, support_reason = self.is_supported(plugin.os_compatibility or [])
        tools = self.tools_available()
        prefix = self._environment_prefix(plugin)
        steps: List[Dict[str, Any]] = []
        plan = {
            "method": method_name,
            "supported": supported,
            "support_reason": support_reason,
            "environment_prefix": str(prefix),
            "steps": steps,
            "requires_manual_download": False,
        }
        if not supported:
            steps.append({
                "action": "abort",
                "description": f"平台不兼容: {support_reason}",
                "command": None,
                "argv": None,
            })
            return plan

        if method_name == "conda":
            executable = next(
                (name for name in ("micromamba", "mamba", "conda") if tools.get(name)),
                None,
            )
            if executable is None:
                steps.append({
                    "action": "abort",
                    "description": "未检测到 micromamba、mamba 或 conda，无法创建隔离环境",
                    "command": None,
                    "argv": None,
                })
            else:
                package_spec = self._validate_package_spec(
                    pinned_package_spec(
                        str(method.get("spec") or method.get("package") or plugin.name),
                        plugin.version,
                    ),
                    "conda package specification",
                )
                channels = method.get("channels") or [method.get("channel", "conda-forge")]
                if isinstance(channels, str):
                    channels = [channels]
                channel_args: List[str] = []
                for channel in channels:
                    channel = str(channel).strip()
                    if not self._SAFE_CHANNEL.fullmatch(channel):
                        raise ValueError("Invalid conda channel in plugin catalog")
                    channel_args.extend(["-c", channel])
                argv = [
                    executable,
                    "create",
                    "-y",
                    "-p",
                    str(prefix),
                    *channel_args,
                    package_spec,
                ]
                steps.append({
                    "action": "run",
                    "description": f"在独立环境中安装 {package_spec}",
                    "command": self._display_command(argv),
                    "argv": argv,
                    "env": {"prefix": str(prefix)},
                })
        elif method_name == "pip":
            package_spec = self._validate_package_spec(
                pinned_package_spec(
                    str(method.get("spec") or method.get("package") or plugin.name),
                    plugin.version,
                ),
                "pip package specification",
            )
            python = sys.executable
            venv_argv = [python, "-m", "venv", str(prefix)]
            environment_python = prefix / ("Scripts/python.exe" if self.current_os() == "windows" else "bin/python")
            install_argv = [str(environment_python), "-m", "pip", "install", package_spec]
            steps.extend([
                {
                    "action": "run",
                    "description": "创建独立 Python 虚拟环境",
                    "command": self._display_command(venv_argv),
                    "argv": venv_argv,
                    "env": {"prefix": str(prefix)},
                },
                {
                    "action": "run",
                    "description": f"在独立环境中安装 {package_spec}",
                    "command": self._display_command(install_argv),
                    "argv": install_argv,
                    "env": {"prefix": str(prefix)},
                },
            ])
        elif method_name == "binary":
            download = method.get("download", {})
            os_key = {"windows": "windows", "darwin": "macos"}.get(self.os_name, "linux")
            url = download.get(os_key) or download.get("any")
            if not url:
                steps.append({
                    "action": "abort",
                    "description": "当前平台没有已登记的二进制安装包",
                    "command": None,
                    "argv": None,
                })
            else:
                steps.append({
                    "action": "download",
                    "description": f"需人工下载并校验安装包: {url}",
                    "url": url,
                    "command": None,
                    "argv": None,
                })
                steps.append({
                    "action": "manual_hint",
                    "description": f"安装指南: {plugin.docs_url or plugin.homepage or plugin.source_url}",
                    "command": None,
                    "argv": None,
                })
                plan["requires_manual_download"] = True
        else:
            steps.append({
                "action": "manual_hint",
                "description": f"该工具需人工安装: {plugin.docs_url or plugin.homepage or plugin.source_url}",
                "command": None,
                "argv": None,
            })
            plan["requires_manual_download"] = True

        if plugin.config_schema and plugin.config_schema.get("properties"):
            steps.append({
                "action": "config",
                "description": "待配置参数: " + ", ".join(plugin.config_schema["properties"].keys()),
                "command": None,
                "argv": None,
            })
        return plan

    async def deploy(self, plugin: Plugin, simulate: bool = False) -> DeployResult:
        plan = self.build_plan(plugin)
        completed_steps: List[Dict[str, Any]] = []
        prefix = Path(plan["environment_prefix"])
        ok = bool(plan["supported"])
        if not simulate:
            await transition(
                self.db,
                plugin.id,
                self.user_id,
                DEPLOYING,
                version=plugin.version,
                config={
                    "environment_prefix": str(prefix),
                    "method": plan["method"],
                },
                provenance={"event": "deployment_started"},
            )
            await self.db.commit()
        message = "已生成隔离部署计划" if simulate else ""

        if not plan["supported"]:
            result = DeployResult(
                plugin.id,
                plugin.name,
                False,
                plan["steps"],
                message=plan["support_reason"],
                is_simulated=simulate,
                environment_prefix=str(prefix),
            )
            if not simulate:
                await self._record_failure(plugin, plan["support_reason"])
            return result

        for step in plan["steps"]:
            action = step["action"]
            if action == "abort":
                ok = False
                message = step["description"]
                completed_steps.append({"status": "failed", **step})
                break
            if action == "run":
                if simulate:
                    completed_steps.append({"status": "planned", **step})
                    continue
                code, stdout, stderr = await self._run_command(
                    step.get("argv") or [], timeout=self.CMD_TIMEOUT
                )
                if code != 0:
                    ok = False
                    message = f"隔离部署失败 (exit={code}): {(stderr or stdout)[:500]}"
                    completed_steps.append({
                        "status": "failed",
                        **step,
                        "exit_code": code,
                        "output": (stdout or stderr)[-500:],
                    })
                    await self._rollback_environment(prefix)
                    break
                completed_steps.append({"status": "ok", **step, "exit_code": 0})
                continue
            if action in {"download", "manual_hint"}:
                status = "planned" if simulate else "requires_action"
                completed_steps.append({"status": status, **step})
                if not simulate:
                    ok = False
                    message = "该工具需要人工下载或安装，系统未将其标记为已部署"
                continue
            completed_steps.append({"status": "planned" if simulate else "ok", **step})

        if ok and not simulate:
            message = f"{plugin.name} 已部署到隔离环境 (v{plugin.version})"
        result = DeployResult(
            plugin.id,
            plugin.name,
            ok,
            completed_steps,
            message,
            deployed_version=plugin.version if ok and not simulate else "",
            is_simulated=simulate,
            requires_manual_download=plan.get("requires_manual_download", False),
            environment_prefix=str(prefix),
        )
        if not simulate:
            await self._record_installation(
                plugin,
                ok,
                message,
                deployed_version=result.deployed_version,
                environment_prefix=str(prefix),
                method=plan["method"],
            )
        return result

    async def _run_command(
        self,
        argv: Sequence[str],
        timeout: int = 60,
    ) -> Tuple[int, str, str]:
        if not argv or not all(isinstance(item, str) and item for item in argv):
            return 1, "", "no executable argv"
        kwargs: Dict[str, Any] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if self.current_os() == "windows":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            process = await asyncio.create_subprocess_exec(*argv, **kwargs)
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return (
                process.returncode or 0,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            await self._terminate_process(process)
            return -1, "", f"command timed out after {timeout}s"
        except FileNotFoundError as exc:
            return 127, "", f"executable not available: {exc}"
        except Exception as exc:
            return 1, "", str(exc)

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            if self.current_os() == "windows":
                terminator = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await terminator.wait()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        except (ProcessLookupError, PermissionError):
            process.kill()
            await process.wait()

    async def _rollback_environment(self, prefix: Path) -> None:
        root = (getattr(self, "env_root", None) or self._default_env_root()).resolve()
        resolved = prefix.resolve()
        if resolved.is_relative_to(root) and resolved.name.startswith("plugin-") and resolved.exists():
            await asyncio.to_thread(shutil.rmtree, resolved)

    async def _record_installation(
        self,
        plugin: Plugin,
        ok: bool,
        message: str,
        deployed_version: str = "",
        environment_prefix: str = "",
        method: str = "",
    ) -> None:
        await transition(
            self.db,
            plugin.id,
            self.user_id,
            DEPLOYED if ok else ERROR,
            version=deployed_version or plugin.version,
            config={"environment_prefix": environment_prefix, "method": method},
            provenance={
                "event": "deployment_succeeded" if ok else "deployment_failed"
            },
            error_message=None if ok else message,
        )
        if ok:
            await self.db.execute(
                update(Plugin)
                .where(Plugin.id == plugin.id)
                .values(
                    downloads=Plugin.downloads + 1,
                )
            )
        await self.db.commit()

    async def _record_failure(self, plugin: Plugin, message: str) -> None:
        await transition(
            self.db,
            plugin.id,
            self.user_id,
            ERROR,
            version=plugin.version,
            provenance={"event": "deployment_rejected"},
            error_message=message,
        )
        await self.db.commit()

    async def record_unhandled_failure(self, plugin: Plugin, message: str) -> None:
        """Persist an unexpected deploy failure after clearing a broken transaction."""
        await self.db.rollback()
        await transition(
            self.db,
            plugin.id,
            self.user_id,
            ERROR,
            version=plugin.version,
            provenance={"event": "deployment_exception"},
            error_message=message[:2000],
            force=True,
        )
        await self.db.commit()

    async def remove_environment(self, plugin: Plugin) -> Dict[str, Any]:
        """Remove only the isolated environment recorded for this user."""
        installation = await latest_installation(self.db, plugin.id, self.user_id)
        if not installation or installation.status not in INSTALLED_STATES | {ERROR}:
            raise ValueError("Plugin has no deployed environment to remove")
        prefix_value = str((installation.config or {}).get("environment_prefix", ""))
        removed = False
        if prefix_value:
            root = self.env_root.resolve()
            prefix = Path(prefix_value).resolve()
            if not prefix.is_relative_to(root) or not prefix.name.startswith("plugin-"):
                raise ValueError("Refusing to remove an environment outside the managed root")
            if prefix.exists():
                await asyncio.to_thread(shutil.rmtree, prefix)
                removed = True
        await transition(
            self.db,
            plugin.id,
            self.user_id,
            UNINSTALLED,
            version=installation.version,
            config=installation.config or {},
            provenance={
                "event": "environment_removed",
                "environment_was_present": removed,
            },
        )
        await self.db.commit()
        return {
            "plugin_id": plugin.id,
            "status": UNINSTALLED,
            "environment_prefix": prefix_value,
            "removed": removed,
        }

    async def verify_installation(self, plugin: Plugin) -> Dict[str, Any]:
        method = plugin.install_method or {}
        installation = await latest_installation(self.db, plugin.id, self.user_id)
        if not installation or installation.status not in {
            DEPLOYED, VERIFIED, ENABLED, "disabled"
        }:
            return {
                "found": False,
                "version": "",
                "probe": method.get("probe") or {},
                "environment_prefix": "",
                "reason": "plugin has no deployed environment for this user",
            }
        prefix_value = str((installation.config or {}).get("environment_prefix", ""))
        prefix = Path(prefix_value) if prefix_value else None
        probe = method.get("probe") or {}
        command = str(probe.get("command") or method.get("executable") or plugin.name)
        args = [str(item) for item in probe.get("args", ["--version"])]
        argv: List[str]
        if not prefix or not prefix.exists():
            message = "deployed environment is missing"
            await transition(
                self.db,
                plugin.id,
                self.user_id,
                ERROR,
                version=installation.version,
                config=installation.config or {},
                provenance={"event": "verification_failed"},
                error_message=message,
            )
            await self.db.commit()
            return {
                "found": False,
                "version": "",
                "probe": probe,
                "environment_prefix": prefix_value,
                "reason": message,
            }
        if method.get("method") == "conda":
            tool = next((name for name in ("micromamba", "mamba", "conda") if shutil.which(name)), "conda")
            argv = [tool, "run", "-p", str(prefix), command, *args]
        elif method.get("method") == "pip":
            candidate = prefix / (f"Scripts/{command}.exe" if self.current_os() == "windows" else f"bin/{command}")
            argv = [str(candidate), *args]
        else:
            return {
                "found": False,
                "version": "",
                "probe": probe,
                "environment_prefix": prefix_value,
                "reason": "runtime does not support isolated verification",
            }
        code, stdout, stderr = await self._run_command(argv, timeout=30)
        first_line = (stdout or stderr).strip().splitlines()
        if code == 0 and installation.status not in VERIFIED_STATES:
            await transition(
                self.db,
                plugin.id,
                self.user_id,
                VERIFIED,
                version=installation.version,
                config=installation.config or {},
                provenance={"event": "verification_succeeded", "probe_argv": argv},
            )
            await self.db.commit()
        elif code != 0:
            await transition(
                self.db,
                plugin.id,
                self.user_id,
                ERROR,
                version=installation.version,
                config=installation.config or {},
                provenance={"event": "verification_failed", "probe_argv": argv},
                error_message=(stderr or stdout or "verification failed")[:1000],
            )
            await self.db.commit()
        return {
            "found": code == 0,
            "version": first_line[0][:120] if code == 0 and first_line else "",
            "probe": probe,
            "environment_prefix": str(prefix or ""),
        }

    async def get_deploy_history(
        self,
        plugin_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        query = select(PluginInstallation).where(PluginInstallation.plugin_id == plugin_id)
        if self.user_id is not None:
            query = query.where(PluginInstallation.user_id == self.user_id)
        result = await self.db.execute(
            query.order_by(PluginInstallation.installed_at.desc()).limit(limit)
        )
        return [
            {
                "id": record.id,
                "version": record.version,
                "status": record.status,
                "error_message": record.error_message,
                "environment_prefix": (record.config or {}).get("environment_prefix", ""),
                "installed_at": record.installed_at.isoformat() if record.installed_at else None,
            }
            for record in result.scalars().all()
        ]


__all__ = ["Deployer", "DeployResult"]
