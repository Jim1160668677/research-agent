"""NCBI检索技能 - 封装NCBI数据库操作"""

from typing import Any

from ..base import BaseSkill, SkillOutput, SkillParameter


class PubmedSearchSkill(BaseSkill):
    """PubMed文献搜索技能"""

    def __init__(self):
        super().__init__(
            name="pubmed_search",
            description="搜索PubMed文献数据库，返回相关文献的PMID和摘要",
            category="literature",
            parameters=[
                SkillParameter("query", "string", "搜索关键词", required=True),
                SkillParameter("max_results", "integer", "最大结果数", default=10),
                SkillParameter("sort", "string", "排序方式: relevance/pub_date", default="relevance"),
            ],
            output_schema=[
                SkillOutput("results", "list", "文献列表"),
                SkillOutput("count", "integer", "结果数量"),
            ],
            network_access=True,
            modalities=["text", "bibliography"],
            timeout_seconds=50,
        )

    async def execute(self, **kwargs) -> dict[str, Any]:
        from ....ncbi_skills.adapter import get_ncbi_adapter
        adapter = get_ncbi_adapter()
        results = await adapter.pubmed_search(
            kwargs["query"],
            max_results=kwargs.get("max_results", 10),
            sort=kwargs.get("sort", "relevance"),
        )
        return {"results": results, "count": len(results)}


class SraSearchSkill(BaseSkill):
    """SRA测序数据搜索技能"""

    def __init__(self):
        super().__init__(
            name="sra_search",
            description="搜索NCBI SRA数据库中的测序数据集",
            category="genomics",
            parameters=[
                SkillParameter("query", "string", "搜索关键词", required=True),
                SkillParameter("max_results", "integer", "最大结果数", default=10),
                SkillParameter("organism", "string", "物种名称", required=False),
            ],
            output_schema=[
                SkillOutput("results", "list", "SRA数据集列表"),
                SkillOutput("count", "integer", "结果数量"),
            ],
            network_access=True,
            timeout_seconds=50,
        )

    async def execute(self, **kwargs) -> dict[str, Any]:
        from ....ncbi_skills.adapter import get_ncbi_adapter
        adapter = get_ncbi_adapter()
        results = await adapter.sra_search(
            kwargs["query"],
            max_results=kwargs.get("max_results", 10),
            organism=kwargs.get("organism"),
        )
        return {"results": results, "count": len(results)}


class GenBankFetchSkill(BaseSkill):
    """GenBank序列获取技能"""

    def __init__(self):
        super().__init__(
            name="genbank_fetch",
            description="获取NCBI GenBank数据库中的核酸序列记录",
            category="genomics",
            parameters=[
                SkillParameter("accession", "string", "序列Accession号 (如 NM_001301714)", required=True),
            ],
            network_access=True,
            timeout_seconds=50,
            output_schema=[
                SkillOutput("record", "dict", "GenBank记录"),
            ],
        )

    async def execute(self, **kwargs) -> dict[str, Any]:
        from ....ncbi_skills.adapter import get_ncbi_adapter
        adapter = get_ncbi_adapter()
        record = await adapter.genbank_fetch(kwargs["accession"])
        return {"record": record}


class BlastSearchSkill(BaseSkill):
    """BLAST序列比对技能"""

    def __init__(self):
        super().__init__(
            name="blast_search",
            description="执行BLAST序列比对搜索",
            category="genomics",
            parameters=[
                SkillParameter("query_sequence", "string", "查询序列", required=True),
                SkillParameter("database", "string", "比对数据库: nt/nr", default="nt"),
                SkillParameter("program", "string", "比对程序: blastn/blastp", default="blastn"),
                SkillParameter("max_results", "integer", "最大结果数", default=10),
            ],
            network_access=True,
            risk_level="medium",
            timeout_seconds=120,
            output_schema=[
                SkillOutput("success", "boolean", "是否成功"),
                SkillOutput("result", "dict", "BLAST结果"),
            ],
        )

    async def execute(self, **kwargs) -> dict[str, Any]:
        from ....ncbi_skills.adapter import get_ncbi_adapter
        adapter = get_ncbi_adapter()
        result = await adapter.blast_search(
            kwargs["query_sequence"],
            database=kwargs.get("database", "nt"),
            program=kwargs.get("program", "blastn"),
            max_results=kwargs.get("max_results", 10),
        )
        return result


class GeneSearchSkill(BaseSkill):
    """基因信息搜索技能"""

    def __init__(self):
        super().__init__(
            name="gene_search",
            description="搜索NCBI Gene数据库中的基因信息",
            category="genomics",
            parameters=[
                SkillParameter("gene_name", "string", "基因名称或符号", required=True),
                SkillParameter("organism", "string", "物种名称", required=False),
                SkillParameter("max_results", "integer", "最大结果数", default=10),
            ],
            network_access=True,
            timeout_seconds=50,
        )

    async def execute(self, **kwargs) -> dict[str, Any]:
        from ....ncbi_skills.adapter import get_ncbi_adapter
        adapter = get_ncbi_adapter()
        results = await adapter.gene_search(
            kwargs["gene_name"],
            organism=kwargs.get("organism"),
            max_results=kwargs.get("max_results", 10),
        )
        return {"results": results, "count": len(results)}


class EntrezLinkSkill(BaseSkill):
    """数据库关联检索技能"""

    def __init__(self):
        super().__init__(
            name="entrez_link",
            description="获取NCBI数据库间的关联记录 (如GSE到SRX的转换)",
            category="genomics",
            parameters=[
                SkillParameter("source_db", "string", "源数据库: gds/pubmed/sra/gene", required=True),
                SkillParameter("source_id", "string", "源记录ID", required=True),
                SkillParameter("target_db", "string", "目标数据库", required=True),
            ],
            network_access=True,
            timeout_seconds=50,
        )

    async def execute(self, **kwargs) -> dict[str, Any]:
        from ....ncbi_skills.adapter import get_ncbi_adapter
        adapter = get_ncbi_adapter()
        links = await adapter.link_datasets(
            kwargs["source_db"],
            kwargs["source_id"],
            kwargs["target_db"],
        )
        return {"links": links, "count": len(links)}


def register_ncbi_skills(registry):
    """注册所有NCBI技能"""
    registry.register(PubmedSearchSkill())
    registry.register(SraSearchSkill())
    registry.register(GenBankFetchSkill())
    registry.register(BlastSearchSkill())
    registry.register(GeneSearchSkill())
    registry.register(EntrezLinkSkill())


__all__ = ["register_ncbi_skills"]
