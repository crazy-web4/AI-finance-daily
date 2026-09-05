"""
本地 RSS / Atom Feed（建议 #6 · T-B6）
=================================================
扫描 data/reports 生成 RSS 2.0 + Atom 1.0，每期日报为一个 item：
标题取头条 1~3 条、描述为导读 + 条目列表、链接指向本地/HTTP 产物。

不引入第三方依赖，xml.etree 保证 well-formed。
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from email.utils import formatdate
from xml.etree import ElementTree as ET

from app.storage.report_store import ReportStore

FEED_TITLE = "AI 行业全球动态日报"
FEED_DESC = "每日 AI 模型 · 资本 · 政策 · 科研 · 产业动态"


def _item_payload(store: ReportStore, date: str) -> dict:
    raw = store.load_raw(date) or {}
    sections = raw.get("sections", [])
    top_titles: list[str] = []
    for sec in sections:
        if sec.get("section_id") == "top_news":
            top_titles = [it.get("title", "") for it in sec.get("items", [])[:3]]
            break
    summary = raw.get("editor_summary") or ""
    all_titles = [it.get("title", "") for sec in sections for it in sec.get("items", [])]
    gen = raw.get("generated_at") or date
    return {
        "date": date,
        "report_id": raw.get("report_id", f"daily_{date}"),
        "total_items": raw.get("total_items", len(all_titles)),
        "top_titles": top_titles,
        "summary": summary,
        "all_titles": all_titles,
        "generated_at": gen,
    }


def _description(p: dict) -> str:
    parts: list[str] = []
    if p["summary"]:
        parts.append(f"<p>{html.escape(p['summary'])}</p>")
    parts.append("<ul>")
    for t in p["all_titles"][:12]:
        parts.append(f"<li>{html.escape(t)}</li>")
    parts.append("</ul>")
    return "".join(parts)


def _title(p: dict) -> str:
    head = p["top_titles"][0] if p["top_titles"] else "今日日报"
    return f"{p['date']} 日报：{head}"


def _to_rfc822(date_str: str) -> str:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return formatdate(dt.timestamp())
    except Exception:
        return formatdate(float(datetime.fromisoformat(date_str + "T00:00:00+08:00").timestamp()))


def collect_items(store: ReportStore, limit: int = 30) -> list[dict]:
    dates = store.report_dates()[-limit:]
    out = []
    for date in reversed(dates):  # 最新在前
        p = _item_payload(store, date)
        p["link"] = f"/report/{date}"
        out.append(p)
    return out


def build_rss(store: ReportStore, base_url: str = "", limit: int = 30) -> str:
    items = collect_items(store, limit)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "description").text = FEED_DESC
    ET.SubElement(channel, "link").text = base_url or "http://127.0.0.1:8910/"
    for p in items:
        it = ET.SubElement(channel, "item")
        ET.SubElement(it, "title").text = _title(p)
        ET.SubElement(it, "link").text = (base_url.rstrip("/") + p["link"]) if base_url else p["link"]
        ET.SubElement(it, "guid", {"isPermaLink": "false"}).text = p["report_id"]
        ET.SubElement(it, "pubDate").text = _to_rfc822(p["generated_at"])
        ET.SubElement(it, "description").text = _description(p)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode")


def build_atom(store: ReportStore, base_url: str = "", limit: int = 30) -> str:
    ns = "http://www.w3.org/2005/Atom"
    items = collect_items(store, limit)
    feed = ET.Element(f"{{{ns}}}feed", {"xml:lang": "zh-CN"})
    ET.SubElement(feed, f"{{{ns}}}title").text = FEED_TITLE
    ET.SubElement(feed, f"{{{ns}}}subtitle").text = FEED_DESC
    ET.SubElement(feed, f"{{{ns}}}id").text = base_url or "urn:ai-daily:feed"
    ET.SubElement(feed, f"{{{ns}}}updated").text = datetime.now(timezone.utc).isoformat()
    for p in items:
        entry = ET.SubElement(feed, f"{{{ns}}}entry")
        ET.SubElement(entry, f"{{{ns}}}title").text = _title(p)
        link = (base_url.rstrip("/") + p["link"]) if base_url else p["link"]
        ET.SubElement(entry, f"{{{ns}}}link", {"href": link})
        ET.SubElement(entry, f"{{{ns}}}id").text = f"urn:ai-daily:{p['report_id']}"
        ET.SubElement(entry, f"{{{ns}}}updated").text = _to_iso(p["generated_at"])
        ET.SubElement(entry, f"{{{ns}}}summary", {"type": "html"}).text = _description(p)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(feed, encoding="unicode")


def _to_iso(date_str: str) -> str:
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).isoformat()
    except Exception:
        return date_str
