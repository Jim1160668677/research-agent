"""UCSF ChimeraX 适配器

ChimeraX: UCSF开发的开源分子可视化软件 (BSD-like)
通过 chimerax --nogui script.cxc 命令行渲染结构。
"""

from typing import Dict, List, Optional, Any
import subprocess
from pathlib import Path
from loguru import logger

from .base import StructureTool, StructureJob


class ChimeraXTool(StructureTool):
    """UCSF ChimeraX 结构可视化工具"""

    name = "chimerax"
    display_name = "UCSF ChimeraX"
    description = "现代分子可视化与分析软件，支持集成密度图、大规模结构比较"
    license = "Open Source (UCSF)"
    binary_name = "chimerax"

    INSTALL_GUIDE = (
        "1. 下载: https://www.cgl.ucsf.edu/chimerax/download.html\n"
        "2. Windows/macOS/Linux 均有安装包\n"
        "3. 验证: chimerax --version"
    )

    @property
    def install_guide(self) -> str:
        return self.INSTALL_GUIDE

    def get_commands(self, pdb_path: str, output_path: str, style: str = "cartoon") -> List[str]:
        """生成 ChimeraX 脚本命令"""
        style_map = {
            "cartoon": "cartoon",
            "surface": "surface",
            "ribbon": "ribbon",
            "ball_stick": "ball-and-stick",
        }
        cmd_style = style_map.get(style, "cartoon")

        commands = [
            f"open {pdb_path}",
            f"{cmd_style}",
            "set bgColor white",
            "view orient",
            "windowsize 1600 1200",
        ]
        if output_path.lower().endswith(".png"):
            commands.append(f"save {output_path} width 1600 height 1200")
        else:
            commands.append(f"save {output_path}")
        return commands

    def render_structure(self, pdb_path: str, output_path: Optional[str] = None,
                         style: str = "cartoon", extra_commands: List[str] = None) -> StructureJob:
        """渲染蛋白质结构"""
        self._require_executable()
        pdb = Path(pdb_path)
        if not pdb.exists():
            return StructureJob(success=False, tool=self.name,
                                error=f"PDB文件不存在: {pdb_path}")

        output_path = output_path or str(self.workdir / f"{pdb.stem}_{style}.png")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        script_path = self.workdir / f"{pdb.stem}_render.cxc"
        commands = self.get_commands(str(pdb), str(output), style)
        if extra_commands:
            commands.extend(extra_commands)
        script_path.write_text("\n".join(commands))

        cmd = [self.executable_path, "--nogui", str(script_path)]
        logger.info(f"ChimeraX 命令: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=180)
        except subprocess.TimeoutExpired:
            return StructureJob(success=False, tool=self.name, error="ChimeraX 渲染超时")

        if result.returncode != 0:
            return StructureJob(success=False, tool=self.name,
                                error=f"ChimeraX 执行失败: {result.stderr[:800]}")

        if not output.exists():
            return StructureJob(success=False, tool=self.name,
                                error="ChimeraX 未生成输出文件",
                                metadata={"script": str(script_path)})

        return StructureJob(
            success=True,
            tool=self.name,
            output_files=[str(output)],
            message=f"结构渲染完成: {output.name}",
            metadata={"script": str(script_path), "style": style},
        )


__all__ = ["ChimeraXTool"]
