"""
周报自动聚合（建议 #9 · T-C9）
=================================================
把一周（周一~周日）的多份日报合并为 1 份周报：
本周 TOP 公司动态 / TOP 融资 / 模型发布节奏 / 政策大事记 / 头条时间轴。

产物写入 ``data/reports/weekly/{week_start}/``：
- ``周报_{mon}_to_{sun}.md``    始终生成
- ``周报_{mon}_to_{sun}.html`` 始终生成（自包含 inline CSS）
- ``周报_{mon}_to_{sun}.pdf``   playwright 可用时生成（否则跳过并标记）

聚合逻辑为纯函数，便于基于 mock 数据集单测。
"""

from __future__ import annotations

import html
from collections import Counter, OrderedDict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from app.schemas.models import DailyReport
from app.storage.entities import extract_companies
from app.storage.report_store import ReportStore
from app.utils.timeutil import report_now


def week_range(anchor: str | date) -> tuple[str, str]:
    """返回锚点所在周的 (周一, 周日) 日期字符串。"""
    d = date.fromisoformat(anchor) if isinstance(anchor, str) else anchor
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def load_week_reports(store: ReportStore, anchor: str | date) -> tuple[list[tuple[str, DailyReport]], str, str]:
    mon, sun = week_range(anchor)
    out: list[tuple[str, DailyReport]] = []
    for d in store.report_dates():
        if mon <= d <= sun:
            rep = store.load_report(d)
            if rep is not None:
                out.append((d, rep))
    return out, mon, sun


def _all_items(reports: list[tuple[str, DailyReport]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for d, rep in reports:
        for sec in rep.sections:
            sid = sec.section_id.value if hasattr(sec.section_id, "value") else str(sec.section_id)
            for it in sec.items:
                items.append({
                    "date": d,
                    "section_id": sid,
                    "section_name": sec.section_name,
                    "rank": it.rank,
                    "title": it.title,
                    "details": it.details,
                    "analysis": it.analysis,
                    "companies": extract_companies(f"{it.title} {it.details}"),
                    "key_data": [{"label": k.label, "value": k.value} for k in it.key_data],
                })
    return items


def _dedup_titles(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按公司+关键词去重（同一事件多天报道只保留信息最全的一条）。"""
    kept: list[dict[str, Any]] = []
    seen_keys: list[frozenset] = []
    for it in sorted(items, key=lambda x: (x["date"], -len(x["details"] or "")), reverse=True):
        tokens = frozenset(__import__("re").findall(r"[A-Za-z0-9\.]+|[\u4e00-\u9fff]{2,}", it["title"]))
        is_dup = False
        for sk in seen_keys:
            union = tokens | sk
            if union and len(tokens & sk) / len(union) >= 0.5:
                is_dup = True
                break
        if not is_dup:
            seen_keys.append(tokens)
            kept.append(it)
    return kept


def aggregate_weekly(reports: list[tuple[str, DailyReport]], mon: str, sun: str) -> dict[str, Any]:
    items = _all_items(reports)
    company_counter: Counter[str] = Counter()
    company_days: dict[str, set] = {}
    for it in items:
        for c in it["companies"]:
            company_counter[c] += 1
            company_days.setdefault(c, set()).add(it["date"])

    top_companies = [
        {"company": c, "mentions": n, "days": len(company_days[c])}
        for c, n in company_counter.most_common(10)
    ]

    def _by_section(sid: str) -> list[dict[str, Any]]:
        return _dedup_titles([it for it in items if it["section_id"] == sid])

    headlines = _dedup_titles([it for it in items if it["section_id"] == "top_news"])
    funding = _by_section("funding")[:10]
    models = _by_section("model_tech")
    policy = _by_section("policy")
    research = _by_section("research")

    timeline = sorted(
        headlines + [m for m in models],
        key=lambda x: x["date"],
    )

    return {
        "week_start": mon,
        "week_end": sun,
        "days": sorted(d for d, _ in reports),
        "report_count": len(reports),
        "total_items": len(items),
        "top_companies": top_companies,
        "headlines": headlines[:12],
        "funding": funding,
        "model_releases": models[:10],
        "policy": policy[:8],
        "research": research[:6],
        "timeline": timeline[:14],
    }


# ── Markdown 渲染 ─────────────────────────────────────

def render_weekly_markdown(agg: dict[str, Any]) -> str:
    L: list[str] = []
    L.append(f"# AI 行业周报 · {agg['week_start']} ~ {agg['week_end']}")
    L.append("")
    L.append(f"> 覆盖 {agg['report_count']} 个日报日 ｜ 合计 {agg['total_items']} 条事件")
    L.append("")
    L.append("## 🏢 本周公司活跃度 TOP 10")
    L.append("")
    for i, c in enumerate(agg["top_companies"], 1):
        L.append(f"{i}. **{c['company']}** — {c['mentions']} 次提及（{c['days']} 天活跃）")
    L.append("")
    L.append("## 💰 本周 TOP 融资")
    L.append("")
    for it in agg["funding"]:
        kd = " ｜ ".join(f"{k['label']}:{k['value']}" for k in it["key_data"])
        L.append(f"- [{it['date']}] {it['title']}" + (f"（{kd}）" if kd else ""))
    L.append("")
    L.append("## 🚀 模型发布与技术节奏")
    L.append("")
    for it in agg["model_releases"]:
        L.append(f"- [{it['date']}] {it['title']}")
    L.append("")
    L.append("## ⚖️ 政策与监管大事记")
    L.append("")
    for it in agg["policy"]:
        L.append(f"- [{it['date']}] {it['title']}")
    L.append("")
    L.append("## 🧪 研究突破")
    L.append("")
    for it in agg["research"]:
        L.append(f"- [{it['date']}] {it['title']}")
    L.append("")
    L.append("## 🗓️ 本周头条时间轴")
    L.append("")
    for it in agg["timeline"]:
        L.append(f"- **{it['date']}** {it['title']}")
    L.append("")
    return "\n".join(L)


# ── HTML 渲染（自包含，邮件/浏览器均可打开） ───────────

def render_weekly_html(agg: dict[str, Any]) -> str:
    e = html.escape
    parts = [
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>",
        f"<title>AI 行业周报 {e(agg['week_start'])}</title>",
        "<style>body{font-family:-apple-system,'PingFang SC',Arial,sans-serif;max-width:820px;margin:0 auto;padding:24px;color:#1a202c;line-height:1.7}"
        "h1{border-bottom:3px solid #2b6cb0;padding-bottom:8px}h2{color:#2b6cb0;margin-top:28px}"
        ".meta{color:#718096}.rank{font-weight:700;color:#2b6cb0}li{margin:6px 0}.tag{color:#c05621;font-size:.9em}"
        "</style></head><body>",
        f"<h1>AI 行业周报</h1><p class='meta'>{e(agg['week_start'])} ~ {e(agg['week_end'])} ｜ "
        f"覆盖 {agg['report_count']} 日 ｜ 合计 {agg['total_items']} 条事件</p>",
    ]

    def list_section(title: str, items: list[dict[str, Any]], with_kd: bool = False):
        parts.append(f"<h2>{e(title)}</h2><ul>")
        for it in items:
            kd = ""
            if with_kd and it["key_data"]:
                kd = "<span class='tag'>（" + e(" ｜ ".join(f"{k['label']}:{k['value']}" for k in it["key_data"])) + "）</span>"
            parts.append(f"<li><span class='tag'>[{e(it['date'])}]</span> {e(it['title'])}{kd}</li>")
        parts.append("</ul>")

    parts.append("<h2>🏢 本周公司活跃度 TOP 10</h2><ol>")
    for c in agg["top_companies"]:
        parts.append(f"<li><span class='rank'>{e(c['company'])}</span> — {c['mentions']} 次提及（{c['days']} 天活跃）</li>")
    parts.append("</ol>")
    list_section("💰 本周 TOP 融资", agg["funding"], with_kd=True)
    list_section("🚀 模型发布与技术节奏", agg["model_releases"])
    list_section("⚖️ 政策与监管大事记", agg["policy"])
    list_section("🧪 研究突破", agg["research"])
    list_section("🗓️ 本周头条时间轴", agg["timeline"])
    parts.append("</body></html>")
    return "\n".join(parts)


def build_weekly(
    anchor: str | date | None = None,
    store: ReportStore | None = None,
    output_root: str | Path = "data/reports/weekly",
) -> dict[str, Any]:
    """生成周报，返回产物路径与聚合摘要。"""
    anchor = anchor or report_now().date().isoformat()
    store = store or ReportStore()
    reports, mon, sun = load_week_reports(store, anchor)
    if not reports:
        return {"ok": False, "reason": f"{mon} ~ {sun} 区间内无日报数据", "week_start": mon, "week_end": sun}

    agg = aggregate_weekly(reports, mon, sun)
    out_dir = Path(output_root) / mon
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"周报_{mon}_to_{sun}"
    md_path = out_dir / f"{base}.md"
    html_path = out_dir / f"{base}.html"
    md_path.write_text(render_weekly_markdown(agg), encoding="utf-8")
    html_path.write_text(render_weekly_html(agg), encoding="utf-8")

    pdf_path: Optional[Path] = None
    pdf_error: Optional[str] = None
    try:
        from app.utils.fallback import playwright_available
        if playwright_available():
            import asyncio
            from app.report.renderer import PDFRenderer
            renderer = PDFRenderer()
            # 周报 HTML 已是自包含页面，直接用 playwright 打印为 PDF
            from playwright.async_api import async_playwright
            async def _to_pdf():
                async with async_playwright() as p:
                    browser = await p.chromium.launch()
                    page = await browser.new_page()
                    await page.goto(f"file://{html_path.resolve()}")
                    await page.wait_for_load_state("networkidle")
                    target = out_dir / f"{base}.pdf"
                    await page.pdf(path=str(target), format="A4", print_background=True,
                                   margin={"top": "18mm", "bottom": "20mm", "left": "16mm", "right": "16mm"})
                    await browser.close()
                    return target
            pdf_path = asyncio.run(_to_pdf())
        else:
            pdf_error = "playwright 不可用，已生成 Markdown + HTML（安装 playwright 可额外出 PDF）"
    except Exception as e:  # noqa: BLE001
        pdf_error = f"PDF 生成失败: {type(e).__name__}: {e}"

    return {
        "ok": True, "week_start": mon, "week_end": sun,
        "report_count": agg["report_count"], "total_items": agg["total_items"],
        "markdown": md_path, "html": html_path, "pdf": pdf_path, "pdf_error": pdf_error,
        "top_companies": agg["top_companies"][:5],
    }
