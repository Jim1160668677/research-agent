"""API routes for docking and structure tools"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...plugins.docking.manager import get_docking_manager
from ...plugins.structure.manager import get_structure_manager

router = APIRouter()


class DockingRequest(BaseModel):
    engine: str
    receptor_path: str
    ligand_path: str
    parameters: dict[str, Any] = {}


class RenderRequest(BaseModel):
    tool: str
    pdb_path: str
    output_path: str | None = None
    style: str = "cartoon"
    extra_commands: list[str] | None = None


@router.get("/engines")
async def list_docking_engines():
    """列出分子对接引擎及状态"""
    manager = get_docking_manager()
    return {"engines": manager.list_engines()}


@router.get("/engines/{engine_name}")
async def get_docking_engine(engine_name: str):
    """获取单个引擎信息"""
    manager = get_docking_manager()
    for info in manager.get_engine_info():
        if info["name"] == engine_name:
            return info
    raise HTTPException(status_code=404, detail=f"未知引擎: {engine_name}")


@router.post("/run")
async def run_docking(request: DockingRequest):
    """执行分子对接"""
    manager = get_docking_manager()
    result = await manager.run_docking(
        engine_name=request.engine,
        receptor_path=request.receptor_path,
        ligand_path=request.ligand_path,
        parameters=request.parameters,
    )
    return result


@router.get("/structure/tools")
async def list_structure_tools():
    """列出蛋白质结构工具及状态"""
    manager = get_structure_manager()
    return {"tools": manager.list_tools()}


@router.post("/structure/render")
async def render_structure(request: RenderRequest):
    """渲染蛋白质结构"""
    manager = get_structure_manager()
    result = await manager.render_structure(
        tool_name=request.tool,
        pdb_path=request.pdb_path,
        output_path=request.output_path,
        style=request.style,
        extra_commands=request.extra_commands,
    )
    return result


__all__ = ["router"]
