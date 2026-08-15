"""分子对接软件 - 统一抽象层

定义 DockingEngine 接口，各软件 (AutoDock Vina / Glide / GOLD) 通过独立适配器实现。
调用流程: prepare_receptor -> prepare_ligand -> run_docking -> parse_results
"""

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DockingResult:
    """对接结果"""
    success: bool
    engine: str
    poses: list[dict[str, Any]] = field(default_factory=list)  # [{rank, score, file}]
    best_score: float | None = None
    output_dir: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "engine": self.engine,
            "poses": self.poses,
            "best_score": self.best_score,
            "output_dir": self.output_dir,
            "error": self.error,
            "metadata": self.metadata,
        }


class DockingEngine(ABC):
    """分子对接引擎抽象基类"""

    name: str = "base"
    display_name: str = "Base Docking Engine"
    description: str = ""
    license: str = ""

    def __init__(self, executable_path: str | None = None, workdir: str = "./docking_work"):
        self.executable_path = executable_path
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def detect(cls, config_paths: list[str] | None = None) -> str | None:
        """检测软件是否可用，返回可执行文件路径或None

        检测顺序:
        1. 用户配置的路径 (config_paths)
        2. 系统 PATH
        """
        candidates = []
        if config_paths:
            candidates.extend(p for p in config_paths if p)
        found_in_path = shutil.which(cls.binary_name)
        if found_in_path:
            candidates.append(found_in_path)

        for cand in candidates:
            p = Path(cand)
            if p.exists() and p.is_file():
                return str(p)
            # 尝试常见安装位置
            if not p.exists() and p.suffix == "":
                for probe in [cand, cand + ".exe", cand + ".bin"]:
                    if Path(probe).exists():
                        return str(probe)
        return None

    @abstractmethod
    def prepare_receptor(self, receptor_path: str, output_dir: str | None = None) -> dict[str, Any]:
        """准备受体（生成pdbqt/mae等格式）"""

    @abstractmethod
    def prepare_ligand(self, ligand_path: str, output_dir: str | None = None) -> dict[str, Any]:
        """准备配体"""

    @abstractmethod
    def run_docking(self, receptor: dict, ligand: dict, config: dict[str, Any]) -> DockingResult:
        """执行对接"""

    @classmethod
    @abstractmethod
    def get_default_parameters(cls) -> dict[str, Any]:
        """返回默认参数（供前端生成表单）"""

    def _require_executable(self):
        """确保可执行文件存在"""
        if not self.executable_path:
            raise RuntimeError(
                f"未检测到 {self.display_name}。请安装软件或在配置中指定路径。"
                f"安装指引: {self.install_guide}"
            )

    @property
    def install_guide(self) -> str:
        return "请参考官方文档安装"


def get_available_engines(engines: list[DockingEngine]) -> list[dict[str, Any]]:
    """获取所有引擎的可用状态"""
    result = []
    for eng in engines:
        result.append({
            "name": eng.name,
            "display_name": eng.display_name,
            "description": eng.description,
            "license": eng.license,
            "available": eng.executable_path is not None,
            "executable_path": eng.executable_path,
            "default_parameters": eng.get_default_parameters(),
        })
    return result


__all__ = ["DockingEngine", "DockingResult", "get_available_engines"]
