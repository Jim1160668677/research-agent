"""蛋白质结构可视化软件 - 统一抽象层

支持: PyMOL / UCSF ChimeraX / Swiss-PdbViewer (DeepView)
调用模式: 生成脚本 -> 调用可执行文件执行 -> 输出图像/结果
"""

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StructureJob:
    """结构处理任务结果"""
    success: bool
    tool: str
    output_files: list[str] = field(default_factory=list)
    message: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "tool": self.tool,
            "output_files": self.output_files,
            "message": self.message,
            "error": self.error,
            "metadata": self.metadata,
        }


class StructureTool(ABC):
    """蛋白质结构工具抽象基类"""

    name: str = "base"
    display_name: str = "Base Structure Tool"
    description: str = ""
    license: str = ""
    binary_name: str = ""

    def __init__(self, executable_path: str | None = None, workdir: str = "./structure_work"):
        self.executable_path = executable_path
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def detect(cls, config_paths: list[str] | None = None) -> str | None:
        """检测工具是否可用"""
        candidates = []
        if config_paths:
            candidates.extend(p for p in config_paths if p)
        found = shutil.which(cls.binary_name)
        if found:
            candidates.append(found)
        for cand in candidates:
            p = Path(cand)
            if p.exists() and p.is_file():
                return str(p)
        return None

    @abstractmethod
    def render_structure(self, pdb_path: str, output_path: str | None = None,
                         style: str = "cartoon", extra_commands: list[str] = None) -> StructureJob:
        """渲染蛋白质结构为图像"""

    @abstractmethod
    def get_commands(self, pdb_path: str, output_path: str, style: str) -> list[str]:
        """生成工具脚本命令 (供检测/调试)"""

    def _require_executable(self):
        if not self.executable_path:
            raise RuntimeError(
                f"未检测到 {self.display_name}。安装指引: {self.install_guide}"
            )

    @property
    def install_guide(self) -> str:
        return "请参考官方文档安装"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "license": self.license,
            "available": self.executable_path is not None,
            "executable_path": self.executable_path,
            "install_guide": self.install_guide,
        }


__all__ = ["StructureTool", "StructureJob"]
