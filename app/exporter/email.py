"""
邮件版 HTML 导出（建议 #4 · T-B4）
日报 → inline CSS、无外部依赖的邮件 HTML，可直接用 Gmail / SMTP 发送。
采用 table/inline-style 兼容老旧邮件客户端。
"""

from __future__ import annotations

import html
from pathlib import Path

from app.schemas.models import DailyReport


def _esc(text: str | None) -> str:
    return html.escape((text or "").strip())


def _paras(text: str | None) -> str:
    if not text:
        return ""
    chunks = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    return "".join(
        f'<p style="margin:8px 0;line-height:1.7;font-size:14px;color:#333;">{_esc(p)}</p>'
        for p in chunks
    )


def report_to_email_html(report: DailyReport) -> str:
    rows: list[str] = []
    rows.append('<div style="max-width:640px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;">')
    rows.append(f'<h1 style="font-size:20px;color:#1a202c;border-bottom:3px solid #2b6cb0;padding-bottom:8px;">AI 行业全球动态日报 · {_esc(report.report_date)}</h1>')
    rows.append(f'<p style="color:#718096;font-size:13px;">总条目 {report.total_items} ｜ 总字数 {report.total_word_count}</p>')

    if report.editor_summary:
        rows.append(f'<div style="background:#ebf8ff;border-left:4px solid #2b6cb0;padding:10px 14px;margin:12px 0;"><p style="margin:0;font-size:14px;color:#2c5282;">📌 {_esc(report.editor_summary)}</p></div>')

    for section in report.sections:
        if section.item_count == 0:
            continue
        rows.append(f'<h2 style="font-size:16px;color:#2b6cb0;margin:20px 0 8px;border-bottom:1px solid #e2e8f0;padding-bottom:4px;">{_esc(section.section_name)}（{section.item_count}）</h2>')
        for item in section.items:
            rows.append('<div style="margin:12px 0;padding:10px;border:1px solid #edf2f7;border-radius:6px;">')
            rows.append(f'<p style="margin:0 0 6px;font-size:15px;font-weight:bold;color:#1a202c;">{item.rank}. {_esc(item.title)}</p>')
            if item.key_data:
                kd = " ｜ ".join(f"{_esc(k.label)}: {_esc(k.value)}" for k in item.key_data)
                rows.append(f'<p style="margin:4px 0;font-size:13px;color:#c05621;">{kd}</p>')
            rows.append(_paras(item.details))
            if item.sources:
                links = " ｜ ".join(
                    f'<a href="{_esc(str(s.url))}" style="color:#3182ce;">{_esc(s.name)}</a>' for s in item.sources
                )
                rows.append(f'<p style="margin:6px 0 0;font-size:12px;color:#a0aec0;">来源: {links}</p>')
            rows.append('</div>')

    if report.quality_flags:
        rows.append('<div style="margin-top:16px;padding:8px 12px;background:#fff5f5;border-radius:6px;">')
        for flag in report.quality_flags:
            rows.append(f'<p style="margin:3px 0;font-size:12px;color:#c53030;">⚠️ {_esc(flag)}</p>')
        rows.append('</div>')

    rows.append('<p style="margin-top:20px;font-size:11px;color:#cbd5e0;text-align:center;">本邮件由 AI 财经日报自动生成</p>')
    rows.append('</div>')
    return "\n".join(rows)


def email_subject(report: DailyReport) -> str:
    return f"AI 行业全球动态日报 · {report.report_date}（{report.total_items} 条）"


def export_email(report: DailyReport, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{report.report_date}_email.html"
    path.write_text(report_to_email_html(report), encoding="utf-8")
    return path
