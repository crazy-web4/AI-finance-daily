"""
Markdown 导出（建议 #4 · T-B4）
日报 → GFM Markdown，可被 Typora / VSCode / GitHub 正确渲染。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.models import DailyReport


def report_to_markdown(report: DailyReport, title: str = "AI 行业全球动态日报") -> str:
    lines: list[str] = []
    lines.append(f"# {title} · {report.report_date}")
    lines.append("")
    meta = f"> 总条目 {report.total_items} ｜ 总字数 {report.total_word_count} ｜ 生成于 {report.generated_at:%Y-%m-%d %H:%M} UTC"
    lines.append(meta)
    lines.append("")

    if report.editor_summary:
        lines.append("## 📌 今日导读")
        lines.append("")
        lines.append(report.editor_summary.strip())
        lines.append("")

    for section in report.sections:
        if section.item_count == 0:
            continue
        lines.append(f"## {section.section_name}")
        lines.append("")
        for item in section.items:
            lines.append(f"### {item.rank}. {item.title}")
            lines.append("")
            if item.key_data:
                for kd in item.key_data:
                    lines.append(f"- **{kd.label}**：{kd.value}")
                if item.key_data:
                    lines.append("")
            for para in _split_paras(item.details):
                lines.append(para)
                lines.append("")
            if item.analysis:
                lines.append(f"> **编辑点评**：{item.analysis.strip()}")
                lines.append("")
            if item.sources:
                lines.append("**来源**：")
                for src in item.sources:
                    official = "（官方）" if src.is_official else ""
                    lines.append(f"- [{src.name}]({src.url}){official}")
                lines.append("")
        lines.append("")

    if report.quality_flags:
        lines.append("---")
        lines.append("")
        lines.append("### ⚠️ 质量标记")
        lines.append("")
        for flag in report.quality_flags:
            lines.append(f"- {flag}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _split_paras(text: str | None) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]


def export_markdown(report: DailyReport, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{report.report_date}.md"
    path.write_text(report_to_markdown(report), encoding="utf-8")
    return path
