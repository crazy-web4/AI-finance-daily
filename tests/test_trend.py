"""跨期趋势测试（建议 #8 T-C8）"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_store
from app.storage.indexer import build_index
from app.storage.db import connect
from app.storage.trend import (
    funding_hotspots, headline_diff, topic_heat,
    format_funding, format_headline_diff, format_topics, _similar,
)


class TestTrend(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "data" / "reports"
        self.db = self.tmp / "intel.db"
        # 跨两周的数据
        make_store(self.tmp, ("2026-08-24", "2026-08-26", "2026-08-31", "2026-09-01"))
        build_index(self.db, self.reports, rebuild=True)
        self.conn = connect(self.db)

    def tearDown(self):
        self.conn.close()

    def test_week_range_monday_sunday(self):
        from app.report.weekly import week_range
        mon, sun = week_range("2026-09-02")  # 周三
        self.assertEqual(mon, "2026-08-31")  # 周一
        self.assertEqual(sun, "2026-09-06")  # 周日

    def test_funding_hotspots(self):
        rows = funding_hotspots(self.conn, weeks=4)
        self.assertTrue(rows)
        names = [r["company"] for r in rows]
        self.assertIn("xAI", names)  # 合成数据融资栏目: xAI 融资 / 月之暗面
        # 按 count 降序
        counts = [r["count"] for r in rows]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_headline_diff_structure(self):
        d = headline_diff(self.conn)
        for k in ("this_week", "added", "kept", "dropped", "week_start"):
            self.assertIn(k, d)

    def test_topic_heat_buckets(self):
        heat = topic_heat(self.conn, weeks=4)
        self.assertTrue(heat)
        ws = list(heat.keys())
        self.assertEqual(ws, sorted(ws))

    def test_formatters_run(self):
        self.assertIn("融资热点", format_funding(funding_hotspots(self.conn, 4), 4))
        self.assertIn("头条差异", format_headline_diff(headline_diff(self.conn)))
        self.assertIn("话题", format_topics(topic_heat(self.conn, 4), 4))

    def test_similarity_helper(self):
        a = (frozenset(["OpenAI"]), frozenset(["OpenAI", "发布", "GPT"]))
        b = (frozenset(["OpenAI"]), frozenset(["OpenAI", "发布", "GPT", "编码"]))
        self.assertTrue(_similar(a, b))
        c = (frozenset(["xAI"]), frozenset(["完全", "不同", "内容"]))
        self.assertFalse(_similar(a, c))

    def test_empty_data(self):
        empty_db = self.tmp / "empty.db"
        from app.storage.db import connect as c2, init_db
        conn = c2(empty_db); init_db(conn)
        self.assertEqual(funding_hotspots(conn, 4), [])
        self.assertEqual(headline_diff(conn)["added"], [])
        conn.close()


if __name__ == "__main__":
    unittest.main()
