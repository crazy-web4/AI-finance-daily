"""
SQLite 情报数据库（建议 #7 · T-C7）
=================================================
日报积累成可检索的本地情报库。表结构：

- ``reports``  ：每期日报元数据（日期/条目数/字数/产物路径）
- ``items``    ：日报条目（栏目/标题/详情/来源/公司），跨期可检索
- ``items_fts``：FTS5 全文索引（title/details/analysis）
- ``entities`` ：公司/机构提及（跨期聚合，供趋势/告警）

中文检索：FTS5(unicode61) 对拉丁文（OpenAI/Claude）走 MATCH；
中文子串在查询层用 LIKE 兜底召回（见 query.py）。所有写入走事务，失败回滚。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from app.schemas.models import DailyReport
from app.storage.entities import extract_companies

DEFAULT_DB_PATH = "data/intel.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    date              TEXT PRIMARY KEY,
    report_id         TEXT,
    total_items       INTEGER,
    total_word_count  INTEGER,
    editor_summary    TEXT,
    json_path         TEXT,
    pdf_path          TEXT,
    generated_at      TEXT,
    indexed_at        TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,
    item_uid      TEXT NOT NULL UNIQUE,
    section_id    TEXT,
    section_name  TEXT,
    rank          INTEGER,
    title         TEXT,
    details       TEXT,
    analysis      TEXT,
    sources       TEXT,
    companies     TEXT,
    importance    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_date ON items(date);
CREATE INDEX IF NOT EXISTS idx_items_section ON items(section_id);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, details, analysis,
    content='', tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS entities (
    name      TEXT NOT NULL,
    date      TEXT NOT NULL,
    item_uid  TEXT NOT NULL,
    section_id TEXT,
    PRIMARY KEY (name, item_uid)
);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_date ON entities(date);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """打开（必要时创建）数据库连接。"""
    path = Path(db_path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """创建表与索引（幂等）。"""
    conn.executescript(_SCHEMA)
    conn.commit()


def _importance(section_id: str, rank: int) -> int:
    """无 LLM 重要性分值时的确定性代理分：头条高、排名越靠前越高。"""
    base = 100 - (rank - 1) * 6
    if section_id == "top_news":
        base += 10
    elif section_id == "funding":
        base += 3
    return max(40, min(99, base))


def upsert_report(
    conn: sqlite3.Connection,
    report: DailyReport,
    json_path: str | Path | None = None,
    pdf_path: str | Path | None = None,
) -> int:
    """
    把一期日报写入数据库（事务，重复日期先清旧再写，保证幂等）。
    返回写入条目数。
    """
    date = report.report_date
    now = datetime.now().isoformat(timespec="seconds")
    item_count = 0
    try:
        conn.execute("BEGIN")
        # 清旧（幂等重索引）
        old_ids = [r["id"] for r in conn.execute("SELECT id FROM items WHERE date=?", (date,))]
        if old_ids:
            placeholders = ",".join("?" * len(old_ids))
            conn.execute(f"DELETE FROM items_fts WHERE rowid IN ({placeholders})", old_ids)
        conn.execute("DELETE FROM items WHERE date=?", (date,))
        conn.execute("DELETE FROM entities WHERE date=?", (date,))
        conn.execute("DELETE FROM reports WHERE date=?", (date,))

        conn.execute(
            "INSERT INTO reports VALUES (?,?,?,?,?,?,?,?,?)",
            (date, report.report_id, report.total_items, report.total_word_count,
             report.editor_summary, str(json_path) if json_path else None,
             str(pdf_path) if pdf_path else None,
             report.generated_at.isoformat() if report.generated_at else now, now),
        )

        for section in report.sections:
            sid = section.section_id.value if hasattr(section.section_id, "value") else str(section.section_id)
            for item in section.items:
                companies = extract_companies(f"{item.title} {item.details} {item.analysis or ''}")
                sources = [{"name": s.name, "url": str(s.url), "is_official": s.is_official}
                           for s in item.sources]
                # item_id 在每个栏目内从 item_001 重新编号，跨栏目会重复；
                # 拼上 section_id 保证全局唯一。
                uid = f"{date}:{sid}:{item.item_id}"
                cur = conn.execute(
                    "INSERT INTO items (date,item_uid,section_id,section_name,rank,title,details,analysis,sources,companies,importance)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (date, uid, sid, section.section_name, item.rank, item.title,
                     item.details, item.analysis,
                     json.dumps(sources, ensure_ascii=False),
                     json.dumps(companies, ensure_ascii=False),
                     _importance(sid, item.rank)),
                )
                row_id = cur.lastrowid
                conn.execute(
                    "INSERT INTO items_fts (rowid, title, details, analysis) VALUES (?,?,?,?)",
                    (row_id, item.title, item.details, item.analysis or ""),
                )
                for name in companies:
                    conn.execute(
                        "INSERT OR IGNORE INTO entities (name,date,item_uid,section_id) VALUES (?,?,?,?)",
                        (name, date, uid, sid),
                    )
                item_count += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return item_count


def indexed_dates(conn: sqlite3.Connection) -> list[str]:
    return [r["date"] for r in conn.execute("SELECT date FROM reports ORDER BY date")]


def stats_overview(conn: sqlite3.Connection, since: str | None = None) -> dict[str, Any]:
    """库级统计：期数/条目数/公司分布/栏目分布。"""
    where = "WHERE date >= ?" if since else ""
    params: tuple = (since,) if since else ()
    total_reports = conn.execute(f"SELECT COUNT(*) c FROM reports {where}", params).fetchone()["c"]
    total_items = conn.execute(f"SELECT COUNT(*) c FROM items {where}", params).fetchone()["c"]
    by_section = [
        dict(r) for r in conn.execute(
            f"SELECT section_id, section_name, COUNT(*) n FROM items {where} GROUP BY section_id ORDER BY n DESC",
            params,
        )
    ]
    by_company = [
        dict(r) for r in conn.execute(
            f"SELECT name, COUNT(DISTINCT date) days, COUNT(*) mentions FROM entities {where} "
            "GROUP BY name ORDER BY mentions DESC LIMIT 20",
            params,
        )
    ]
    return {
        "reports": total_reports,
        "items": total_items,
        "by_section": by_section,
        "top_companies": by_company,
    }
