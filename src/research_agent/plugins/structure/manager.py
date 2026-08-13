"""蛋白质结构工具管理器"""

from typing import Dict, List, Optional, Any
from loguru import logger

from .base import StructureTool, StructureJob


class StructureManager:
    """蛋白质结构工具管理器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: 工具路径配置, 如
                {"pymol": "pymol", "chimerax": "chimerax", "swiss_pdbviewer": "spdbv"}
        """
        self.config = config or {}
        self._tools: Dict[str, StructureTool] = {}
        self._initialize_tools()

    def _initialize_tools(self):
        """初始化并检测所有结构工具"""
        from .pymol_adapter import PyMOLTool
        from .chimerax_adapter import ChimeraXTool
        from .swiss_pdbviewer_adapter import SwissPdbViewerTool

        tool_classes = [PyMOLTool, ChimeraXTool, SwissPdbViewerTool]

        for cls in tool_classes:
            configured = self.config.get(cls.name)
            executable = cls.detect([configured] if configured else None)
            tool = cls(executable_path=executable)
            self._tools[cls.name] = tool
            status = "可用" if executable else "未安装"
            logger.info(f"结构工具 [{cls.name}]: {status}"
                        + (f" ({executable})" if executable else ""))

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有工具及状态"""
        return [tool.to_dict() for tool in self._tools.values()]

    def get_tool(self, name: str) -> Optional[StructureTool]:
        """获取指定工具"""
        return self._tools.get(name)

    async def render_structure(
        self,
        tool_name: str,
        pdb_path: str,
        output_path: Optional[str] = None,
        style: str = "cartoon",
        extra_commands: List[str] = None,
    ) -> Dict[str, Any]:
        """渲染结构"""
        import asyncio
        tool = self._tools.get(tool_name)
        if not tool:
            return StructureJob(
                success=False, tool=tool_name,
                error=f"未知工具: {tool_name}，可用: {list(self._tools.keys())}",
            ).to_dict()
        if not tool.executable_path:
            return StructureJob(
                success=False, tool=tool_name,
                error=f"{tool.display_name} 未安装或未配置。安装指引: {tool.install_guide}",
            ).to_dict()

        try:
            job = await asyncio.to_thread(
                tool.render_structure, pdb_path, output_path, style, extra_commands
            )
            return job.to_dict()
        except Exception as e:
            logger.exception(f"[{tool_name}] 渲染异常")
            return StructureJob(success=False, tool=tool_name, error=str(e)).to_dict()


_manager: Optional[StructureManager] = None


def get_structure_manager() -> StructureManager:
    """获取全局结构工具管理器"""
    global _manager
    if _manager is None:
        _manager = StructureManager()
    return _manager


__all__ = ["StructureManager", "get_structure_manager"]
