"""
索引构建（建议 #7 · T-C7）
扫描 data/reports/ 下全部日报 JSON，写入 SQLite（build / rebuild / 增量）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from app.storage.db import DEFAULT_DB_PATH, connect, init_db, indexed_dates, upsert_report
from app.storage.report_store import ReportStore


def index_one_date(
    conn,
    store: ReportStore,
    date: str,
) -> tuple[bool, int, str | None]:
    """索引单个日期，返回 (ok, item_count, error)。"""
    art = store.get(date)
    if not art.daily_json:
        return False, 0, "no daily json"
    try:
        report = store.load_report(date)
        if report is None:
            return False, 0, "report parse failed"
        pdf = art.primary_pdf()
        n = upsert_report(conn, report, json_path=art.daily_json, pdf_path=pdf)
        return True, n, None
    except Exception as e:  # noqa: BLE001
        return False, 0, f"{type(e).__name__}: {e}"


def build_index(
    db_path: str | Path = DEFAULT_DB_PATH,
    reports_dir: str | Path = "data/reports",
    rebuild: bool = False,
    on_progress: Optional[Callable[[str, int], None]] = None,
) -> dict[str, Any]:
    """
    建/补索引。

    rebuild=True 时先删除旧库全量重建；否则增量（已索引且 JSON 未变的日期跳过）。
    """
    db_path = Path(db_path)
    if rebuild and db_path.exists():
        db_path.unlink()
        for side in (db_path.with_suffix(".db-wal"), db_path.with_suffix(".db-shm")):
            side.unlink(missing_ok=True)

    store = ReportStore(reports_dir)
    conn = connect(db_path)
    init_db(conn)
    already = set(indexed_dates(conn))

    indexed: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    total_items = 0

    for date in store.report_dates():
        if date in already and not rebuild:
            skipped.append(date)
            continue
        ok, n, err = index_one_date(conn, store, date)
        if ok:
            indexed.append(date)
            total_items += n
            if on_progress:
                on_progress(date, n)
        else:
            failed.append({"date": date, "error": err or "unknown"})

    conn.close()
    return {
        "db_path": str(db_path),
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "total_items": total_items,
        "total_reports": len(store.report_dates()),
    }


def ensure_indexed(
    db_path: str | Path = DEFAULT_DB_PATH,
    reports_dir: str | Path = "data/reports",
) -> None:
    """确保库与表存在（供 run_daily 增量写库前调用）。"""
    conn = connect(db_path)
    init_db(conn)
    conn.close()
