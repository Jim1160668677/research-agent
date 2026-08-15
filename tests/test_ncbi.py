"""Protocol-level tests for the NCBI adapter."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx
import pytest

from research_agent.ncbi_skills.adapter import (
    NCBIAdapter,
    NCBIProtocolError,
)

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation>
<PMID>12345678</PMID><Article><ArticleTitle>CRISPR test</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">Evidence text.</AbstractText></Abstract>
<AuthorList><Author><ForeName>Ada</ForeName><LastName>Lovelace</LastName></Author></AuthorList>
<Journal><Title>Test Journal</Title><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
</Article></MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="doi">10.1000/test</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""


SRA_XML = """<?xml version="1.0"?>
<EXPERIMENT_PACKAGE_SET><EXPERIMENT_PACKAGE>
<EXPERIMENT accession="SRX000001"><TITLE>RNA-seq experiment</TITLE>
<STUDY_REF accession="SRP000001"/><DESIGN><LIBRARY_DESCRIPTOR>
<LIBRARY_STRATEGY>RNA-Seq</LIBRARY_STRATEGY><LIBRARY_SOURCE>TRANSCRIPTOMIC</LIBRARY_SOURCE>
<LIBRARY_SELECTION>cDNA</LIBRARY_SELECTION><LIBRARY_LAYOUT><PAIRED/></LIBRARY_LAYOUT>
</LIBRARY_DESCRIPTOR></DESIGN></EXPERIMENT>
<SAMPLE accession="SRS000001"><SAMPLE_NAME><SCIENTIFIC_NAME>Homo sapiens</SCIENTIFIC_NAME></SAMPLE_NAME></SAMPLE>
<RUN_SET><RUN accession="SRR000001" total_spots="10" total_bases="1000" size="500"/></RUN_SET>
</EXPERIMENT_PACKAGE></EXPERIMENT_PACKAGE_SET>"""


GENBANK_TEXT = """LOCUS       TEST0001                 12 bp    DNA     linear   SYN 01-JAN-2026
DEFINITION  Synthetic test sequence.
ACCESSION   TEST0001
VERSION     TEST0001.1
KEYWORDS    .
SOURCE      synthetic construct
  ORGANISM  synthetic construct
            other sequences; artificial sequences.
FEATURES             Location/Qualifiers
     source          1..12
                     /organism="synthetic construct"
                     /mol_type="other DNA"
ORIGIN
        1 atgcgtacgtag
//
"""


BLAST_XML = """<?xml version="1.0"?>
<BlastOutput><BlastOutput_iterations><Iteration><Iteration_hits><Hit>
<Hit_id>ref|NM_1|</Hit_id><Hit_def>example hit</Hit_def><Hit_accession>NM_1</Hit_accession><Hit_len>20</Hit_len>
<Hit_hsps><Hsp><Hsp_bit-score>42</Hsp_bit-score><Hsp_evalue>1e-8</Hsp_evalue>
<Hsp_query-from>1</Hsp_query-from><Hsp_query-to>20</Hsp_query-to>
<Hsp_hit-from>2</Hsp_hit-from><Hsp_hit-to>21</Hsp_hit-to>
<Hsp_identity>19</Hsp_identity><Hsp_align-len>20</Hsp_align-len></Hsp></Hit_hsps>
</Hit></Iteration_hits></Iteration></BlastOutput_iterations></BlastOutput>"""


def make_adapter(handler, *, sleep=None, max_retries=0):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return NCBIAdapter(
        http_client=client,
        sleep=sleep or AsyncMock(),
        max_retries=max_retries,
    ), client


@pytest.mark.asyncio
async def test_pubmed_search_uses_json_esearch_and_batch_xml_fetch():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/esearch.fcgi"):
            assert request.url.params["retmode"] == "json"
            return httpx.Response(
                200,
                json={"esearchresult": {"idlist": ["12345678"]}},
                request=request,
            )
        assert request.url.path.endswith("/efetch.fcgi")
        assert request.url.params["id"] == "12345678"
        return httpx.Response(200, text=PUBMED_XML, request=request)

    adapter, client = make_adapter(handler)
    try:
        results = await adapter.pubmed_search("CRISPR", max_results=10)
    finally:
        await client.aclose()

    assert len(requests) == 2
    assert results == [
        {
            "pmid": "12345678",
            "title": "CRISPR test",
            "abstract": "BACKGROUND: Evidence text.",
            "authors": ["Ada Lovelace"],
            "journal": "Test Journal",
            "year": "2026",
            "doi": "10.1000/test",
            "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        }
    ]


@pytest.mark.asyncio
async def test_sra_search_fetches_batch_once_and_returns_structured_metadata():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/esearch.fcgi"):
            return httpx.Response(
                200,
                json={"esearchresult": {"idlist": ["101"]}},
                request=request,
            )
        return httpx.Response(200, text=SRA_XML, request=request)

    adapter, client = make_adapter(handler)
    try:
        results = await adapter.sra_search("human RNA-seq")
    finally:
        await client.aclose()

    assert calls.count("/entrez/eutils/efetch.fcgi") == 1
    assert results[0]["accession"] == "SRX000001"
    assert results[0]["organism"] == "Homo sapiens"
    assert results[0]["library"]["layout"] == "PAIRED"
    assert results[0]["runs"][0]["accession"] == "SRR000001"


@pytest.mark.asyncio
async def test_genbank_normalizes_and_converts_formats():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["rettype"] == "gbwithparts"
        return httpx.Response(200, text=GENBANK_TEXT, request=request)

    adapter, client = make_adapter(handler)
    try:
        result = await adapter.genbank_fetch("TEST0001", retmode="json")
    finally:
        await client.aclose()

    assert result["accession"] == "TEST0001"
    assert result["length"] == 12
    assert result["sequence"] == "ATGCGTACGTAG"
    assert result["formats"]["fasta"].startswith(">TEST0001.1")
    assert "LOCUS" in result["formats"]["genbank"]


@pytest.mark.asyncio
async def test_blast_uses_put_poll_get_protocol_and_parses_hits():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            form = parse_qs(request.content.decode())
            assert form["CMD"] == ["Put"]
            assert form["PROGRAM"] == ["blastn"]
            assert form["DATABASE"] == ["nt"]
            return httpx.Response(200, text="RID = TEST_RID\nRTOE = 0\n", request=request)
        if request.url.params.get("FORMAT_OBJECT") == "SearchInfo":
            return httpx.Response(200, text="Status=READY\nThereAreHits=yes\n", request=request)
        return httpx.Response(200, text=BLAST_XML, request=request)

    adapter, client = make_adapter(handler)
    try:
        result = await adapter.blast_search("ACTGACTGACTGACTGACTG")
    finally:
        await client.aclose()

    assert [call.method for call in calls] == ["POST", "GET", "GET"]
    assert result["success"] is True
    assert result["rid"] == "TEST_RID"
    assert result["hits"][0]["accession"] == "NM_1"
    assert result["hits"][0]["identity_percent"] == 95.0


@pytest.mark.asyncio
async def test_retry_after_rate_limit_then_success():
    attempts = 0
    sleep = AsyncMock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0.01"}, request=request)
        return httpx.Response(
            200,
            json={"esearchresult": {"idlist": []}},
            request=request,
        )

    adapter, client = make_adapter(handler, sleep=sleep, max_retries=1)
    try:
        assert await adapter.pubmed_search("nothing") == []
    finally:
        await client.aclose()

    assert attempts == 2
    assert any(call.args == (0.01,) for call in sleep.await_args_list)


@pytest.mark.asyncio
async def test_invalid_json_is_a_protocol_error_not_an_empty_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>", request=request)

    adapter, client = make_adapter(handler)
    try:
        with pytest.raises(NCBIProtocolError, match="invalid JSON"):
            await adapter.pubmed_search("BRCA1")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_settings_are_not_required_for_a_mocked_request():
    with patch("research_agent.ncbi_skills.adapter.settings") as mocked:
        mocked.ncbi_api_key = ""
        mocked.ncbi_email = "test@example.com"
        mocked.version = "test"

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["email"] == "test@example.com"
            return httpx.Response(
                200,
                content=json.dumps({"esearchresult": {"idlist": []}}).encode(),
                request=request,
            )

        adapter, client = make_adapter(handler)
        try:
            assert await adapter.sra_search("no results") == []
        finally:
            await client.aclose()
