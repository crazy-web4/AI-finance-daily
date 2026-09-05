"""
跨期对比与趋势（建议 #8 · T-C8）
=================================================
基于 SQLite 索引做聚合：
- ``trend funding --weeks N``   近 N 周融资热点公司
- ``trend headlines --diff``    本周 vs 上周头条差异（新增/保留/下榜）
- ``trend topics --weeks N``    近 N 周话题（栏目）热度序列
"""

from __future__ import annotations

import re
import sqlite3
from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Any

from app.storage.db import DEFAULT_DB_PATH, connect
from app.storage.entities import extract_companies

_MONEY = re.compile(
    r"(?:约|近|超)?\s?\$?\s?([\d,\.]+)\s?(万亿|亿|十亿|百亿|亿万美元|亿美元|亿人民币|b|m|bn|million|billion)",
    re.IGNORECASE,
)


def _week_start(date_str: str) -> str:
    """该日期所在周的周一（ISO），返回 YYYY-MM-DD。"""
    d = date.fromisoformat(date_str)
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat()


def _recent_weeks_dates(conn: sqlite3.Connection, weeks: int) -> list[str]:
    rows = conn.execute("SELECT DISTINCT date FROM items ORDER BY date").fetchall()
    dates = [r["date"] for r in rows]
    if not dates:
        return []
    latest = date.fromisoformat(dates[-1])
    cutoff = (latest - timedelta(weeks=weeks)).isoformat()
    return [d for d in dates if d >= cutoff]


def funding_hotspots(conn: sqlite3.Connection, weeks: int = 4, top: int = 10) -> list[dict[str, Any]]:
    """近 N 周融资栏目中公司出现频次（best-effort 汇总提及金额）。"""
    dates = set(_recent_weeks_dates(conn, weeks))
    if not dates:
        return []
    ph = ",".join("?" * len(dates))
    rows = conn.execute(
        f"SELECT title, details, date FROM items WHERE section_id='funding' AND date IN ({ph})",
        tuple(dates),
    ).fetchall()
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        text = f"{r['title']} {r['details'] or ''}"
        for company in extract_companies(text):
            a = agg.setdefault(company, {"company": company, "count": 0, "dates": set(), "amounts": []})
            a["count"] += 1
            a["dates"].add(r["date"])
            a["amounts"].extend(_extract_amounts(r["title"]))
    out = []
    for a in agg.values():
        out.append({
            "company": a["company"],
            "count": a["count"],
            "days": len(a["dates"]),
            "amounts": a["amounts"],
        })
    out.sort(key=lambda x: (x["count"], x["days"]), reverse=True)
    return out[:top]


def _extract_amounts(text: str) -> list[float]:
    """从标题抽取金额，统一换算成「亿美元」（best-effort，仅用于量级参考）。"""
    amounts: list[float] = []
    for m in _MONEY.finditer(text or ""):
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = m.group(2).lower()
        if "万亿" in unit:
            val *= 10000
        elif "百亿" in unit:
            val *= 100
        elif "十亿" in unit:
            val *= 10
        elif "亿" in unit:
            pass  # 已是亿
        elif unit in ("b", "bn", "billion"):
            val *= 10  # 10 亿美元 ≈ 1B
        elif unit in ("m", "million"):
            val *= 0.1
        amounts.append(val)
    return amounts


def _headline_identity(title: str) -> tuple[frozenset, frozenset]:
    """用公司集合 + 标题关键词集合表征一条头条，供跨期比对。"""
    companies = frozenset(extract_companies(title))
    tokens = frozenset(re.findall(r"[A-Za-z0-9\.]+|[\u4e00-\u9fff]{2,}", title))
    return companies, tokens


def _similar(a: tuple[frozenset, frozenset], b: tuple[frozenset, frozenset]) -> bool:
    ca, ta = a
    cb, tb = b
    overlap = len(ta & tb)
    union = len(ta | tb)
    if union == 0:
        return False
    jaccard = overlap / union
    # 同一事件跨天标题高度相似（流水线已做跨天去重，保留下来的多为持续热点）；
    # 仅公司相同但标题不同（如 OpenAI 的两件事）不算「持续」。
    if jaccard >= 0.5:
        return True
    if ca and cb and (ca & cb) and jaccard >= 0.25:
        return True
    return False


def headline_diff(conn: sqlite3.Connection, anchor: str | None = None) -> dict[str, Any]:
    """
    本周 vs 上周今日头条差异。

    返回 ``{"this_week": [...], "added": [...], "kept": [...], "dropped": [...]}``。
    """
    rows = conn.execute(
        "SELECT title, date, importance FROM items WHERE section_id='top_news' ORDER BY date DESC, rank"
    ).fetchall()
    if not rows:
        return {"this_week": [], "added": [], "kept": [], "dropped": []}
    anchor_date = anchor or rows[0]["date"]
    this_ws = _week_start(anchor_date)
    last_ws = (date.fromisoformat(this_ws) - timedelta(weeks=1)).isoformat()

    this = [dict(r) for r in rows if _week_start(r["date"]) == this_ws]
    last = [dict(r) for r in rows if _week_start(r["date"]) == last_ws]

    this_id = {r["title"]: _headline_identity(r["title"]) for r in this}
    last_id = {r["title"]: _headline_identity(r["title"]) for r in last}

    kept_titles, added = set(), []
    for r in this:
        ident = this_id[r["title"]]
        if any(_similar(ident, lid) for lid in last_id.values()):
            kept_titles.add(r["title"])
        else:
            added.append(r)
    dropped = [r for r in last if not any(_similar(last_id[r["title"]], tid) for tid in this_id.values())]
    return {
        "this_week": this,
        "added": added,
        "kept": [r for r in this if r["title"] in kept_titles],
        "dropped": dropped,
        "week_start": this_ws,
        "last_week_start": last_ws,
    }


def topic_heat(conn: sqlite3.Connection, weeks: int = 12) -> "OrderedDict[str, dict[str, Any]]":
    """近 N 周各栏目（话题）条目数时间序列。"""
    dates = _recent_weeks_dates(conn, weeks)
    if not dates:
        return OrderedDict()
    ph = ",".join("?" * len(dates))
    rows = conn.execute(
        f"SELECT date, section_name, COUNT(*) n FROM items WHERE date IN ({ph}) GROUP BY date, section_name",
        tuple(dates),
    ).fetchall()
    weeks_buckets: "OrderedDict[str, dict[str, int]]" = OrderedDict()
    names: set[str] = set()
    for r in rows:
        ws = _week_start(r["date"])
        bucket = weeks_buckets.setdefault(ws, {})
        bucket[r["section_name"]] = bucket.get(r["section_name"], 0) + r["n"]
        names.add(r["section_name"])
    return OrderedDict(
        (ws, {"week_start": ws, "topics": {name: weeks_buckets[ws].get(name, 0) for name in sorted(names)}})
        for ws in sorted(weeks_buckets)
    )


# ── CLI 格式化 ────────────────────────────────────────

def format_funding(rows: list[dict[str, Any]], weeks: int) -> str:
    if not rows:
        return f"近 {weeks} 周暂无融资栏目数据。"
    lines = [f"近 {weeks} 周融资热点公司 TOP {len(rows)}:"]
    for i, r in enumerate(rows, 1):
        amounts = r.get("amounts") or []
        amt = f" · 提及金额约 {sum(amounts):.0f} 亿美元级" if amounts else ""
        lines.append(f"  {i:2d}. {r['company']:20s} {r['count']} 次（{r['days']} 天活跃）{amt}")
    return "\n".join(lines)


def format_headline_diff(d: dict[str, Any]) -> str:
    if not d.get("this_week"):
        return "暂无今日头条数据。"
    lines = [f"本周（{d['week_start']} 起）vs 上周（{d['last_week_start']} 起）头条差异:", ""]
    lines.append(f"🆕 本周新增头条（{len(d['added'])}）:")
    for r in d["added"]:
        lines.append(f"  + [{r['date']}] {r['title'][:50]}（{r['importance']}分）")
    lines.append("")
    lines.append(f"🔁 两周持续（{len(d['kept'])}）:")
    for r in d["kept"]:
        lines.append(f"  = [{r['date']}] {r['title'][:50]}")
    lines.append("")
    lines.append(f"📉 上周头条下榜（{len(d['dropped'])}）:")
    for r in d["dropped"]:
        lines.append(f"  - [{r['date']}] {r['title'][:50]}")
    return "\n".join(lines)


def format_topics(heat: "OrderedDict[str, dict[str, Any]]", weeks: int) -> str:
    if not heat:
        return "暂无话题热度数据。"
    topics = list(next(iter(heat.values()))["topics"].keys())
    lines = [f"近 {weeks} 周话题（栏目）热度:", ""]
    header = "周起始      " + "".join(f"{t[:6]:>8s}" for t in topics)
    lines.append(header)
    for ws, payload in heat.items():
        row = ws + "  " + "".join(f"{payload['topics'][t]:8d}" for t in topics)
        lines.append(row)
    return "\n".join(lines)
