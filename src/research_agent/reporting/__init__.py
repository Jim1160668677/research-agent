"""研究简报生成：Markdown 组装与 PDF/HTML 渲染。"""

from .brief import build_brief_markdown
from .pdf import render_html, render_pdf

__all__ = ["build_brief_markdown", "render_pdf", "render_html"]
