"""
日报在线阅读视图渲染（T13-A）
=================================================
把 ``daily_{date}.json``（``ReportStore.load_raw`` 的 dict）渲染成可在浏览器
直接阅读的中文 HTML 片段：导读 → 栏目 → 条目（关键数据 / 正文 / 编辑点评 / 来源）。

纯函数、不触碰 socket 与文件系统，因此 ``tests/test_web.py`` 可直接断言输出。
所有进入 HTML 的文本一律先经 ``html.escape``，再做关键词高亮，防注入。
"""

from __future__ import annotations

import html
import re
from typing import Any, Iterable

# 栏目主题色（左侧色条 / 标签）
SECTION_ACCENT = {
    "top_news": "#c53030",
    "model_tech": "#2b6cb0",
    "funding": "#2f855a",
    "policy": "#b7791f",
    "research": "#6b46c1",
    "industry": "#2c7a7b",
    "us_stocks": "#9c4221",
}


def esc(text: Any) -> str:
    return html.escape("" if text is None else str(text))


def highlight(text: Any, query: str) -> str:
    """先转义再高亮命中关键词（多词 OR，中文按子串）。"""
    safe = esc(text)
    q = (query or "").strip()
    if not q:
        return safe
    tokens = [t for t in re.split(r"\s+", q) if t]
    for tok in tokens:
        etok = html.escape(tok)
        if not etok:
            continue
        safe = re.sub(
            f"({re.escape(etok)})",
            r"<mark>\1</mark>",
            safe,
            flags=re.IGNORECASE,
        )
    return safe


def _paragraphs(text: str) -> list[str]:
    """把正文按换行/中文分号句切成段落，避免一大坨文字。"""
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    return parts or [text.strip()]


def _render_key_data(key_data: Iterable[dict]) -> str:
    rows = [kd for kd in (key_data or []) if isinstance(kd, dict) and kd.get("label")]
    if not rows:
        return ""
    chips = "".join(
        f'<div class="kd"><span class="kd-l">{esc(kd.get("label"))}</span>'
        f'<span class="kd-v">{esc(kd.get("value"))}</span></div>'
        for kd in rows
    )
    return f'<div class="kd-grid">{chips}</div>'


def _render_sources(sources: Iterable[dict]) -> str:
    srcs = [s for s in (sources or []) if isinstance(s, dict)]
    if not srcs:
        return ""
    links = []
    for s in srcs:
        name = esc(s.get("name") or s.get("url") or "来源")
        url = s.get("url")
        if url:
            links.append(f'<a href="{esc(url)}" target="_blank" rel="noopener">🔗 {name}</a>')
        else:
            links.append(f"<span>🔗 {name}</span>")
    return '<div class="src">' + " ".join(links) + "</div>"


def render_item(item: dict, query: str = "") -> str:
    title = highlight(item.get("title"), query)
    rank = item.get("rank", "·")
    cat = item.get("category", "")
    accent = SECTION_ACCENT.get(cat, "#4a5568")
    b = [f'<article class="news" style="border-left-color:{accent}">']
    b.append(f'<h4><span class="rank">{esc(rank)}</span> {title}</h4>')
    b.append(_render_key_data(item.get("key_data")))
    for para in _paragraphs(item.get("details") or ""):
        b.append(f"<p>{highlight(para, query)}</p>")
    if item.get("analysis"):
        b.append(f'<aside class="ana"><strong>✍️ 编辑点评</strong>：{highlight(item["analysis"], query)}</aside>')
    b.append(_render_sources(item.get("sources")))
    wc = item.get("word_count")
    if wc:
        b.append(f'<div class="muted wc">约 {esc(wc)} 字</div>')
    b.append("</article>")
    return "".join(b)


def render_reading_view(raw: dict, date: str, *, banner: str = "", query: str = "") -> str:
    """渲染整期日报为阅读 HTML 片段（不含站点布局）。"""
    b: list[str] = []
    if banner:
        b.append(f'<div class="banner">{esc(banner)}</div>')
    summary = raw.get("editor_summary")
    if summary:
        b.append(f'<div class="card read-card"><h2>📌 今日导读</h2><p class="summary">{highlight(summary, query)}</p></div>')

    flags = [f for f in (raw.get("quality_flags") or []) if f]
    if flags:
        items = "".join(f"<li>{esc(f)}</li>" for f in flags)
        b.append(f'<details class="card flags"><summary>🚩 质量标记（{len(flags)}）</summary><ul>{items}</ul></details>')

    any_item = False
    for sec in raw.get("sections", []):
        items = sec.get("items") or []
        if not items:
            continue
        any_item = True
        sid = sec.get("section_id") or ""
        accent = SECTION_ACCENT.get(sid, "#4a5568")
        b.append('<div class="card read-card">')
        b.append(
            f'<h2 class="sec-title" style="border-left-color:{accent}">'
            f"{esc(sec.get('section_name', ''))} "
            f'<span class="muted">（{len(items)}）</span></h2>'
        )
        for it in items:
            b.append(render_item(it, query=query))
        b.append("</div>")

    if not any_item:
        b.append('<div class="card"><h2>暂无条目</h2><p class="muted">本期没有可展示的新闻条目。</p></div>')

    meta = (
        f'<p class="muted meta">📅 {esc(date)} ｜ 条目 {raw.get("total_items", "-")} '
        f'｜ 字数 {raw.get("total_word_count", "-")} ｜ report_id {esc(raw.get("report_id", ""))}</p>'
    )
    return meta + "".join(b)
