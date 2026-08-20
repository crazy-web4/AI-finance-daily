"""
跨天事件记忆（架构评审 #8）
职责: 读取近 N 天的历史事件索引（data/events/{date}/events_*.json），
     从今日事件中过滤"前几天已报道"的旧事件，避免日报连续多天重复同一新闻。

说明: 同一天内的重复运行不去重（exclude_date=今天），保证重跑不丢内容。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from app.pipeline.cluster import _jaccard, _title_bigrams

EVENTS_DIR = Path("data/events")


def load_recent_event_titles(
    days: int = 3,
    exclude_date: str | None = None,
    events_dir: str | Path = EVENTS_DIR,
) -> list[tuple[str, str]]:
    """
    加载近 days 天（不含 exclude_date，通常为今天）的历史事件标题。

    Returns:
        [(date, canonical_title), ...]
    """
    base = Path(events_dir)
    if not base.exists():
        return []

    exclude_date = exclude_date or datetime.now().strftime("%Y-%m-%d")
    window_start = datetime.now() - timedelta(days=days)

    titles: list[tuple[str, str]] = []
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue  # 跳过旧版平铺文件，只认 {date}/ 目录
        try:
            dt = datetime.strptime(d.name, "%Y-%m-%d")
        except ValueError:
            continue
        if d.name == exclude_date or dt < window_start:
            continue
        for f in sorted(d.glob("events_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for e in data:
                t = (e or {}).get("canonical_title") or ""
                if t:
                    titles.append((d.name, t))
    return titles


def filter_seen_events(
    events,
    recent_titles: list[tuple[str, str]],
    threshold: float = 0.7,
) -> tuple[list, list]:
    """
    过滤近几天已报道的事件。

    阈值说明: 同天聚类用 0.6，跨天去重略严取 0.7——
    相同/同义改写标题(≈0.75+)会被过滤，真正不同的事件(通常<0.5)不受影响。

    Returns:
        (fresh_events, seen_list)
        seen_list: [(event, (date, past_title, similarity)), ...]
    """
    past = [(d, t, _title_bigrams(t)) for d, t in recent_titles]
    fresh: list = []
    seen: list = []

    for e in events:
        bg = _title_bigrams(e.canonical_title)
        hit = None
        if bg:
            for d, t, pb in past:
                if not pb:
                    continue
                sim = _jaccard(bg, pb)
                if sim >= threshold:
                    hit = (d, t, sim)
                    break
        if hit:
            seen.append((e, hit))
        else:
            fresh.append(e)

    return fresh, seen
