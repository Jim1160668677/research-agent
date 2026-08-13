"""分子对接管理器 - 统一调度所有对接引擎"""

from typing import Dict, List, Optional, Any
from loguru import logger

from .base import DockingEngine, DockingResult, get_available_engines


class DockingManager:
    """分子对接管理器

    负责:
    1. 检测各引擎可用性
    2. 根据引擎名称分派对接任务
    3. 统一返回标准化结果
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: 引擎路径配置, 如
                {"autodock_vina": "C:/Program Files/Vina/vina.exe",
                 "glide": "$SCHRODINGER/glide",
                 "gold": "gold"}
        """
        self.config = config or {}
        self._engines: Dict[str, DockingEngine] = {}
        self._initialize_engines()

    def _initialize_engines(self):
        """初始化并检测所有引擎"""
        from .autodock_vina import AutoDockVinaEngine
        from .glide import GlideEngine
        from .gold import GoldEngine

        engine_classes = [
            AutoDockVinaEngine,
            GlideEngine,
            GoldEngine,
        ]

        for cls in engine_classes:
            # 检测可执行文件
            configured = self.config.get(cls.name)
            executable = cls.detect([configured] if configured else None)
            engine = cls(executable_path=executable)
            self._engines[cls.name] = engine
            status = "可用" if executable else "未安装"
            logger.info(f"对接引擎 [{cls.name}]: {status}"
                        + (f" ({executable})" if executable else ""))

    def list_engines(self) -> List[Dict[str, Any]]:
        """列出所有引擎及状态"""
        return get_available_engines(list(self._engines.values()))

    def get_engine(self, name: str) -> Optional[DockingEngine]:
        """获取指定引擎"""
        return self._engines.get(name)

    async def run_docking(
        self,
        engine_name: str,
        receptor_path: str,
        ligand_path: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行对接

        Args:
            engine_name: 引擎名称 (autodock_vina/glide/gold)
            receptor_path: 受体文件路径
            ligand_path: 配体文件路径
            parameters: 对接参数 (各引擎默认参数)
        """
        engine = self._engines.get(engine_name)
        if not engine:
            return DockingResult(
                success=False, engine=engine_name,
                error=f"未知引擎: {engine_name}，可用: {list(self._engines.keys())}",
            ).to_dict()

        if not engine.executable_path:
            return DockingResult(
                success=False, engine=engine_name,
                error=f"{engine.display_name} 未安装或未配置。安装指引: {engine.install_guide}",
            ).to_dict()

        parameters = parameters or {}
        try:
            # 1. 准备受体
            logger.info(f"[{engine_name}] 准备受体: {receptor_path}")
            receptor = engine.prepare_receptor(receptor_path)

            # 2. 准备配体
            logger.info(f"[{engine_name}] 准备配体: {ligand_path}")
            ligand = engine.prepare_ligand(ligand_path)

            # 3. 执行对接
            logger.info(f"[{engine_name}] 执行对接...")
            result = await self._run_async(engine, receptor, ligand, parameters)
            return result.to_dict()

        except FileNotFoundError as e:
            return DockingResult(success=False, engine=engine_name, error=str(e)).to_dict()
        except RuntimeError as e:
            return DockingResult(success=False, engine=engine_name, error=str(e)).to_dict()
        except Exception as e:
            logger.exception(f"[{engine_name}] 对接异常")
            return DockingResult(success=False, engine=engine_name, error=str(e)).to_dict()

    async def _run_async(self, engine: DockingEngine, receptor: Dict, ligand: Dict,
                         parameters: Dict) -> DockingResult:
        """异步包装同步对接（避免阻塞事件循环）"""
        import asyncio
        return await asyncio.to_thread(engine.run_docking, receptor, ligand, parameters)

    def get_engine_info(self) -> List[Dict[str, Any]]:
        """获取引擎信息（供前端表单）"""
        return [
            {
                "name": eng.name,
                "display_name": eng.display_name,
                "description": eng.description,
                "license": eng.license,
                "available": eng.executable_path is not None,
                "install_guide": eng.install_guide,
                "default_parameters": eng.get_default_parameters(),
            }
            for eng in self._engines.values()
        ]


# 全局单例
_manager: Optional[DockingManager] = None


def get_docking_manager() -> DockingManager:
    """获取全局对接管理器"""
    global _manager
    if _manager is None:
        _manager = DockingManager()
    return _manager


__all__ = ["DockingManager", "get_docking_manager"]
