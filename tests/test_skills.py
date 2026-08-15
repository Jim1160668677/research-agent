"""技能系统测试"""

import pytest

from research_agent.agents.skills import (
    SkillExecutor,
    SkillRegistry,
    initialize_builtin_skills,
)


@pytest.fixture(scope="module")
def registry():
    """初始化技能注册表"""
    initialize_builtin_skills()
    return SkillRegistry


def test_builtin_skills_registered(registry):
    """测试内置技能注册"""
    skills = registry.list_all()
    assert len(skills) >= 10
    names = set(skills.keys())
    assert "pubmed_search" in names
    assert "sra_search" in names
    assert "genbank_fetch" in names
    assert "blast_search" in names
    assert "gene_search" in names
    assert "entrez_link" in names
    assert "literature_summary" in names
    assert "experimental_design" in names
    assert "statistical_test" in names
    assert "correlation_analysis" in names
    assert "volcano_plot" in names
    assert "heatmap" in names


def test_skill_categories(registry):
    """测试技能分类"""
    skills = registry.list_all()
    categories = {s["category"] for s in skills.values()}
    assert "genomics" in categories
    assert "literature" in categories
    assert "statistics" in categories
    assert "visualization" in categories


def test_skill_search(registry):
    """测试技能搜索"""
    results = registry.search("p")
    assert "pubmed_search" in results
    results = registry.search("plot")
    assert "volcano_plot" in results


def test_skill_list_by_category(registry):
    """测试按分类列出"""
    genomics = registry.list_by_category("genomics")
    assert len(genomics) >= 5


@pytest.mark.asyncio
async def test_execute_statistical_test():
    """测试统计检验执行"""
    executor = SkillExecutor()
    result = await executor.execute(
        "statistical_test",
        group1=[1, 2, 3, 4, 5],
        group2=[2, 3, 4, 5, 6],
    )
    assert result.success
    assert "p_value" in result.output
    assert "statistic" in result.output


@pytest.mark.asyncio
async def test_execute_correlation():
    """测试相关性分析"""
    executor = SkillExecutor()
    result = await executor.execute(
        "correlation_analysis",
        x=[1, 2, 3, 4, 5],
        y=[2, 4, 6, 8, 10],
    )
    assert result.success
    assert abs(result.output["correlation"] - 1.0) < 0.01


@pytest.mark.asyncio
async def test_execute_validation_error():
    """测试参数校验失败"""
    executor = SkillExecutor()
    result = await executor.execute("statistical_test")  # 缺少group1
    assert not result.success
    assert result.error is not None


@pytest.mark.asyncio
async def test_execute_unknown_skill():
    """测试未知技能"""
    executor = SkillExecutor()
    result = await executor.execute("nonexistent")
    assert not result.success
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_volcano_plot(tmp_path):
    """测试火山图生成"""
    executor = SkillExecutor()
    output = tmp_path / "volcano.png"
    result = await executor.execute(
        "volcano_plot",
        log2fc=[1.5, -2.0, 0.5, 2.5],
        pvalues=[0.001, 0.01, 0.5, 0.02],
        output_path=str(output),
    )
    assert result.success
    assert output.exists()
    assert result.output["total_genes"] == 4
    assert result.output["upregulated"] >= 1


@pytest.mark.asyncio
async def test_experimental_design():
    """测试实验设计建议"""
    executor = SkillExecutor()
    result = await executor.execute(
        "experimental_design",
        objective="研究某基因在肿瘤中的作用",
        data_type="rna_seq",
    )
    assert result.success
    assert "suggestion" in result.output
    assert "steps" in result.output
