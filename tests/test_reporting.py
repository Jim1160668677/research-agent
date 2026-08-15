"""研究简报生成与渲染测试。"""

from fastapi.testclient import TestClient

from research_agent.core.app import create_app
from research_agent.reporting.brief import build_brief_markdown
from research_agent.reporting.pdf import registered_font, render_html, render_pdf


def _sample_run() -> dict:
    return {
        "id": "run-brief-1",
        "objective": "系统评价某干预的疗效并生成论文框架",
        "status": "completed",
        "progress": 100,
        "created_at": "2026-08-15T10:00:00",
        "completed_at": "2026-08-15T10:05:00",
        "plan": {
            "id": "plan-1",
            "domains": ["literature", "writing", "integrity"],
            "review_gates": ["writing", "integrity"],
        },
        "steps": [
            {
                "key": "literature",
                "title": "文献调研",
                "capability": "literature_search",
                "status": "completed",
                "confidence": 0.9,
                "duration_ms": 1200,
                "warnings": [],
                "dependencies": [],
                "output": {"summary": "检索到 25 篇文献"},
            },
            {
                "key": "writing",
                "title": "写作框架",
                "capability": "research_writing",
                "status": "completed",
                "confidence": 0.8,
                "duration_ms": 900,
                "warnings": ["引用格式待核"],
                "dependencies": ["literature"],
                "output": {},
            },
        ],
        "evidence": [
            {
                "source_type": "pubmed",
                "id": "123",
                "locator": "https://pubmed.ncbi.nlm.nih.gov/123/",
            }
        ],
        "result": {
            "status": "completed_with_gaps",
            "has_gaps": True,
            "confidence": 0.85,
            "warnings": ["引用格式待核"],
            "failed_or_blocked_steps": [],
            "review_required": ["writing", "integrity"],
            "provenance": {"runtime": "research-runtime-v1", "evidence_count": 1},
        },
        "budget": {},
        "policy": {},
    }


def test_brief_markdown_contains_objective_evidence_and_gaps():
    markdown = build_brief_markdown(
        _sample_run(),
        [{"name": "measurements.csv", "kind": "table", "size_bytes": 123, "sha256": "abc"}],
        [{
            "pipeline_id": "nf-core/rnaseq",
            "revision": "3.26.0",
            "profile": "docker",
            "status": "completed",
            "task_summary": {"tasks": 234, "statuses": {"COMPLETED": 234}, "failed": []},
        }],
    )
    assert "系统评价某干预的疗效并生成论文框架" in markdown
    assert "research-runtime-v1" in markdown
    assert "证据清单（1 条）" in markdown
    assert "pubmed" in markdown
    assert "缺口与限制" in markdown
    assert "引用格式待核" in markdown
    assert "nf-core/rnaseq" in markdown
    assert "审查门：writing, integrity" in markdown


def test_brief_markdown_handles_empty_run():
    markdown = build_brief_markdown({"id": "x", "objective": "空任务", "plan": {}, "result": {}, "steps": [], "evidence": []})
    assert "空任务" in markdown
    assert "（无输入材料）" in markdown


def test_pdf_render_has_pdf_header():
    markdown = build_brief_markdown(_sample_run())
    pdf = render_pdf(markdown, title="测试简报")
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 2000


def test_pdf_registers_cjk_font_on_windows():
    font = registered_font()
    if font is None:
        import sys
        if sys.platform == "win32":
            raise AssertionError("Windows 环境应注册到中文字体")
    else:
        assert font in {"MSYH", "SimSun", "SimHei", "DengXian", "NotoSansCJK"}


def test_html_render_contains_table_and_heading():
    markdown = build_brief_markdown(_sample_run())
    page = render_html(markdown)
    assert "<table>" in page
    assert "<h1>研究简报</h1>" in page
    assert "pubmed" in page


def test_report_api_returns_pdf_and_marks_own_run_only(monkeypatch):
    from research_agent.core.app import settings

    monkeypatch.setattr(settings, "debug", False)
    with TestClient(create_app()) as client:
        owner = client.post("/api/v1/auth/setup", json={
            "username": "brief_owner",
            "email": "brief-owner@example.org",
            "password": "secure-brief-password",
        }).json()
        other = client.post("/api/v1/auth/register", json={
            "username": "brief_other",
            "email": "brief-other@example.org",
            "password": "secure-brief-password",
        }).json()
        owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}

        created = client.post("/api/v1/research/runs", headers=owner_headers, json={
            "objective": "设计一项体外实验并生成论文结构和学术规范检查",
            "domains": ["experiment", "writing", "integrity"],
            "network_allowed": False,
            "execute": True,
        })
        assert created.status_code == 201
        run_id = created.json()["id"]
        for _ in range(80):
            detail = client.get(f"/api/v1/research/runs/{run_id}", headers=owner_headers).json()
            if detail["status"] in {"completed", "failed", "cancelled"}:
                break
            __import__("time").sleep(0.05)
        assert detail["status"] == "completed"

        pdf = client.post(f"/api/v1/research/runs/{run_id}/report", headers=owner_headers, json={"format": "pdf"})
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content[:5] == b"%PDF-"

        md = client.post(f"/api/v1/research/runs/{run_id}/report", headers=owner_headers, json={"format": "md"})
        assert md.status_code == 200
        assert "text/markdown" in md.headers["content-type"]
        assert "设计一项体外实验" in md.text

        html_report = client.post(f"/api/v1/research/runs/{run_id}/report", headers=owner_headers, json={"format": "html"})
        assert html_report.status_code == 200
        assert "<table>" in html_report.text

        denied = client.post(f"/api/v1/research/runs/{run_id}/report", headers=other_headers, json={"format": "pdf"})
        assert denied.status_code == 404

        bad_format = client.post(f"/api/v1/research/runs/{run_id}/report", headers=owner_headers, json={"format": "docx"})
        assert bad_format.status_code == 422
