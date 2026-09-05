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


def render_item(item: dict, query: str = "", detail_prefix: str = "") -> str:
    title = highlight(item.get("title"), query)
    rank = item.get("rank", "·")
    cat = item.get("category", "")
    accent = SECTION_ACCENT.get(cat, "#4a5568")
    item_id = item.get("item_id") or f"item-{rank}"
    b = [f'<article class="news" id="{esc(item_id)}" style="border-left-color:{accent}">']
    b.append(f'<h4><span class="rank">{esc(rank)}</span> {title}</h4>')
    b.append(_render_key_data(item.get("key_data")))
    for para in _paragraphs(item.get("details") or ""):
        b.append(f"<p>{highlight(para, query)}</p>")
    if item.get("analysis"):
        b.append(f'<aside class="ana"><strong>✍️ 编辑点评</strong>：{highlight(item["analysis"], query)}</aside>')
    b.append(_render_sources(item.get("sources")))
    tools = []
    if detail_prefix:
        tools.append(f'<a class="detail-link" href="{esc(detail_prefix)}{esc(item_id)}">🔎 深度阅读</a>')
    wc = item.get("word_count")
    if wc:
        tools.append(f'<span class="muted wc">约 {esc(wc)} 字</span>')
    if tools:
        b.append('<div class="item-tools">' + " ".join(tools) + "</div>")
    b.append("</article>")
    return "".join(b)


def render_toc(sections: list[dict], date: str) -> str:
    """本期目录：栏目锚点跳转。"""
    items = []
    idx = 0
    for sec in sections:
        sitems = sec.get("items") or []
        if not sitems:
            continue
        sec_anchor = f"sec-{idx}"
        items.append(
            f'<li><a href="#{sec_anchor}">{esc(sec.get("section_name", ""))}'
            f'<span class="muted">（{len(sitems)}）</span></a></li>'
        )
        idx += 1
    if not items:
        return ""
    return ('<div class="card toc"><h2>🧭 本期目录</h2><ul class="toc-list">'
            + "".join(items) + "</ul></div>")


def render_item_detail(item: dict, date: str, related: list[dict] | None = None) -> str:
    """单条深度阅读页片段：完整内容 + 全部来源 + 跨期相关报道。"""
    b = ['<div class="card read-card">']
    b.append(f'<p class="muted">📅 {esc(date)}</p>')
    b.append(f'<h2 class="detail-title">{esc(item.get("title", ""))}</h2>')
    b.append(_render_key_data(item.get("key_data")))
    for para in _paragraphs(item.get("details") or ""):
        b.append(f"<p>{esc(para)}</p>")
    if item.get("analysis"):
        b.append(f'<aside class="ana"><strong>✍️ 编辑点评</strong>：{esc(item["analysis"])}</aside>')
    b.append("</div>")
    # 全部来源
    srcs = [s for s in (item.get("sources") or []) if isinstance(s, dict)]
    if srcs:
        b.append('<div class="card read-card"><h2>🔗 原文来源</h2><ul class="src-list">')
        for s in srcs:
            name = esc(s.get("name") or s.get("url") or "来源")
            url = s.get("url")
            if url:
                b.append(f'<li><a href="{esc(url)}" target="_blank" rel="noopener">{name}</a> <span class="muted">{esc(url)}</span></li>')
            else:
                b.append(f"<li>{name}</li>")
        b.append("</ul></div>")
    # 跨期相关
    rel = [r for r in (related or []) if r.get("date") != date or r.get("title") != item.get("title")]
    if rel:
        b.append('<div class="card read-card"><h2>🔁 相关报道（跨期）</h2><ul>')
        for r in rel[:12]:
            comp = "、".join((r.get("companies") or [])[:3])
            comp_s = f' <span class="muted">[{esc(comp)}]</span>' if comp else ""
            b.append(
                f'<li>[{esc(r["date"])}] {esc(r.get("section_name") or "")} · '
                f'<a href="/read/{esc(r["date"])}">{esc(r.get("title", ""))}</a>{comp_s}</li>')
        b.append("</ul></div>")
    return "".join(b)


def render_company_timeline(name: str, rows: list[dict]) -> str:
    """公司时间线片段。"""
    b = [f'<div class="card"><h2>🏢 {esc(name)} · 全部报道（{len(rows)}）</h2>']
    if not rows:
        b.append('<p class="muted">没有找到相关报道。</p></div>')
        return "".join(b)
    b.append('<table><tr><th>日期</th><th>栏目</th><th>重要度</th><th>标题</th></tr>')
    for r in rows:
        b.append(
            f'<tr><td><a href="/read/{esc(r["date"])}">{esc(r["date"])}</a></td>'
            f'<td>{esc(r.get("section_name") or "")}</td><td>{r.get("importance", "-")}</td>'
            f'<td><a href="/read/{esc(r["date"])}">{esc(r.get("title", ""))}</a></td></tr>')
    b.append("</table></div>")
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
        fl = "".join(f"<li>{esc(f)}</li>" for f in flags)
        b.append(f'<details class="card flags"><summary>🚩 质量标记（{len(flags)}）</summary><ul>{fl}</ul></details>')

    sections = raw.get("sections", [])
    b.append(render_toc(sections, date))
    detail_prefix = f"/item/{date}/"
    any_item = False
    for idx, sec in enumerate(sections):
        sitems = sec.get("items") or []
        if not sitems:
            continue
        any_item = True
        sid = sec.get("section_id") or ""
        accent = SECTION_ACCENT.get(sid, "#4a5568")
        b.append(f'<div class="card read-card" id="sec-{idx}">')
        b.append(
            f'<h2 class="sec-title" style="border-left-color:{accent}">'
            f"{esc(sec.get('section_name', ''))} "
            f'<span class="muted">（{len(sitems)}）</span></h2>'
        )
        for it in sitems:
            b.append(render_item(it, query=query, detail_prefix=detail_prefix))
        b.append("</div>")

    if not any_item:
        b.append('<div class="card"><h2>暂无条目</h2><p class="muted">本期没有可展示的新闻条目。</p></div>')

    meta = (
        f'<p class="muted meta">📅 {esc(date)} ｜ 条目 {raw.get("total_items", "-")} '
        f'｜ 字数 {raw.get("total_word_count", "-")} ｜ report_id {esc(raw.get("report_id", ""))}</p>'
    )
    return meta + "".join(b)
