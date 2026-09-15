"""
优雅降级（建议 #12 · T-D12）
=================================================
两条降级路径：

1. **LLM 降级** —— LLM 不可用 / 额度耗尽时，:func:`build_template_report`
   直接从聚类事件 + 文章快照确定性拼出一份日报（标题/摘要/来源齐全），
   保证「能出报」，并在 ``quality_flags`` 明确标记为模板降级版。
2. **PDF 降级** —— playwright 缺失或渲染失败时，:func:`render_outputs_with_fallback`
   自动退到 HTML + Markdown，终端提示安装命令，用户仍有可读产物。

所有函数均不依赖网络，可离线单测。
"""

from __future__ import annotations

import contextlib
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.schemas.models import (
    Category,
    CATEGORY_NAMES,
    CATEGORY_ORDER,
    DailyReport,
    NewsEvent,
    RawNewsArticle,
    ReportItem,
    ReportSection,
    ReportSource,
)
from app.utils.timeutil import report_day_start, report_now

FALLBACK_FLAG = "LLM 不可用：本报告为模板降级版（标题/摘要来自原始文章，未经编辑加工）"

_PW_CACHE: bool | None = None

# EventType → 栏目 的确定性映射（LLM 缺席时用于归类）
_EVENT_TYPE_TO_CATEGORY: dict[str, Category] = {
    "model_release": Category.MODEL_TECH,
    "model_update": Category.MODEL_TECH,
    "api_launch": Category.MODEL_TECH,
    "chip_hardware": Category.INDUSTRY,
    "datacenter_infra": Category.INDUSTRY,
    "funding_round": Category.FUNDING,
    "acquisition": Category.FUNDING,
    "partnership": Category.INDUSTRY,
    "policy_change": Category.POLICY,
    "regulation_update": Category.POLICY,
    "research_breakthrough": Category.RESEARCH,
    "product_launch": Category.INDUSTRY,
    "company_strategy": Category.INDUSTRY,
    "lawsuit_legal": Category.POLICY,
    "market_data": Category.US_STOCKS,
    "safety_security": Category.POLICY,
}


def playwright_available() -> bool:
    """
    探测 playwright 与 chromium 是否可用（不启动浏览器）。

    sync_playwright 不能在已运行 asyncio 事件循环的线程里启动
    （run_daily 的 do_pdf 是 async），否则抛
    "Sync API inside the asyncio loop"。这里放到独立线程探测，
    从同步/异步两种调用方都安全。
    """
    global _PW_CACHE
    if _PW_CACHE is not None:
        return _PW_CACHE
    try:
        import playwright  # noqa: F401
    except Exception:
        _PW_CACHE = False
        return False

    def _probe() -> bool:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                return Path(p.chromium.executable_path).exists()
        except Exception:
            return False

    import concurrent.futures
    try:
        # 探测会启动 playwright 驱动子进程，其退出时在 py3.14 会打印
        # 无害的 "Task was destroyed" 噪声；静默 stderr，只取布尔结果。
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                result = bool(ex.submit(_probe).result(timeout=60))
        _PW_CACHE = result
        return result
    except Exception:
        _PW_CACHE = False
        return False


def event_category(event: NewsEvent) -> Category:
    """根据事件类型猜测归类（兜底 industry）。"""
    et = event.event_type_guess
    if et is not None:
        cat = _EVENT_TYPE_TO_CATEGORY.get(getattr(et, "value", str(et)))
        if cat is not None:
            return cat
    return Category.INDUSTRY


def _build_sources(event: NewsEvent, article_map: dict[str, RawNewsArticle]) -> list[ReportSource]:
    sources: list[ReportSource] = []
    seen: set[str] = set()
    for aid in event.article_ids[:5]:
        art = article_map.get(aid)
        if art is None:
            continue
        domain = art.source_domain or ""
        if domain in seen:
            continue
        seen.add(domain)
        try:
            sources.append(ReportSource(
                name=art.source_name or domain,
                url=str(art.url),
                is_official=False,
            ))
        except Exception:
            continue
    return sources


def _details_from_articles(event: NewsEvent, article_map: dict[str, RawNewsArticle], max_len: int = 600) -> str:
    """用关联文章的快照拼出降级版详情。"""
    snippets: list[str] = []
    for aid in event.article_ids[:3]:
        art = article_map.get(aid)
        if art is None:
            continue
        text = (art.content or art.snippet or "").strip()
        if text:
            snippets.append(text)
    joined = " ".join(snippets)
    if len(joined) > max_len:
        joined = joined[:max_len].rstrip() + "……"
    return joined or "（原始文章摘要缺失）"


def _event_to_item(event: NewsEvent, article_map: dict[str, RawNewsArticle], rank: int,
                   category: Category) -> ReportItem:
    sources = _build_sources(event, article_map)
    details = _details_from_articles(event, article_map)
    title = event.canonical_title.strip()
    return ReportItem(
        item_id=ReportItem.make_id(rank),
        event_id=event.event_id,
        rank=rank,
        category=category,
        title=title,
        key_data=[],
        details=details,
        analysis=None,
        sources=sources,
        word_count=len(title) + len(details),
    )


def build_template_report(
    events: list[NewsEvent],
    article_map: dict[str, RawNewsArticle],
    report_date: str | None = None,
    top_n: int = 6,
    per_section: int = 8,
) -> DailyReport:
    """
    LLM 降级：零 LLM 调用，确定性生成日报。

    重要性以 ``article_count``（多源印证度）代理；今日头条取报道源最多的事件，
    其余按栏目归类，已入选头条的事件不在子栏目重复。
    """
    report_date = report_date or report_now().strftime("%Y-%m-%d")
    ranked = sorted(events, key=lambda e: (e.article_count, len(e.source_domains)), reverse=True)

    top_events = ranked[:top_n]
    top_ids = {e.event_id for e in top_events}

    sections: list[ReportSection] = []
    top_items = [_event_to_item(e, article_map, i, Category.TOP_NEWS) for i, e in enumerate(top_events, 1)]
    sections.append(ReportSection(
        section_id=Category.TOP_NEWS,
        section_name=CATEGORY_NAMES[Category.TOP_NEWS],
        item_count=len(top_items),
        items=top_items,
    ))

    for cat in CATEGORY_ORDER[1:]:
        members = [e for e in ranked if e.event_id not in top_ids and event_category(e) == cat][:per_section]
        items = [_event_to_item(e, article_map, i, cat) for i, e in enumerate(members, 1)]
        sections.append(ReportSection(
            section_id=cat,
            section_name=CATEGORY_NAMES[cat],
            item_count=len(items),
            items=items,
        ))

    total_items = sum(s.item_count for s in sections)
    total_words = sum(it.word_count for s in sections for it in s.items)
    return DailyReport(
        report_id=f"daily_{report_date.replace('-', '')}",
        report_date=report_date,
        time_window_start=report_day_start(report_date),
        time_window_end=report_now(),
        total_items=total_items,
        total_word_count=total_words,
        editor_summary=None,
        sections=sections,
        quality_flags=[FALLBACK_FLAG],
        generated_at=datetime.now(timezone.utc),
    )


def render_outputs_with_fallback(report: DailyReport, renderer: Any | None = None) -> dict[str, Any]:
    """
    PDF 降级：优先 playwright 出 PDF；失败/缺失则退到 HTML + Markdown。

    返回::

        {"pdf": Path|None, "html": Path|None, "markdown": Path|None,
         "degraded": bool, "flags": [str, ...]}
    """
    from app.report.renderer import PDFRenderer
    from app.exporter.markdown import report_to_markdown

    renderer = renderer or PDFRenderer()
    flags: list[str] = []
    pdf_path: Optional[Path] = None
    html_path: Optional[Path] = None
    md_path: Optional[Path] = None

    # HTML 总是先存（调试 + 降级兜底）
    try:
        html_path = renderer.save_html(report)
    except Exception as e:  # noqa: BLE001
        flags.append(f"HTML 渲染失败: {type(e).__name__}: {e}")

    if playwright_available():
        try:
            import asyncio
            pdf_path = asyncio.run(renderer.render_pdf(report))
        except Exception as e:  # noqa: BLE001
            flags.append(f"PDF 渲染失败，降级到 HTML/Markdown: {type(e).__name__}: {e}")
            pdf_path = None
    else:
        flags.append("playwright/chromium 不可用：已降级为 HTML + Markdown（pip install playwright && playwright install chromium）")

    # Markdown 兜底（无论是否出 PDF 都生成，便于二次消费）
    try:
        out_dir = renderer._ensure_output_dir(report.report_date)
        md_path = out_dir / f"report_{report.report_date}.md"
        md_path.write_text(report_to_markdown(report), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        flags.append(f"Markdown 导出失败: {type(e).__name__}: {e}")

    degraded = pdf_path is None
    return {"pdf": pdf_path, "html": html_path, "markdown": md_path, "degraded": degraded, "flags": flags}
