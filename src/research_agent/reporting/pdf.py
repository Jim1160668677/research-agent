"""研究简报渲染：reportlab PDF 与极简 HTML。

PDF 使用平台中文字体（Windows 微软雅黑/宋体等），找不到时回退
Helvetica 并只保证 ASCII 内容可读。HTML 为模板输出语法子集的
极简转换器，避免引入第三方 Markdown 依赖。
"""

from __future__ import annotations

import html
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_CJK_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("MSYH", r"C:\Windows\Fonts\msyh.ttc"),
    ("SimSun", r"C:\Windows\Fonts\simsun.ttc"),
    ("SimHei", r"C:\Windows\Fonts\simhei.ttf"),
    ("DengXian", r"C:\Windows\Fonts\Deng.ttf"),
    ("NotoSansCJK", r"C:\Windows\Fonts\NotoSansCJK-Regular.ttc"),
)

_registered_font: str | None = None


def registered_font() -> str | None:
    """返回已注册的中文字体名；未找到时返回 None。"""
    global _registered_font
    if _registered_font is not None:
        return _registered_font
    for name, path in _CJK_CANDIDATES:
        if not Path(path).exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
            _registered_font = name
            return name
        except Exception:
            continue
    return None


def _escape(value: str) -> str:
    return html.escape(value, quote=False)


def _inline(value: str) -> str:
    """极简行内 Markdown（**粗体**、`代码`）转 PDF 段落 XML。"""
    value = _escape(value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`([^`]+)`", r"<font face='Courier' size='8'>\1</font>", value)
    return value


def _table_flowable(rows: list[list[str]]) -> Table:
    table = Table(rows, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8cdd4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _markdown_to_flowables(markdown: str, base_font: str) -> list[Any]:
    styles = getSampleStyleSheet()
    font_kwargs = {"fontName": base_font} if base_font else {}
    title_style = ParagraphStyle(
        "BriefTitle", parent=styles["Title"], fontSize=17, leading=22, spaceAfter=6, **font_kwargs
    )
    h2_style = ParagraphStyle(
        "BriefH2", parent=styles["Heading2"], fontSize=13, leading=17, spaceBefore=10, spaceAfter=4,
        textColor=colors.HexColor("#1f3b5c"), **font_kwargs,
    )
    h3_style = ParagraphStyle(
        "BriefH3", parent=styles["Heading3"], fontSize=11, leading=15, spaceBefore=6, spaceAfter=2,
        **font_kwargs,
    )
    body_style = ParagraphStyle(
        "BriefBody", parent=styles["BodyText"], fontSize=9.5, leading=14, alignment=TA_LEFT,
        spaceAfter=3, **font_kwargs,
    )
    quote_style = ParagraphStyle(
        "BriefQuote", parent=body_style, textColor=colors.HexColor("#666666"),
        leftIndent=8, borderPadding=2, **font_kwargs,
    )
    code_style = ParagraphStyle(
        "BriefCode", parent=body_style, fontName="Courier", fontSize=8, leading=10,
        backColor=colors.HexColor("#f4f4f4"), borderPadding=4,
    )

    flowables: list[Any] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            block: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            flowables.append(Preformatted("\n".join(block), code_style))
            continue
        if line.startswith("# "):
            flowables.append(Paragraph(_inline(line[2:]), title_style))
        elif line.startswith("## "):
            flowables.append(Paragraph(_inline(line[3:]), h2_style))
        elif line.startswith("### "):
            flowables.append(Paragraph(_inline(line[4:]), h3_style))
        elif line.startswith("> "):
            flowables.append(Paragraph(_inline(line[2:]), quote_style))
        elif line.startswith("| "):
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                    rows.append([_inline(cell) for cell in cells])
                index += 1
            if rows:
                flowables.append(_table_flowable(rows))
                flowables.append(Spacer(1, 4))
            continue
        elif line.startswith("- "):
            items: list[Any] = []
            while index < len(lines) and lines[index].startswith("- "):
                items.append(ListItem(Paragraph(_inline(lines[index][2:]), body_style), leftIndent=6))
                index += 1
            flowables.append(ListFlowable(items, bulletType="bullet", start="•", bulletFontSize=8))
            continue
        elif not line.strip():
            flowables.append(Spacer(1, 3))
        else:
            flowables.append(Paragraph(_inline(line), body_style))
        index += 1
    return flowables


def render_pdf(markdown: str, title: str = "研究简报") -> bytes:
    """将简报 Markdown 渲染为 PDF 字节流。"""
    base_font = registered_font()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title,
        author="Research Agent",
    )
    doc.build(_markdown_to_flowables(markdown, base_font or ""))
    return buffer.getvalue()


def render_html(markdown: str) -> str:
    """将简报 Markdown 渲染为 HTML 文档字符串。"""
    body = _markdown_to_html(markdown)
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<title>研究简报</title><style>"
        "body{font-family:'Microsoft YaHei',sans-serif;max-width:880px;margin:24px auto;"
        "padding:0 16px;line-height:1.7;color:#222}"
        "h1{border-bottom:2px solid #1f3b5c;padding-bottom:6px}"
        "h2{color:#1f3b5c;margin-top:28px}"
        "table{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}"
        "th,td{border:1px solid #c8cdd4;padding:6px 10px;text-align:left}"
        "th{background:#eef2f7}blockquote{color:#666;border-left:3px solid #ccc;margin:8px 0;padding-left:12px}"
        "code{background:#f4f4f4;padding:1px 4px;border-radius:3px;font-size:13px}"
        "li{margin:2px 0}</style></head><body>"
        f"{body}</body></html>"
    )


def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    index = 0
    in_code = False
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            in_code = not in_code
            if in_code:
                out.append("<pre><code>")
            else:
                out.append("</code></pre>")
            index += 1
            continue
        if in_code:
            out.append(_escape(line))
        elif line.startswith("# "):
            out.append(f"<h1>{_escape(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{_escape(line[3:])}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{_escape(line[4:])}</h3>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{_escape(line[2:])}</blockquote>")
        elif line.startswith("| "):
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                    rows.append(cells)
                index += 1
            if rows:
                table = ["<table>"]
                for row_index, row in enumerate(rows):
                    tag = "th" if row_index == 0 else "td"
                    table.append(f"<tr>{''.join(f'<{tag}>{_escape(cell)}</{tag}>' for cell in row)}</tr>")
                table.append("</table>")
                out.append("".join(table))
            continue
        elif line.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].startswith("- "):
                items.append(f"<li>{_escape(lines[index][2:])}</li>")
                index += 1
            out.append(f"<ul>{''.join(items)}</ul>")
            continue
        elif not line.strip():
            out.append("<p></p>")
        else:
            out.append(f"<p>{_escape(line)}</p>")
        index += 1
    return "\n".join(out)
