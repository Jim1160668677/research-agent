"""插件冒烟评测：白名单命令 + 受管执行 + 断言记录。

冒烟用例 SmokeTest 结构：
{
  id, command, args, expect_exit,
  expect_stdout: 字符串，解释为正则表达式（v2）；
  expect_stderr: 可选字符串，正则表达式匹配 stderr；
  timeout_s (默认 60)
}

执行复用 Deployer 的受管子进程（argv-only、超时、输出有界），
结果写入 PluginSmokeRun；未配置用例时退化为 install_method.probe
（exit 0 断言）。
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any

from ..core.models.db import Plugin, PluginSmokeRun
from .deployer import Deployer
from .lifecycle import latest_installation

_COMMAND_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHELL_METACHARS = re.compile(r"[&|;<>$`(){}]")
_SNIPPET_LIMIT = 500


def validate_smoke_spec(spec: Any) -> tuple[bool, str]:
    """白名单校验冒烟用例：拒绝 shell 元字符与无效正则。"""
    if not isinstance(spec, dict):
        return False, "smoke spec 必须是映射"
    command = spec.get("command")
    if not isinstance(command, str) or not _COMMAND_PATTERN.fullmatch(command):
        return False, "command 必须是单一可执行文件名（仅字母/数字/._-）"
    for field in ("expect_stdout", "expect_stderr"):
        value = spec.get(field)
        if value is not None and not isinstance(value, str):
            return False, f"{field} 必须是字符串"
        if value is not None and not value.strip():
            return False, f"{field} 不能为空"
        if value is not None:
            try:
                re.compile(value)
            except re.error as exc:
                return False, f"{field} 不是合法的正则表达式: {exc}"
    args = spec.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        return False, "args 必须是字符串列表"
    if any(_SHELL_METACHARS.search(item) for item in args):
        return False, "args 禁止包含 shell 元字符（&|;<>$`(){}）"
    if any(not item.strip() for item in args):
        return False, "args 禁止空字符串"
    try:
        expect_exit = int(spec.get("expect_exit", 0))
    except (TypeError, ValueError):
        return False, "expect_exit 必须是整数"
    if not 0 <= expect_exit <= 255:
        return False, "expect_exit 必须在 0-255"
    timeout_s = spec.get("timeout_s", 60)
    if not isinstance(timeout_s, int) or not 1 <= timeout_s <= 300:
        return False, "timeout_s 必须是 1-300 的整数"
    return True, ""


def _resolve_argv(
    deployer: Deployer,
    plugin: Plugin,
    prefix: Path,
    command: str,
    args: list[str],
) -> tuple[list[str], str]:
    """按安装方法解析受管环境内的可执行文件 argv。"""
    method = (plugin.install_method or {}).get("method")
    if method == "conda":
        tool = next(
            (name for name in ("micromamba", "mamba", "conda") if shutil.which(name)),
            "conda",
        )
        return [tool, "run", "-p", str(prefix), command, *args], ""
    if method == "pip":
        candidate = prefix / (
            f"Scripts/{command}.exe" if deployer.current_os() == "windows" else f"bin/{command}"
        )
        return [str(candidate), *args], ""
    return [], "运行时方法不支持隔离冒烟执行（仅 conda/pip 部署）"


class SmokeRunner:
    """针对单个插件的冒烟执行器。"""

    def __init__(self, db, user_id: int | None = None):
        self.db = db
        self.user_id = user_id
        self.deployer = Deployer(db, user_id=user_id)

    def smoke_specs(self, plugin: Plugin) -> list[dict[str, Any]]:
        specs = [item for item in (plugin.smoke_tests or []) if isinstance(item, dict)]
        if specs:
            return specs
        probe = ((plugin.install_method or {}).get("probe") or {})
        command = probe.get("command")
        if command:
            return [{
                "id": "probe",
                "command": str(command),
                "args": [str(item) for item in probe.get("args", [])],
                "expect_exit": 0,
            }]
        return []

    async def run(self, plugin: Plugin, smoke_id: str | None = None) -> dict[str, Any]:
        """执行一个冒烟用例并落库，返回评测结果。"""
        specs = self.smoke_specs(plugin)
        target = next(
            (spec for spec in specs if spec.get("id") == smoke_id), None
        ) if smoke_id else (specs[0] if specs else None)
        if target is None:
            raise ValueError("插件没有可执行的冒烟用例（未配置 smoke_tests 且无 probe 探测）")
        valid, reason = validate_smoke_spec(target)
        if not valid:
            raise ValueError(f"冒烟用例未通过白名单校验: {reason}")

        installation = await latest_installation(self.db, plugin.id, self.user_id)
        if not installation or installation.status not in {
            "deployed", "verified", "enabled", "disabled"
        }:
            raise ValueError("插件没有已部署的隔离环境；请先部署并验证")
        prefix_value = str((installation.config or {}).get("environment_prefix", ""))
        prefix = Path(prefix_value) if prefix_value else None
        if not prefix or not prefix.exists():
            raise ValueError("部署环境缺失，无法执行冒烟用例")

        command = str(target["command"])
        args = [str(item) for item in target.get("args", [])]
        argv, resolve_error = _resolve_argv(self.deployer, plugin, prefix, command, args)
        if not argv:
            raise ValueError(resolve_error)

        started = time.monotonic()
        code, stdout, stderr = await self.deployer._run_command(
            argv, timeout=int(target.get("timeout_s", 60))
        )
        duration_ms = int((time.monotonic() - started) * 1000)

        expect_exit = int(target.get("expect_exit", 0))
        expect_stdout = target.get("expect_stdout")
        expect_stderr = target.get("expect_stderr")
        matched = True
        if expect_stdout:
            pat = re.compile(expect_stdout)
            matched = bool(pat.search(f"{stdout}\n{stderr}"))
        if expect_stderr and matched:
            pat = re.compile(expect_stderr)
            matched = bool(pat.search(stderr))
        status = "passed" if code == expect_exit and matched else "failed"
        detail = {
            "command": command,
            "args": args,
            "argv": argv,
            "exit_code": code,
            "expect_exit": expect_exit,
            "expect_stdout": expect_stdout,
            "expect_stderr": expect_stderr,
            "stdout_matched": matched,
            "stdout": stdout[:_SNIPPET_LIMIT],
            "stderr": stderr[:_SNIPPET_LIMIT],
        }
        record = PluginSmokeRun(
            plugin_id=plugin.id,
            user_id=self.user_id,
            smoke_id=str(target.get("id") or "probe"),
            status=status,
            detail=detail,
            duration_ms=duration_ms,
        )
        self.db.add(record)
        await self.db.commit()
        return {
            "smoke_id": record.smoke_id,
            "status": record.status,
            "detail": detail,
            "duration_ms": duration_ms,
            "run_at": record.run_at,
        }

    async def history(self, plugin_id: int, limit: int = 20) -> list[dict[str, Any]]:
        from sqlalchemy import select

        result = await self.db.execute(
            select(PluginSmokeRun)
            .where(PluginSmokeRun.plugin_id == plugin_id)
            .order_by(PluginSmokeRun.run_at.desc(), PluginSmokeRun.id.desc())
            .limit(limit)
        )
        return [
            {
                "id": item.id,
                "smoke_id": item.smoke_id,
                "status": item.status,
                "detail": item.detail or {},
                "duration_ms": item.duration_ms,
                "run_at": item.run_at,
            }
            for item in result.scalars().all()
        ]


__all__ = ["SmokeRunner", "validate_smoke_spec"]
