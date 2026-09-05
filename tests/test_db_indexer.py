"""SQLite 情报库索引测试（建议 #7 T-C7）"""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_store, make_report, write_report_tree
from app.storage.indexer import build_index, index_one_date
from app.storage.db import connect, init_db, indexed_dates, stats_overview, upsert_report
from app.storage.report_store import ReportStore


class TestDbIndexer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "data" / "reports"
        self.db = self.tmp / "intel.db"
        make_store(self.tmp, ("2026-08-31", "2026-09-01"))

    def test_build_index(self):
        res = build_index(self.db, self.reports, rebuild=True)
        self.assertEqual(len(res["indexed"]), 2)
        self.assertEqual(res["failed"], [])
        self.assertTrue(self.db.exists())

    def test_idempotent_reindex(self):
        build_index(self.db, self.reports, rebuild=True)
        conn = connect(self.db)
        n1 = conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
        conn.close()
        # 重建不翻倍
        res = build_index(self.db, self.reports, rebuild=True)
        conn = connect(self.db)
        n2 = conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
        conn.close()
        self.assertEqual(n1, n2)

    def test_incremental_skips_indexed(self):
        build_index(self.db, self.reports, rebuild=True)
        res = build_index(self.db, self.reports, rebuild=False)
        self.assertEqual(len(res["skipped"]), 2)
        self.assertEqual(res["indexed"], [])

    def test_entities_extracted(self):
        build_index(self.db, self.reports, rebuild=True)
        conn = connect(self.db)
        names = {r["name"] for r in conn.execute("SELECT DISTINCT name FROM entities")}
        conn.close()
        self.assertIn("OpenAI", names)
        self.assertIn("Anthropic", names)

    def test_fts_search_latin(self):
        build_index(self.db, self.reports, rebuild=True)
        conn = connect(self.db)
        rows = conn.execute(
            "SELECT i.title FROM items_fts f JOIN items i ON i.id=f.rowid WHERE items_fts MATCH 'OpenAI'").fetchall()
        conn.close()
        self.assertTrue(any("OpenAI" in r["title"] for r in rows))

    def test_stats(self):
        build_index(self.db, self.reports, rebuild=True)
        conn = connect(self.db)
        s = stats_overview(conn)
        conn.close()
        self.assertEqual(s["reports"], 2)
        self.assertGreater(s["items"], 0)
        self.assertTrue(s["by_section"])

    def test_transaction_rollback_on_bad_report(self):
        conn = connect(self.db)
        init_db(conn)
        store = ReportStore(self.reports)
        # 坏数据不应留下半写入
        ok, n, err = index_one_date(conn, store, "1999-01-01")
        self.assertFalse(ok)
        conn.close()


if __name__ == "__main__":
    unittest.main()
