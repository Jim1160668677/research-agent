"""API routes for NCBI services"""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...ncbi_skills.adapter import NCBIAdapter, NCBIError
from ..db import get_db
from ..models.schemas import BlastQuery, NcbiResponse

router = APIRouter()


async def ncbi_adapter(
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[NCBIAdapter]:
    """Create and reliably close one NCBI client per API request."""
    adapter = NCBIAdapter(db)
    try:
        yield adapter
    finally:
        await adapter.close()


def _raise_ncbi_error(exc: Exception) -> None:
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, NCBIError):
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail="NCBI operation failed") from exc


@router.get("/pubmed", response_model=NcbiResponse)
async def search_pubmed(
    query: str = Query(..., description="搜索关键词"),
    max_results: int = Query(10, ge=1, le=100),
    sort: str = Query("relevance"),
    adapter: NCBIAdapter = Depends(ncbi_adapter),
):
    """搜索PubMed文献"""
    try:
        results = await adapter.pubmed_search(query, max_results, sort)
        return NcbiResponse(
            total_count=len(results),
            results=results,
            query=query,
            timestamp=__import__("datetime").datetime.now(),
        )
    except Exception as e:
        _raise_ncbi_error(e)


@router.get("/pubmed/{pmid}")
async def get_pubmed_article(
    pmid: str,
    adapter: NCBIAdapter = Depends(ncbi_adapter),
):
    """获取PubMed文章详情"""
    try:
        article = await adapter.pubmed_fetch(pmid)
        return article
    except Exception as e:
        _raise_ncbi_error(e)


@router.post("/blast")
async def run_blast(
    query: BlastQuery,
    adapter: NCBIAdapter = Depends(ncbi_adapter),
):
    """执行BLAST搜索"""
    try:
        results = await adapter.blast_search(
            query.query_sequence,
            query.database,
            query.program,
            query.max_results,
        )
        return {"results": results, "query": query.query_sequence}
    except Exception as e:
        _raise_ncbi_error(e)


@router.get("/sra", response_model=NcbiResponse)
async def search_sra(
    query: str = Query(..., description="搜索关键词"),
    max_results: int = Query(10, ge=1, le=100),
    organism: str | None = Query(None),
    adapter: NCBIAdapter = Depends(ncbi_adapter),
):
    """搜索SRA数据库"""
    try:
        results = await adapter.sra_search(query, max_results, organism)
        return NcbiResponse(
            total_count=len(results),
            results=results,
            query=query,
            timestamp=__import__("datetime").datetime.now(),
        )
    except Exception as e:
        _raise_ncbi_error(e)


@router.get("/genbank/{accession}")
async def get_genbank(
    accession: str,
    format: str = Query("json", pattern="^(json|fasta|genbank)$"),
    adapter: NCBIAdapter = Depends(ncbi_adapter),
):
    """获取GenBank序列信息"""
    try:
        record = await adapter.genbank_fetch(accession, retmode=format)
        return record
    except Exception as e:
        _raise_ncbi_error(e)


@router.get("/gene/{gene_name}")
async def search_gene(
    gene_name: str,
    organism: str | None = Query(None, description="物种名称"),
    adapter: NCBIAdapter = Depends(ncbi_adapter),
):
    """搜索基因信息"""
    try:
        results = await adapter.gene_search(gene_name, organism)
        return {"results": results, "total": len(results)}
    except Exception as e:
        _raise_ncbi_error(e)


__all__ = ["router"]
