"""PyMOL 适配器

PyMOL: 开源分子可视化软件 (Incentive版商业 / Open-Source版开源)
通过 pymol -cq script.pml 命令行渲染结构图像。
"""

import subprocess
from pathlib import Path

from loguru import logger

from .base import StructureJob, StructureTool


class PyMOLTool(StructureTool):
    """PyMOL 结构可视化工具"""

    name = "pymol"
    display_name = "PyMOL"
    description = "分子可视化软件，支持高质量结构渲染、突变分析、轨迹展示"
    license = "Open-Source (Python license) / Commercial (Incentive)"
    binary_name = "pymol"

    INSTALL_GUIDE = (
        "1. Open-Source版: pip install pymol-open-source 或 conda install -c conda-forge pymol-open-source\n"
        "2. Incentive版: https://pymol.org (商业许可)\n"
        "3. 验证: pymol -cq -d 'print(1)'"
    )

    @property
    def install_guide(self) -> str:
        return self.INSTALL_GUIDE

    def get_commands(self, pdb_path: str, output_path: str, style: str = "cartoon") -> list[str]:
        """生成 PyMOL 脚本命令"""
        commands = [
            f"load {pdb_path}",
            "hide everything",
            f"show {style}",
            "set ray_shadows, 1",
            "set ray_opaque_background, 0",
            "bg_color white",
            "orient",
            "zoom",
        ]
        if output_path.lower().endswith(".png"):
            commands.append("ray 1600, 1200")
            commands.append(f"png {output_path}, dpi=300")
        else:
            commands.append(f"save {output_path}")
        return commands

    def render_structure(self, pdb_path: str, output_path: str | None = None,
                         style: str = "cartoon", extra_commands: list[str] = None) -> StructureJob:
        """渲染蛋白质结构"""
        self._require_executable()
        pdb = Path(pdb_path)
        if not pdb.exists():
            return StructureJob(success=False, tool=self.name,
                                error=f"PDB文件不存在: {pdb_path}")

        output_path = output_path or str(self.workdir / f"{pdb.stem}_{style}.png")
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # 生成脚本
        script_path = self.workdir / f"{pdb.stem}_render.pml"
        commands = self.get_commands(str(pdb), str(output), style)
        if extra_commands:
            commands.extend(extra_commands)
        script_path.write_text("\n".join(commands))

        cmd = [self.executable_path, "-cq", str(script_path)]
        logger.info(f"PyMOL 命令: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=120)
        except subprocess.TimeoutExpired:
            return StructureJob(success=False, tool=self.name, error="PyMOL 渲染超时")

        if result.returncode != 0:
            return StructureJob(success=False, tool=self.name,
                                error=f"PyMOL 执行失败: {result.stderr[:800]}")

        if not output.exists():
            return StructureJob(success=False, tool=self.name,
                                error="PyMOL 未生成输出文件",
                                metadata={"script": str(script_path)})

        return StructureJob(
            success=True,
            tool=self.name,
            output_files=[str(output)],
            message=f"结构渲染完成: {output.name}",
            metadata={
                "script": str(script_path),
                "style": style,
                "stdout": result.stdout[:500],
            },
        )


__all__ = ["PyMOLTool"]
