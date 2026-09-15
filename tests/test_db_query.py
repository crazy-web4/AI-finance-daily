"""情报库检索测试（建议 #7 T-C7）"""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_store
from app.storage.indexer import build_index
from app.storage.query import search, stats, format_results, format_stats


class TestDbQuery(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "data" / "reports"
        self.db = self.tmp / "intel.db"
        make_store(self.tmp, ("2026-08-31", "2026-09-01"))
        build_index(self.db, self.reports, rebuild=True)

    def test_search_latin(self):
        rows = search(self.db, "OpenAI")
        self.assertTrue(rows)
        self.assertTrue(all("OpenAI" in (r["title"] + r["details"]) or "OpenAI" in r.get("companies", []) for r in rows))

    def test_search_chinese_like(self):
        rows = search(self.db, "融资")
        self.assertTrue(rows)
        # 中文走 LIKE 召回
        self.assertTrue(any(r["match"] in ("like", "fts") for r in rows))

    def test_search_category_filter(self):
        rows = search(self.db, "", category="funding")
        self.assertTrue(rows)
        self.assertTrue(all(r["section_id"] == "funding" for r in rows))

    def test_search_days_filter(self):
        rows = search(self.db, "OpenAI", days=1)
        # 2026-09-01 相对"今天"是过去很久，days=1 可能为空，不报错即可
        self.assertIsInstance(rows, list)
        rows_all = search(self.db, "OpenAI", days=100000)
        self.assertTrue(rows_all)

    def test_search_importance_min(self):
        rows = search(self.db, "OpenAI", importance_min=0)
        self.assertTrue(rows)

    def test_stats_shape(self):
        s = stats(self.db)
        self.assertEqual(s["reports"], 2)
        self.assertIn("top_companies", s)

    def test_formatters(self):
        self.assertIn("命中", format_results(search(self.db, "OpenAI"), "OpenAI"))
        self.assertIn("期数", format_stats(stats(self.db)))
        self.assertIn("未找到", format_results([], "xxx"))

    def test_browse_no_keyword(self):
        rows = search(self.db, "", limit=5)
        self.assertLessEqual(len(rows), 5)


if __name__ == "__main__":
    unittest.main()
