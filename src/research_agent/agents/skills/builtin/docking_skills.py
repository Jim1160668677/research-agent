"""分子对接与蛋白质结构技能"""

from typing import Any

from ..base import BaseSkill, SkillOutput, SkillParameter


class MolecularDockingSkill(BaseSkill):
    """分子对接技能"""

    def __init__(self):
        super().__init__(
            name="molecular_docking",
            description="使用 AutoDock Vina / Glide / GOLD 执行分子对接，预测配体-受体结合模式",
            category="docking",
            parameters=[
                SkillParameter("engine", "string", "对接引擎: autodock_vina/glide/gold", required=True,
                               enum=["autodock_vina", "glide", "gold"]),
                SkillParameter("receptor_path", "string", "受体文件路径 (pdb/pdbqt/mae/mol2)", required=True),
                SkillParameter("ligand_path", "string", "配体文件路径 (pdb/pdbqt/sdf/mol2)", required=True),
                SkillParameter("center_x", "number", "对接盒子中心X", default=0.0),
                SkillParameter("center_y", "number", "对接盒子中心Y", default=0.0),
                SkillParameter("center_z", "number", "对接盒子中心Z", default=0.0),
                SkillParameter("size_x", "number", "盒子尺寸X", default=20.0),
                SkillParameter("size_y", "number", "盒子尺寸Y", default=20.0),
                SkillParameter("size_z", "number", "盒子尺寸Z", default=20.0),
                SkillParameter("exhaustiveness", "integer", "搜索穷尽度", default=8),
                SkillParameter("num_modes", "integer", "输出模式数", default=9),
                SkillParameter("precision", "string", "Glide精度 (SP/XP/HTVS)", default="SP"),
            ],
            output_schema=[
                SkillOutput("success", "boolean", "是否成功"),
                SkillOutput("engine", "string", "使用的引擎"),
                SkillOutput("best_score", "number", "最佳结合能 (kcal/mol)"),
                SkillOutput("poses", "list", "对接姿态列表"),
            ],
        )

    async def execute(self, **kwargs) -> dict[str, Any]:
        from ....plugins.docking.manager import get_docking_manager

        manager = get_docking_manager()
        parameters = {k: v for k, v in kwargs.items()
                      if k not in ("engine", "receptor_path", "ligand_path")}
        result = await manager.run_docking(
            engine_name=kwargs["engine"],
            receptor_path=kwargs["receptor_path"],
            ligand_path=kwargs["ligand_path"],
            parameters=parameters,
        )
        return result


class StructureRenderSkill(BaseSkill):
    """蛋白质结构渲染技能"""

    def __init__(self):
        super().__init__(
            name="structure_render",
            description="使用 PyMOL / ChimeraX / Swiss-PdbViewer 渲染蛋白质三维结构图像",
            category="structure",
            parameters=[
                SkillParameter("tool", "string", "渲染工具: pymol/chimerax/swiss_pdbviewer", required=True,
                               enum=["pymol", "chimerax", "swiss_pdbviewer"]),
                SkillParameter("pdb_path", "string", "PDB结构文件路径", required=True),
                SkillParameter("output_path", "string", "输出图像路径 (.png)", required=False),
                SkillParameter("style", "string", "渲染样式: cartoon/surface/ribbon/ball_stick", default="cartoon"),
            ],
            output_schema=[
                SkillOutput("success", "boolean", "是否成功"),
                SkillOutput("output_files", "list", "输出文件列表"),
                SkillOutput("message", "string", "结果信息"),
            ],
        )

    async def execute(self, **kwargs) -> dict[str, Any]:
        from ....plugins.structure.manager import get_structure_manager

        manager = get_structure_manager()
        result = await manager.render_structure(
            tool_name=kwargs["tool"],
            pdb_path=kwargs["pdb_path"],
            output_path=kwargs.get("output_path"),
            style=kwargs.get("style", "cartoon"),
        )
        return result


class DockingStatusSkill(BaseSkill):
    """对接引擎状态检查技能"""

    def __init__(self):
        super().__init__(
            name="docking_status",
            description="检查分子对接引擎与结构工具的安装可用状态",
            category="docking",
        )

    async def execute(self, **kwargs) -> dict[str, Any]:
        from ....plugins.docking.manager import get_docking_manager
        from ....plugins.structure.manager import get_structure_manager

        docking = get_docking_manager().list_engines()
        structure = get_structure_manager().list_tools()

        return {
            "success": True,
            "docking_engines": docking,
            "structure_tools": structure,
        }


def register_docking_skills(registry):
    """注册对接与结构技能"""
    registry.register(MolecularDockingSkill())
    registry.register(StructureRenderSkill())
    registry.register(DockingStatusSkill())


__all__ = ["register_docking_skills"]

