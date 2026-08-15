"""Reliable adapters for NCBI Entrez, SRA, GenBank, Gene and BLAST services."""

from __future__ import annotations

import asyncio
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

import httpx
from Bio import SeqIO
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.app import settings


class NCBIError(RuntimeError):
    """Base class for errors that callers may safely expose as an upstream failure."""


class NCBIRequestError(NCBIError):
    """The NCBI service could not be reached or rejected a request."""


class NCBIProtocolError(NCBIError):
    """NCBI returned a response that did not match the documented protocol."""


def _xml_text(node: ET.Element | None) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


class NCBIAdapter:
    """Protocol-aware NCBI client with rate limiting, retries and typed results."""

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    BLAST_URL = "https://blast.ncbi.nlm.nih.gov/Blast.cgi"
    _RETRIABLE_STATUS = {408, 429, 500, 502, 503, 504}
    _BLAST_PROGRAMS = {"blastn", "blastp", "blastx", "tblastn", "tblastx"}

    def __init__(
        self,
        db_session: AsyncSession | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        max_retries: int = 3,
    ):
        self.db_session = db_session
        self.api_key = settings.ncbi_api_key
        self.email = settings.ncbi_email
        self._session = http_client
        self._owns_session = http_client is None
        self._sleep = sleep
        self._monotonic = monotonic
        self._max_retries = max(0, min(max_retries, 6))
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def __aenter__(self) -> NCBIAdapter:
        await self._get_session()
        return self

    async def __aexit__(self, *_exc_info) -> None:
        await self.close()

    async def _get_session(self) -> httpx.AsyncClient:
        if self._session is None:
            email = self.email or "contact-not-configured"
            self._session = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
                headers={"User-Agent": f"ResearchAgent/{settings.version} ({email})"},
            )
        return self._session

    async def _rate_limit(self) -> None:
        # NCBI permits 3 req/s without an API key and 10 req/s with one.
        interval = 0.11 if self.api_key else 0.34
        async with self._rate_lock:
            remaining = interval - (self._monotonic() - self._last_request_at)
            if remaining > 0:
                await self._sleep(remaining)
            self._last_request_at = self._monotonic()

    async def _http_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        session = await self._get_session()
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            await self._rate_limit()
            try:
                response = await session.request(method, url, params=params, data=data)
                if response.status_code in self._RETRIABLE_STATUS:
                    raise httpx.HTTPStatusError(
                        f"retriable NCBI status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.text
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if status is not None and status not in self._RETRIABLE_STATUS:
                    break
                if attempt >= self._max_retries:
                    break
                retry_after = None
                if isinstance(exc, httpx.HTTPStatusError):
                    retry_after = exc.response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(0.5 * (2**attempt), 4.0)
                except ValueError:
                    delay = min(0.5 * (2**attempt), 4.0)
                logger.warning(
                    "NCBI request failed (attempt {}/{}); retrying in {:.2f}s: {}",
                    attempt + 1,
                    self._max_retries + 1,
                    delay,
                    exc,
                )
                await self._sleep(delay)

        logger.error("NCBI request failed: {}", last_error)
        raise NCBIRequestError(f"NCBI request failed: {last_error}") from last_error

    def _common_params(self, params: dict[str, Any]) -> dict[str, Any]:
        result = {**params, "tool": "research_agent"}
        if self.email:
            result["email"] = self.email
        if self.api_key:
            result["api_key"] = self.api_key
        return result

    async def _request(self, tool: str, **params: Any) -> str:
        return await self._http_request(
            "GET",
            f"{self.BASE_URL}/{tool}.fcgi",
            params=self._common_params(params),
        )

    async def _request_json(self, tool: str, **params: Any) -> dict[str, Any]:
        payload = await self._request(tool, **params)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            snippet = payload[:120].replace("\n", " ")
            raise NCBIProtocolError(
                f"NCBI {tool} returned invalid JSON: {snippet!r}"
            ) from exc
        if not isinstance(parsed, dict):
            raise NCBIProtocolError(f"NCBI {tool} returned a non-object JSON payload")
        return parsed

    @staticmethod
    def _esearch_ids(payload: dict[str, Any]) -> list[str]:
        result = payload.get("esearchresult")
        if not isinstance(result, dict):
            raise NCBIProtocolError("NCBI ESearch response is missing esearchresult")
        ids = result.get("idlist", [])
        if not isinstance(ids, list):
            raise NCBIProtocolError("NCBI ESearch idlist is not a list")
        return [str(item) for item in ids if str(item).strip()]

    # ---------- PubMed ----------

    async def pubmed_search(
        self,
        query: str,
        max_results: int = 10,
        sort: str = "relevance",
        date_range: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            raise ValueError("PubMed query must not be empty")

        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmax": max(1, min(int(max_results), 100)),
            "sort": sort,
            "retmode": "json",
            "usehistory": "y",
        }
        if date_range and date_range.get("start"):
            params.update(
                datetype="pdat",
                mindate=date_range["start"],
                maxdate=date_range.get("end") or datetime.now().strftime("%Y/%m/%d"),
            )

        ids = self._esearch_ids(await self._request_json("esearch", **params))
        return await self.pubmed_fetch_batch(ids)

    async def pubmed_fetch(self, pmid: str) -> dict[str, Any]:
        articles = await self.pubmed_fetch_batch([pmid])
        return articles[0] if articles else {"error": f"PMID {pmid} not found"}

    async def pubmed_fetch_batch(self, pmids: Sequence[str]) -> list[dict[str, Any]]:
        clean_ids = [str(item).strip() for item in pmids if str(item).strip()]
        if not clean_ids:
            return []
        xml_result = await self._request(
            "efetch",
            db="pubmed",
            id=",".join(clean_ids),
            retmode="xml",
        )
        try:
            root = ET.fromstring(xml_result)
        except ET.ParseError as exc:
            raise NCBIProtocolError("PubMed EFetch returned invalid XML") from exc

        results: list[dict[str, Any]] = []
        for node in root.findall(".//PubmedArticle"):
            citation = node.find("./MedlineCitation")
            article = citation.find("./Article") if citation is not None else None
            if citation is None or article is None:
                continue
            pmid = _xml_text(citation.find("./PMID"))
            abstract_parts: list[str] = []
            for abstract in article.findall("./Abstract/AbstractText"):
                content = _xml_text(abstract)
                label = abstract.attrib.get("Label")
                if content:
                    abstract_parts.append(f"{label}: {content}" if label else content)
            authors: list[str] = []
            for author in article.findall("./AuthorList/Author"):
                collective = _xml_text(author.find("./CollectiveName"))
                personal = " ".join(
                    filter(
                        None,
                        [
                            _xml_text(author.find("./ForeName")),
                            _xml_text(author.find("./LastName")),
                        ],
                    )
                )
                if collective or personal:
                    authors.append(collective or personal)
            pub_date = article.find("./Journal/JournalIssue/PubDate")
            year = _xml_text(pub_date.find("./Year")) if pub_date is not None else ""
            if not year and pub_date is not None:
                match = re.search(r"\b(?:19|20)\d{2}\b", _xml_text(pub_date.find("./MedlineDate")))
                year = match.group(0) if match else ""
            doi = next(
                (
                    _xml_text(identifier)
                    for identifier in node.findall("./PubmedData/ArticleIdList/ArticleId")
                    if identifier.attrib.get("IdType") == "doi"
                ),
                "",
            )
            results.append(
                {
                    "pmid": pmid,
                    "title": _xml_text(article.find("./ArticleTitle")),
                    "abstract": "\n".join(abstract_parts),
                    "authors": authors,
                    "journal": _xml_text(article.find("./Journal/Title")),
                    "year": year,
                    "doi": doi,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                }
            )
        return results

    # ---------- SRA ----------

    async def sra_search(
        self,
        query: str,
        max_results: int = 10,
        organism: str | None = None,
    ) -> list[dict[str, Any]]:
        term = query.strip()
        if not term:
            raise ValueError("SRA query must not be empty")
        if organism:
            term += f' AND "{organism.strip()}"[Organism]'
        ids = self._esearch_ids(
            await self._request_json(
                "esearch",
                db="sra",
                term=term,
                retmax=max(1, min(int(max_results), 100)),
                retmode="json",
                usehistory="y",
            )
        )
        return await self.sra_fetch_batch(ids)

    async def sra_fetch(self, sra_id: str) -> dict[str, Any]:
        records = await self.sra_fetch_batch([sra_id])
        return records[0] if records else {"error": f"SRA record {sra_id} not found"}

    async def sra_fetch_batch(self, sra_ids: Sequence[str]) -> list[dict[str, Any]]:
        clean_ids = [str(item).strip() for item in sra_ids if str(item).strip()]
        if not clean_ids:
            return []
        xml_result = await self._request(
            "efetch",
            db="sra",
            id=",".join(clean_ids),
            retmode="xml",
        )
        try:
            root = ET.fromstring(xml_result)
        except ET.ParseError as exc:
            raise NCBIProtocolError("SRA EFetch returned invalid XML") from exc

        results: list[dict[str, Any]] = []
        for index, package in enumerate(root.findall(".//EXPERIMENT_PACKAGE")):
            experiment = package.find("./EXPERIMENT")
            study_ref = experiment.find("./STUDY_REF") if experiment is not None else None
            sample = package.find("./SAMPLE")
            runs = []
            for run in package.findall("./RUN_SET/RUN"):
                runs.append(
                    {
                        "accession": run.attrib.get("accession", ""),
                        "spots": int(run.attrib.get("total_spots", "0") or 0),
                        "bases": int(run.attrib.get("total_bases", "0") or 0),
                        "size_bytes": int(run.attrib.get("size", "0") or 0),
                    }
                )
            library = experiment.find("./DESIGN/LIBRARY_DESCRIPTOR") if experiment is not None else None
            experiment_accession = experiment.attrib.get("accession", "") if experiment is not None else ""
            results.append(
                {
                    "sra_id": clean_ids[index] if index < len(clean_ids) else experiment_accession,
                    "accession": experiment_accession or (runs[0]["accession"] if runs else ""),
                    "title": _xml_text(experiment.find("./TITLE")) if experiment is not None else "",
                    "study_accession": study_ref.attrib.get("accession", "") if study_ref is not None else "",
                    "sample_accession": sample.attrib.get("accession", "") if sample is not None else "",
                    "organism": _xml_text(sample.find("./SAMPLE_NAME/SCIENTIFIC_NAME")) if sample is not None else "",
                    "library": {
                        "strategy": _xml_text(library.find("./LIBRARY_STRATEGY")) if library is not None else "",
                        "source": _xml_text(library.find("./LIBRARY_SOURCE")) if library is not None else "",
                        "selection": _xml_text(library.find("./LIBRARY_SELECTION")) if library is not None else "",
                        "layout": next(
                            iter(
                                child.tag
                                for child in library.findall("./LIBRARY_LAYOUT/*")
                            ),
                            "",
                        ) if library is not None else "",
                    },
                    "runs": runs,
                    "download": {
                        "prefetch": f"prefetch {runs[0]['accession']}" if runs else "",
                        "fasterq_dump": f"fasterq-dump {runs[0]['accession']} --split-files" if runs else "",
                    },
                }
            )
        return results

    # ---------- GenBank ----------

    @staticmethod
    def _sequence_record(record: Any, *, include_formats: bool = True) -> dict[str, Any]:
        accessions = record.annotations.get("accessions") or [record.id]
        features = []
        for feature in record.features:
            features.append(
                {
                    "type": feature.type,
                    "location": str(feature.location),
                    "qualifiers": feature.qualifiers,
                }
            )
        result: dict[str, Any] = {
            "accession": accessions[0],
            "version": record.id,
            "name": record.name,
            "description": record.description,
            "length": len(record.seq),
            "molecule_type": record.annotations.get("molecule_type", ""),
            "organism": record.annotations.get("organism", ""),
            "taxonomy": record.annotations.get("taxonomy", []),
            "sequence": str(record.seq),
            "features": features,
        }
        if include_formats:
            result["formats"] = {
                "fasta": record.format("fasta"),
                "genbank": record.format("genbank"),
            }
        return result

    async def genbank_fetch(
        self,
        accession: str,
        retmode: str = "xml",
    ) -> dict[str, Any]:
        records = await self.genbank_fetch_batch([accession], output_format=retmode)
        return records[0] if records else {"error": f"GenBank record {accession} not found"}

    async def genbank_fetch_batch(
        self,
        accessions: Sequence[str],
        *,
        output_format: str = "json",
    ) -> list[dict[str, Any]]:
        clean_ids = [str(item).strip() for item in accessions if str(item).strip()]
        if not clean_ids:
            return []
        normalized_format = output_format.lower()
        if normalized_format in {"fasta", "fna"}:
            content = await self._request(
                "efetch", db="nuccore", id=",".join(clean_ids), rettype="fasta", retmode="text"
            )
            return [{"accession": ",".join(clean_ids), "format": "fasta", "content": content}]

        genbank_text = await self._request(
            "efetch",
            db="nuccore",
            id=",".join(clean_ids),
            rettype="gbwithparts",
            retmode="text",
        )
        try:
            records = list(SeqIO.parse(io.StringIO(genbank_text), "genbank"))
        except Exception as exc:
            raise NCBIProtocolError("GenBank EFetch returned an invalid GenBank document") from exc
        if not records and genbank_text.strip():
            raise NCBIProtocolError("GenBank EFetch response contained no records")
        if normalized_format in {"genbank", "gb", "text"}:
            return [{"accession": ",".join(clean_ids), "format": "genbank", "content": genbank_text}]
        return [self._sequence_record(record) for record in records]

    # ---------- BLAST ----------

    async def _blast_request(
        self,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        common = {"TOOL": "research_agent"}
        if self.email:
            common["EMAIL"] = self.email
        if params is not None:
            params = {**params, **common}
        if data is not None:
            data = {**data, **common}
        return await self._http_request(method, self.BLAST_URL, params=params, data=data)

    @staticmethod
    def _parse_blast_hits(xml_result: str, max_results: int) -> list[dict[str, Any]]:
        try:
            root = ET.fromstring(xml_result)
        except ET.ParseError as exc:
            raise NCBIProtocolError("BLAST returned invalid XML") from exc
        hits: list[dict[str, Any]] = []
        for hit in root.findall(".//Hit")[:max_results]:
            hsp = hit.find("./Hit_hsps/Hsp")
            align_len = int(_xml_text(hsp.find("./Hsp_align-len")) or 0) if hsp is not None else 0
            identities = int(_xml_text(hsp.find("./Hsp_identity")) or 0) if hsp is not None else 0
            hits.append(
                {
                    "id": _xml_text(hit.find("./Hit_id")),
                    "accession": _xml_text(hit.find("./Hit_accession")),
                    "description": _xml_text(hit.find("./Hit_def")),
                    "length": int(_xml_text(hit.find("./Hit_len")) or 0),
                    "evalue": float(_xml_text(hsp.find("./Hsp_evalue")) or "inf") if hsp is not None else None,
                    "bit_score": float(_xml_text(hsp.find("./Hsp_bit-score")) or 0) if hsp is not None else None,
                    "identity_count": identities,
                    "alignment_length": align_len,
                    "identity_percent": round((identities / align_len) * 100, 3) if align_len else None,
                    "query_range": [
                        int(_xml_text(hsp.find("./Hsp_query-from")) or 0),
                        int(_xml_text(hsp.find("./Hsp_query-to")) or 0),
                    ] if hsp is not None else None,
                    "subject_range": [
                        int(_xml_text(hsp.find("./Hsp_hit-from")) or 0),
                        int(_xml_text(hsp.find("./Hsp_hit-to")) or 0),
                    ] if hsp is not None else None,
                }
            )
        return hits

    async def blast_search(
        self,
        query_sequence: str,
        database: str = "nt",
        program: str = "blastn",
        max_results: int = 10,
        *,
        max_wait_seconds: float = 120.0,
        poll_interval: float = 2.0,
    ) -> dict[str, Any]:
        program = program.lower().strip()
        database = database.strip()
        sequence = re.sub(r"\s+", "", query_sequence).upper()
        if program not in self._BLAST_PROGRAMS:
            raise ValueError(f"Unsupported BLAST program: {program}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", database):
            raise ValueError("Invalid BLAST database name")
        if not sequence or len(sequence) > 100_000 or not re.fullmatch(r"[A-Z*.-]+", sequence):
            raise ValueError("BLAST sequence must contain 1-100000 valid sequence characters")

        submitted = await self._blast_request(
            method="POST",
            data={
                "CMD": "Put",
                "PROGRAM": program,
                "DATABASE": database,
                "QUERY": sequence,
                "HITLIST_SIZE": max(1, min(int(max_results), 100)),
            },
        )
        rid_match = re.search(r"^\s*RID\s*=\s*(\S+)", submitted, re.MULTILINE)
        rtoe_match = re.search(r"^\s*RTOE\s*=\s*(\d+)", submitted, re.MULTILINE)
        if not rid_match:
            raise NCBIProtocolError("BLAST submission did not return an RID")
        rid = rid_match.group(1)
        estimated_wait = int(rtoe_match.group(1)) if rtoe_match else 0
        deadline = self._monotonic() + max(1.0, max_wait_seconds)
        if estimated_wait:
            await self._sleep(min(float(estimated_wait), max(1.0, poll_interval)))

        while self._monotonic() < deadline:
            status_text = await self._blast_request(
                params={"CMD": "Get", "RID": rid, "FORMAT_OBJECT": "SearchInfo"}
            )
            status_match = re.search(r"Status=(\w+)", status_text)
            status = status_match.group(1).upper() if status_match else "UNKNOWN"
            if status == "READY":
                xml_result = await self._blast_request(
                    params={"CMD": "Get", "RID": rid, "FORMAT_TYPE": "XML"}
                )
                return {
                    "success": True,
                    "status": "READY",
                    "rid": rid,
                    "query_length": len(sequence),
                    "database": database,
                    "program": program,
                    "hits": self._parse_blast_hits(xml_result, max_results),
                }
            if status in {"FAILED", "UNKNOWN"}:
                raise NCBIProtocolError(f"BLAST job {rid} ended with status {status}")
            await self._sleep(max(0.2, poll_interval))
        raise NCBIRequestError(f"BLAST job {rid} did not complete within {max_wait_seconds:g}s")

    # ---------- Gene and links ----------

    async def gene_search(
        self,
        gene_name: str,
        organism: str | None = None,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        term = f"{gene_name.strip()}[Gene]"
        if organism:
            term += f" AND {organism.strip()}[Organism]"
        ids = self._esearch_ids(
            await self._request_json(
                "esearch",
                db="gene",
                term=term,
                retmax=max(1, min(int(max_results), 100)),
                retmode="json",
            )
        )
        return await self.gene_fetch_batch(ids)

    async def gene_fetch_batch(self, gene_ids: Sequence[str]) -> list[dict[str, Any]]:
        clean_ids = [str(item).strip() for item in gene_ids if str(item).strip()]
        if not clean_ids:
            return []
        payload = await self._request_json(
            "esummary", db="gene", id=",".join(clean_ids), retmode="json"
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise NCBIProtocolError("Gene ESummary response is missing result")
        records = []
        for gene_id in clean_ids:
            item = result.get(gene_id)
            if not isinstance(item, dict):
                continue
            organism = item.get("organism") if isinstance(item.get("organism"), dict) else {}
            records.append(
                {
                    "gene_id": gene_id,
                    "name": item.get("name", ""),
                    "description": item.get("description", ""),
                    "summary": item.get("summary", ""),
                    "chromosome": item.get("chromosome", ""),
                    "map_location": item.get("maplocation", ""),
                    "organism": organism.get("scientificname", ""),
                }
            )
        return records

    async def link_datasets(self, source_db: str, source_id: str, target_db: str) -> list[str]:
        payload = await self._request_json(
            "elink",
            dbfrom=source_db,
            id=source_id,
            db=target_db,
            retmode="json",
        )
        links: list[str] = []
        for linkset in payload.get("linksets", []):
            if not isinstance(linkset, dict):
                continue
            for link_db in linkset.get("linksetdbs", []):
                if isinstance(link_db, dict):
                    links.extend(str(item) for item in link_db.get("links", []))
        return links

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.aclose()
            self._session = None


_adapters: dict[str, NCBIAdapter] = {}


def get_ncbi_adapter(db_session: AsyncSession | None = None) -> NCBIAdapter:
    """Return a loop-local adapter for built-in skills."""
    try:
        loop_key = str(id(asyncio.get_running_loop()))
    except RuntimeError:
        loop_key = "no-loop"
    key = f"{loop_key}:{id(db_session) if db_session else 'default'}"
    if key not in _adapters:
        _adapters[key] = NCBIAdapter(db_session)
    return _adapters[key]


__all__ = [
    "NCBIAdapter",
    "NCBIError",
    "NCBIRequestError",
    "NCBIProtocolError",
    "get_ncbi_adapter",
]
