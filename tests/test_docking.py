"""分子对接与蛋白质结构软件集成测试

测试策略:
- 引擎/工具检测逻辑 (mock PATH)
- 默认参数完整性
- 未安装时的错误处理与安装指引
- 结果解析逻辑 (mock文件)
"""

import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile


# ========== Docking Base ==========

def test_docking_engine_detect_not_installed():
    """测试引擎检测: 未安装时返回None"""
    from research_agent.plugins.docking.base import DockingEngine

    class MockEngine(DockingEngine):
        name = "mock"
        display_name = "Mock Engine"
        binary_name = "definitely_not_installed_binary_xyz"
        def prepare_receptor(self, receptor_path, output_dir=None): return {}
        def prepare_ligand(self, ligand_path, output_dir=None): return {}
        def run_docking(self, receptor, ligand, config): return None
        @classmethod
        def get_default_parameters(cls): return {}

    with patch("research_agent.plugins.docking.base.shutil.which", return_value=None):
        assert MockEngine.detect() is None
        assert MockEngine.detect(["/nonexistent/path/vina"]) is None


def test_docking_engine_detect_configured_path():
    """测试引擎检测: 配置路径存在时返回"""
    from research_agent.plugins.docking.base import DockingEngine

    class MockEngine(DockingEngine):
        name = "mock"
        display_name = "Mock Engine"
        binary_name = "mock_binary"
        def prepare_receptor(self, receptor_path, output_dir=None): return {}
        def prepare_ligand(self, ligand_path, output_dir=None): return {}
        def run_docking(self, receptor, ligand, config): return None
        @classmethod
        def get_default_parameters(cls): return {}

    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "vina.exe"
        fake.write_text("fake")
        found = MockEngine.detect([str(fake)])
        assert found == str(fake)


def test_docking_engine_require_executable_error():
    """测试未安装时抛错并给出安装指引"""
    from research_agent.plugins.docking.base import DockingEngine

    class MockEngine(DockingEngine):
        name = "mock"
        display_name = "Mock Engine"
        binary_name = "mock_binary"
        def prepare_receptor(self, receptor_path, output_dir=None): return {}
        def prepare_ligand(self, ligand_path, output_dir=None): return {}
        def run_docking(self, receptor, ligand, config): return None
        @classmethod
        def get_default_parameters(cls): return {}

    engine = MockEngine(executable_path=None)
    with pytest.raises(RuntimeError) as exc:
        engine._require_executable()
    assert "未检测到" in str(exc.value)


# ========== AutoDock Vina ==========

def test_vina_default_parameters():
    """测试Vina默认参数完整性"""
    from research_agent.plugins.docking.autodock_vina import AutoDockVinaEngine

    params = AutoDockVinaEngine.get_default_parameters()
    required = ["center_x", "center_y", "center_z", "size_x", "size_y", "size_z",
                "exhaustiveness", "num_modes", "energy_range"]
    for key in required:
        assert key in params, f"缺少参数: {key}"


def test_vina_install_guide():
    """测试Vina安装指引"""
    from research_agent.plugins.docking.autodock_vina import AutoDockVinaEngine

    engine = AutoDockVinaEngine()
    assert "AutoDock-Vina" in engine.install_guide
    assert "GPL" in engine.license


def test_vina_prepare_receptor_missing_file():
    """测试受体文件不存在"""
    from research_agent.plugins.docking.autodock_vina import AutoDockVinaEngine

    engine = AutoDockVinaEngine(executable_path="vina")
    with pytest.raises(FileNotFoundError):
        engine.prepare_receptor("/nonexistent/receptor.pdb")


def test_vina_prepare_receptor_pdbqt_direct():
    """测试PDBQT格式直接使用"""
    from research_agent.plugins.docking.autodock_vina import AutoDockVinaEngine

    with tempfile.TemporaryDirectory() as tmp:
        pdbqt = Path(tmp) / "rec.pdbqt"
        pdbqt.write_text("ATOM  1  N   ALA     1       1.0   1.0   1.0  1.00 10.00           N")

        engine = AutoDockVinaEngine(executable_path="vina")
        result = engine.prepare_receptor(str(pdbqt))
        assert result["format"] == "pdbqt"
        assert result["path"] == str(pdbqt)


def test_vina_parse_log():
    """测试Vina log解析"""
    from research_agent.plugins.docking.autodock_vina import AutoDockVinaEngine

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "out_log.txt"
        log.write_text(
            "mode |   affinity | dist from best mode\n"
            "     | (kcal/mol) | rmsd l.b.| rmsd u.b.\n"
            "-----+------------+----------+----------\n"
            "   1       -7.2       0.000       0.000\n"
            "   2       -6.8       1.234       2.345\n"
            "   3       -6.5       2.111       3.222\n"
        )
        engine = AutoDockVinaEngine(executable_path="vina")
        poses = engine._parse_log(log)
        assert len(poses) == 3
        assert poses[0]["rank"] == 1
        assert poses[0]["score"] == -7.2
        assert poses[2]["score"] == -6.5


def test_vina_parse_pdbqt():
    """测试Vina PDBQT输出解析"""
    from research_agent.plugins.docking.autodock_vina import AutoDockVinaEngine

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.pdbqt"
        out.write_text(
            "MODEL 1\n"
            "REMARK VINA RESULT:    -7.2  0.000  0.000\n"
            "ATOM  1  C   LIG     1       1.0   1.0   1.0  1.00 10.00           C\n"
            "ENDMDL\n"
            "MODEL 2\n"
            "REMARK VINA RESULT:    -6.8  1.234  0.000\n"
            "ENDMDL\n"
        )
        engine = AutoDockVinaEngine(executable_path="vina")
        poses = engine._parse_pdbqt(out)
        assert len(poses) == 2
        assert poses[0]["score"] == -7.2


# ========== Glide ==========

def test_glide_default_parameters():
    """测试Glide默认参数"""
    from research_agent.plugins.docking.glide import GlideEngine

    params = GlideEngine.get_default_parameters()
    assert params["precision"]["default"] == "SP"
    assert "XP" in params["precision"]["enum"]
    assert "gridfile" in params


def test_glide_install_guide():
    """测试Glide安装指引"""
    from research_agent.plugins.docking.glide import GlideEngine

    engine = GlideEngine()
    assert "Schrödinger" in engine.install_guide
    assert "Commercial" in engine.license


# ========== GOLD ==========

def test_gold_default_parameters():
    """测试GOLD默认参数"""
    from research_agent.plugins.docking.gold import GoldEngine

    params = GoldEngine.get_default_parameters()
    assert params["fitness_function"]["default"] == "chemscore"
    assert "goldscore" in params["fitness_function"]["enum"]
    assert "sphere" in params["binding_site"]["enum"]


def test_gold_parse_solutions():
    """测试GOLD结果解析"""
    from research_agent.plugins.docking.gold import GoldEngine

    with tempfile.TemporaryDirectory() as tmp:
        sol = Path(tmp) / "gold_solutions.txt"
        sol.write_text(
            "Fit.       S(hbond)  S(vdw)  S(metal)   S(phob)    Energy  Rank\n"
            "58.84       3.53     20.11     0.00     29.02     10.18      1\n"
            "55.12       2.90     19.44     0.00     27.81     11.03      2\n"
        )
        engine = GoldEngine(executable_path="gold")
        poses = engine._parse_gold_results(Path(tmp))
        assert len(poses) == 2
        assert poses[0]["rank"] == 1
        assert poses[0]["score"] == 58.84
        assert poses[1]["score"] == 55.12


# ========== Docking Manager ==========

def test_docking_manager_lists_engines():
    """测试对接管理器引擎列表"""
    from research_agent.plugins.docking.manager import DockingManager

    manager = DockingManager()
    engines = manager.list_engines()
    names = [e["name"] for e in engines]
    assert "autodock_vina" in names
    assert "glide" in names
    assert "gold" in names


def test_docking_manager_unknown_engine():
    """测试未知引擎"""
    import asyncio
    from research_agent.plugins.docking.manager import DockingManager

    manager = DockingManager()
    result = asyncio.run(manager.run_docking("nonexistent", "r.pdb", "l.pdb"))
    assert result["success"] is False
    assert "未知引擎" in result["error"]


def test_docking_manager_uninstalled_engine():
    """测试未安装引擎的提示"""
    import asyncio
    from research_agent.plugins.docking.manager import DockingManager

    with patch("research_agent.plugins.docking.manager.DockingEngine.detect", return_value=None):
        manager = DockingManager()
        result = asyncio.run(manager.run_docking("autodock_vina", "r.pdb", "l.pdb"))
        assert result["success"] is False
        assert "未安装" in result["error"]


# ========== Structure Tools ==========

def test_structure_tools_detection():
    """测试结构工具检测"""
    from research_agent.plugins.structure.manager import StructureManager

    manager = StructureManager()
    tools = manager.list_tools()
    names = [t["name"] for t in tools]
    assert "pymol" in names
    assert "chimerax" in names
    assert "swiss_pdbviewer" in names


def test_pymol_commands_generation():
    """测试PyMOL脚本生成"""
    from research_agent.plugins.structure.pymol_adapter import PyMOLTool

    tool = PyMOLTool(executable_path="pymol")
    commands = tool.get_commands("test.pdb", "out.png", style="cartoon")
    assert "load test.pdb" in commands
    assert "show cartoon" in commands
    assert any("png" in c for c in commands)


def test_pymol_render_missing_file():
    """测试PyMOL渲染缺失文件"""
    from research_agent.plugins.structure.pymol_adapter import PyMOLTool

    tool = PyMOLTool(executable_path="pymol")
    job = tool.render_structure("/nonexistent.pdb")
    assert job.success is False
    assert "不存在" in job.error


def test_chimerax_commands_generation():
    """测试ChimeraX脚本生成"""
    from research_agent.plugins.structure.chimerax_adapter import ChimeraXTool

    tool = ChimeraXTool(executable_path="chimerax")
    commands = tool.get_commands("test.pdb", "out.png", style="surface")
    assert "open test.pdb" in commands
    assert "surface" in commands
    assert any("save" in c for c in commands)


def test_swiss_pdbviewer_install_guide():
    """测试Swiss-PdbViewer安装指引"""
    from research_agent.plugins.structure.swiss_pdbviewer_adapter import SwissPdbViewerTool

    tool = SwissPdbViewerTool()
    assert "spdbv" in tool.install_guide.lower() or "Swiss-PdbViewer" in tool.install_guide


# ========== Skills ==========

def test_docking_skills_registered():
    """测试对接技能已注册"""
    from research_agent.agents.skills import SkillRegistry, initialize_builtin_skills

    initialize_builtin_skills()
    skills = SkillRegistry.list_all()
    assert "molecular_docking" in skills
    assert "structure_render" in skills
    assert "docking_status" in skills


@pytest.mark.asyncio
async def test_molecular_docking_skill_unavailable():
    """测试对接技能在软件未安装时返回清晰错误"""
    from research_agent.agents.skills import SkillRegistry, get_executor

    executor = get_executor()
    result = await executor.execute(
        "molecular_docking",
        engine="autodock_vina",
        receptor_path="r.pdb",
        ligand_path="l.pdb",
    )
    # 无论是否安装都应返回结构化结果
    assert "success" in result.output
    assert "engine" in result.output


@pytest.mark.asyncio
async def test_docking_status_skill():
    """测试对接状态技能"""
    from research_agent.agents.skills import SkillRegistry, get_executor

    executor = get_executor()
    result = await executor.execute("docking_status")
    assert result.success
    assert "docking_engines" in result.output
    assert "structure_tools" in result.output
