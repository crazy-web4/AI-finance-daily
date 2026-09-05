"""
公众号富文本导出（建议 #4 · T-B4）
日报 → 微信公众号可粘贴的 HTML 块（标题 + 每事件独立段落，字号克制，图片 alt 完整）。
所有样式 inline，无外部依赖资源。
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
        f'<p style="margin:10px 0;line-height:1.75;font-size:15px;color:#333;">{_esc(p)}</p>'
        for p in chunks
    )


def report_to_wechat_html(report: DailyReport) -> str:
    parts: list[str] = []
    parts.append('<section style="font-family:-apple-system,PingFang SC,Helvetica,Arial,sans-serif;max-width:677px;margin:0 auto;padding:16px;">')
    parts.append(f'<h1 style="font-size:22px;font-weight:700;text-align:center;color:#1a1a1a;margin:8px 0 4px;">AI 行业全球动态日报 · {_esc(report.report_date)}</h1>')
    parts.append(f'<p style="text-align:center;color:#999;font-size:13px;margin:0 0 16px;">总条目 {report.total_items} ｜ 总字数 {report.total_word_count}</p>')

    if report.editor_summary:
        parts.append('<section style="background:#f6f7f9;border-left:4px solid #5b8def;padding:10px 14px;margin:14px 0;border-radius:4px;">')
        parts.append(f'<p style="margin:0;line-height:1.7;font-size:14px;color:#555;">📌 <strong>今日导读</strong>：{_esc(report.editor_summary)}</p>')
        parts.append('</section>')

    for section in report.sections:
        if section.item_count == 0:
            continue
        parts.append(f'<h2 style="font-size:18px;color:#fff;background:#2b6cb0;display:inline-block;padding:4px 12px;border-radius:4px;margin:22px 0 10px;">{_esc(section.section_name)}</h2>')
        for item in section.items:
            parts.append('<section style="margin:16px 0;padding-bottom:12px;border-bottom:1px solid #eee;">')
            parts.append(f'<h3 style="font-size:16px;font-weight:600;color:#111;margin:6px 0;line-height:1.5;">{item.rank}. {_esc(item.title)}</h3>')
            if item.key_data:
                kd = " ｜ ".join(f"{_esc(k.label)}：{_esc(k.value)}" for k in item.key_data)
                parts.append(f'<p style="margin:6px 0;font-size:14px;color:#c05621;font-weight:600;">{kd}</p>')
            parts.append(_paras(item.details))
            if item.analysis:
                parts.append(f'<p style="margin:10px 0;font-size:14px;color:#4a5568;background:#fffaf0;padding:8px 10px;border-radius:4px;">💡 <strong>编辑点评</strong>：{_esc(item.analysis)}</p>')
            if item.sources:
                src = " ｜ ".join(
                    f'<a href="{_esc(str(s.url))}" style="color:#3182ce;text-decoration:none;">{_esc(s.name)}</a>'
                    + ("（官方）" if s.is_official else "")
                    for s in item.sources
                )
                parts.append(f'<p style="margin:8px 0 0;font-size:12px;color:#888;">来源：{src}</p>')
            parts.append('</section>')

    if report.quality_flags:
        parts.append('<section style="margin-top:18px;padding:10px 14px;background:#fff5f5;border-radius:4px;">')
        parts.append('<p style="margin:0;font-size:13px;color:#c53030;">⚠️ 质量标记</p>')
        for flag in report.quality_flags:
            parts.append(f'<p style="margin:4px 0;font-size:12px;color:#c53030;">· {_esc(flag)}</p>')
        parts.append('</section>')

    parts.append('</section>')
    return "\n".join(parts)


def export_wechat(report: DailyReport, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{report.report_date}_wechat.html"
    path.write_text(report_to_wechat_html(report), encoding="utf-8")
    return path
