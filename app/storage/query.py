"""
情报检索（建议 #7 · T-C7）
=================================================
``query "OpenAI" --days 30``  全文检索
``query "融资" --category funding``  按栏目
``stats --since 2026-08-01``  统计分布

中文走 LIKE 兜底召回，拉丁文走 FTS5 MATCH 加权；结果合并去重。
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from app.storage.db import DEFAULT_DB_PATH, connect, stats_overview
from app.utils.timeutil import report_now


def _fts_query(term: str) -> str:
    """把用户输入转成 FTS5 MATCH 表达式（多词 AND，加引号防语法注入）。"""
    tokens = [t for t in term.replace('"', " ").split() if t]
    if not tokens:
        return '""'
    return " ".join(f'"{t}"*' for t in tokens)


def search(
    db_path: str | Path = DEFAULT_DB_PATH,
    keyword: str = "",
    days: int | None = None,
    category: str | None = None,
    importance_min: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        where: list[str] = []
        params: list[Any] = []
        if days is not None:
            cutoff = (report_now() - timedelta(days=days)).date().isoformat()
            where.append("date >= ?")
            params.append(cutoff)
        if category:
            where.append("section_id = ?")
            params.append(category)
        if importance_min is not None:
            where.append("importance >= ?")
            params.append(importance_min)
        base_where = (" WHERE " + " AND ".join(where)) if where else ""

        matched: dict[str, dict[str, Any]] = {}

        # 1) FTS5 MATCH（拉丁文 / 多词）
        if keyword.strip():
            try:
                fts_sql = (
                    "SELECT i.* FROM items_fts f JOIN items i ON i.id = f.rowid "
                    f"{'WHERE' if not where else 'WHERE ' + ' AND '.join(where) + ' AND '} "
                    "items_fts MATCH ? ORDER BY rank LIMIT ?"
                )
                # 重建带 join 条件的语句
                cond = where + ["items_fts MATCH ?"]
                sql = (
                    "SELECT i.* FROM items_fts f JOIN items i ON i.id=f.rowid "
                    "WHERE " + " AND ".join(cond) + " ORDER BY f.rank LIMIT ?"
                )
                rows = conn.execute(sql, (*params, _fts_query(keyword), limit)).fetchall()
                for r in rows:
                    d = dict(r)
                    d["match"] = "fts"
                    matched[d["item_uid"]] = d
            except Exception:
                pass

            # 2) LIKE 兜底（中文子串 / 召回补充）
            like = f"%{keyword.strip()}%"
            like_sql = (
                "SELECT * FROM items " + base_where +
                (" AND " if where else " WHERE ") +
                "(title LIKE ? OR details LIKE ? OR analysis LIKE ?) "
                "ORDER BY date DESC, importance DESC LIMIT ?"
            )
            rows = conn.execute(like_sql, (*params, like, like, like, limit)).fetchall()
            for r in rows:
                d = dict(r)
                if d["item_uid"] not in matched:
                    d["match"] = "like"
                    matched[d["item_uid"]] = d
        else:
            rows = conn.execute(
                f"SELECT * FROM items {base_where} ORDER BY date DESC, importance DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            for r in rows:
                d = dict(r)
                d["match"] = "browse"
                matched[d["item_uid"]] = d

        results = list(matched.values())
        results.sort(key=lambda x: (x["date"], x["importance"]), reverse=True)
        for r in results:
            r["companies"] = json.loads(r.get("companies") or "[]")
            r["sources"] = json.loads(r.get("sources") or "[]")
        return results[:limit]
    finally:
        conn.close()


def stats(db_path: str | Path = DEFAULT_DB_PATH, since: str | None = None) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        return stats_overview(conn, since=since)
    finally:
        conn.close()


def format_results(rows: list[dict[str, Any]], keyword: str = "") -> str:
    if not rows:
        return f"未找到与「{keyword}」相关的条目。"
    lines = [f"共 {len(rows)} 条命中："]
    for r in rows:
        comp = "、".join(r.get("companies", [])[:4])
        comp_str = f" [{comp}]" if comp else ""
        lines.append(
            f"[{r['date']}] {r['section_name']} · {r['importance']}分 · "
            f"「{r['title'][:50]}」{comp_str}"
        )
    return "\n".join(lines)


def format_stats(s: dict[str, Any]) -> str:
    lines = [
        f"期数: {s['reports']} ｜ 总条目: {s['items']}",
        "",
        "栏目分布:",
    ]
    for sec in s["by_section"]:
        lines.append(f"  {sec['section_name']}: {sec['n']} 条")
    lines.append("")
    lines.append("公司/机构 TOP 20（提及次数 / 活跃天数）:")
    for c in s["top_companies"]:
        lines.append(f"  {c['name']:22s} {c['mentions']:3d} 次  {c['days']:2d} 天")
    return "\n".join(lines)
