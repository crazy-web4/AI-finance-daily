"""
Notion 导入 JSON 导出（建议 #4 · T-B4）
日报 → Notion blocks 数组，可直接作为 pages/{page_id}/children 的 children POST 到 Notion API。
参考: https://developers.notion.com/reference/block-object
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.models import DailyReport


def _rt(text: str, bold: bool = False) -> list[dict]:
    """构造 rich_text 数组（Notion 单段文本上限 2000 字符，这里简单截断）。"""
    text = (text or "").strip()
    if len(text) > 1900:
        text = text[:1900] + "…"
    return [{"type": "text", "text": {"content": text}, "annotations": {"bold": bold}}]


def _heading(level: int, text: str) -> dict:
    key = {1: "heading_1", 2: "heading_2", 3: "heading_3"}[level]
    return {"object": "block", "type": key, key: {"rich_text": _rt(text)}}


def _para(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rt(text)}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _rt(text)}}


def _quote(text: str) -> dict:
    return {"object": "block", "type": "quote", "quote": {"rich_text": _rt(text)}}


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def report_to_notion_blocks(report: DailyReport, title: str = "AI 行业全球动态日报") -> list[dict]:
    blocks: list[dict] = []
    blocks.append(_heading(1, f"{title} · {report.report_date}"))
    blocks.append(_para(f"总条目 {report.total_items} ｜ 总字数 {report.total_word_count}"))

    if report.editor_summary:
        blocks.append(_heading(2, "📌 今日导读"))
        blocks.append(_quote(report.editor_summary))

    for section in report.sections:
        if section.item_count == 0:
            continue
        blocks.append(_heading(2, f"{section.section_name}（{section.item_count}）"))
        for item in section.items:
            blocks.append(_heading(3, f"{item.rank}. {item.title}"))
            if item.key_data:
                for kd in item.key_data:
                    blocks.append(_bullet(f"{kd.label}：{kd.value}"))
            for para in (item.details or "").replace("\r\n", "\n").split("\n\n"):
                if para.strip():
                    blocks.append(_para(para.strip()))
            if item.analysis:
                blocks.append(_quote(f"编辑点评：{item.analysis.strip()}"))
            if item.sources:
                blocks.append(_bullet("来源：" + "；".join(f"{s.name} {s.url}" for s in item.sources)))

    if report.quality_flags:
        blocks.append(_divider())
        blocks.append(_heading(3, "⚠️ 质量标记"))
        for flag in report.quality_flags:
            blocks.append(_bullet(flag))
    return blocks


def report_to_notion_json(report: DailyReport) -> dict:
    """返回可直接 POST 的 payload 骨架（children 为 blocks）。"""
    return {
        "parent": {"page_id": "REPLACE_WITH_PAGE_ID"},
        "properties": {
            "title": [{"type": "text", "text": {"content": f"AI 日报 {report.report_date}"}}]
        },
        "children": report_to_notion_blocks(report),
    }


def export_notion(report: DailyReport, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{report.report_date}_notion.json"
    path.write_text(
        json.dumps(report_to_notion_json(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
