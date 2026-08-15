"""Read-only host capability probe for isolated bioinformatics execution."""

from __future__ import annotations

import asyncio
import platform
import shutil
import sys
from collections.abc import Sequence
from typing import Any

TOOLS: dict[str, Sequence[str]] = {
    "micromamba": ("micromamba",),
    "mamba": ("mamba",),
    "conda": ("conda",),
    "docker": ("docker",),
    "podman": ("podman",),
    "apptainer": ("apptainer",),
    "singularity": ("singularity",),
    "nextflow": ("nextflow",),
    "snakemake": ("snakemake",),
    "git": ("git",),
}


def _decode_output(output: bytes) -> str:
    if output.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in output[:200]:
        try:
            return output.decode("utf-16").strip()
        except UnicodeError:
            pass
    return output.decode("utf-8", errors="replace").strip()


async def _command(argv: Sequence[str], timeout: float = 5.0) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode or 0, _decode_output(output)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return -1, "probe timed out"
    except (OSError, ValueError) as exc:
        return 127, str(exc)


class PlatformCapabilityProbe:
    async def probe(self, *, deep: bool = False) -> dict[str, Any]:
        system = platform.system().lower()
        tools: dict[str, dict[str, Any]] = {}
        for name, candidates in TOOLS.items():
            executable = next((shutil.which(item) for item in candidates if shutil.which(item)), None)
            item: dict[str, Any] = {"available": bool(executable), "path": executable}
            if deep and executable:
                code, output = await _command([executable, "--version"], timeout=4.0)
                item.update({"probe_ok": code == 0, "version": output.splitlines()[0][:240] if output else ""})
            tools[name] = item

        wsl = await self._probe_wsl(deep=deep, system=system)
        backends: list[dict[str, Any]] = []
        if tools["micromamba"]["available"] or tools["mamba"]["available"] or tools["conda"]["available"]:
            backends.append({"id": "isolated_conda", "available": True, "native": True})
        backends.append({"id": "python_venv", "available": True, "native": True})
        for engine in ("docker", "podman", "apptainer", "singularity"):
            if tools[engine]["available"]:
                backends.append({"id": f"container_{engine}", "available": True, "native": True})
        if wsl["operational"]:
            backends.append({"id": "wsl2", "available": True, "native": False})
        if tools["nextflow"]["available"]:
            backends.append({"id": "nextflow", "available": True, "native": True})
        if tools["snakemake"]["available"]:
            backends.append({"id": "snakemake", "available": True, "native": True})

        limitations = []
        if system == "windows" and not wsl["operational"] and not any(
            tools[item]["available"] for item in ("docker", "podman")
        ):
            limitations.append(
                "Linux-only Bioconda tools require configured WSL2, a container engine, or a remote runner"
            )
        if not any(tools[item]["available"] for item in ("micromamba", "mamba", "conda")):
            limitations.append("No conda-compatible environment manager was detected")
        if not tools["nextflow"]["available"]:
            limitations.append("Nextflow is not available on the native PATH")

        return {
            "host": {
                "system": system,
                "release": platform.release(),
                "architecture": platform.machine().lower(),
                "python": sys.version.split()[0],
            },
            "tools": tools,
            "wsl": wsl,
            "execution_backends": backends,
            "limitations": limitations,
            "deep_probe": deep,
        }

    async def _probe_wsl(self, *, deep: bool, system: str) -> dict[str, Any]:
        executable = shutil.which("wsl.exe") if system == "windows" else None
        result: dict[str, Any] = {
            "available": bool(executable),
            "operational": False,
            "distributions": [],
        }
        if not executable or not deep:
            return result
        code, output = await _command([executable, "--list", "--quiet"], timeout=6.0)
        distributions = [line.strip() for line in output.splitlines() if line.strip()]
        result.update({
            "operational": code == 0 and bool(distributions),
            "distributions": distributions[:50],
            "probe_error": "" if code == 0 else output[:500],
        })
        return result


__all__ = ["PlatformCapabilityProbe", "TOOLS"]
