"""Swiss-PdbViewer (DeepView) 适配器

Swiss-PdbViewer: SIB瑞士生物信息学研究所的蛋白质结构查看器 (免费)
支持结构比对、突变、氢键分析。渲染功能有限，主要提供结构分析。
通过命令行参数调用，部分功能需要GUI交互。
"""

import subprocess
from pathlib import Path

from .base import StructureJob, StructureTool


class SwissPdbViewerTool(StructureTool):
    """Swiss-PdbViewer 结构工具"""

    name = "swiss_pdbviewer"
    display_name = "Swiss-PdbViewer (DeepView)"
    description = "蛋白质结构查看与分析工具，支持结构比对、突变建模、氢键分析"
    license = "Freeware (SIB)"
    binary_name = "spdbv"

    INSTALL_GUIDE = (
        "1. 下载: https://spdbv.unil.ch/\n"
        "2. Windows 安装 spdbv.exe，Linux 运行 spdbv 二进制\n"
        "3. 注意: Swiss-PdbViewer 主要为GUI工具，命令行支持有限，"
        "建议使用 PyMOL 或 ChimeraX 进行命令行渲染"
    )

    @property
    def install_guide(self) -> str:
        return self.INSTALL_GUIDE

    def get_commands(self, pdb_path: str, output_path: str, style: str = "cartoon") -> list[str]:
        """Swiss-PdbViewer 命令行参数"""
        # DeepView 命令行参数格式有限，返回建议
        return [f"spdbv {pdb_path}"]

    def render_structure(self, pdb_path: str, output_path: str | None = None,
                         style: str = "cartoon", extra_commands: list[str] = None) -> StructureJob:
        """渲染结构 - Swiss-PdbViewer 渲染能力有限"""
        self._require_executable()
        pdb = Path(pdb_path)
        if not pdb.exists():
            return StructureJob(success=False, tool=self.name,
                                error=f"PDB文件不存在: {pdb_path}")

        # DeepView 通过命令行打开文件，渲染需要GUI
        cmd = [self.executable_path, str(pdb)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=30)
            return StructureJob(
                success=True,
                tool=self.name,
                output_files=[],
                message=(
                    "Swiss-PdbViewer 已打开结构文件。注意: 该工具主要用于交互式分析"
                    "（结构比对、突变、氢键），命令行渲染建议使用 PyMOL 或 ChimeraX。"
                    f"已启动: {pdb.name}"
                ),
                metadata={"command": " ".join(cmd), "returncode": result.returncode},
            )
        except subprocess.TimeoutExpired:
            # 打开GUI进程挂起是正常的，视为成功
            return StructureJob(
                success=True,
                tool=self.name,
                output_files=[],
                message=f"已启动 Swiss-PdbViewer 打开 {pdb.name} (GUI进程)",
            )
        except Exception as e:
            return StructureJob(success=False, tool=self.name, error=str(e))

    def analyze_structure(self, pdb_path: str, analysis_type: str = "h_bonds") -> StructureJob:
        """结构分析 - 返回可用的分析能力说明"""
        available = {
            "h_bonds": "氢键分析 (GUI: Display -> H-bonds)",
            "alignment": "结构比对 (GUI: SwissModel -> Alignment)",
            "mutation": "突变建模 (GUI: Edit -> Mutation)",
        }
        return StructureJob(
            success=True,
            tool=self.name,
            message=f"Swiss-PdbViewer 分析能力: {available.get(analysis_type, analysis_type)}。"
                    "该操作需要GUI交互完成。",
            metadata={"analysis_type": analysis_type},
        )


__all__ = ["SwissPdbViewerTool"]
