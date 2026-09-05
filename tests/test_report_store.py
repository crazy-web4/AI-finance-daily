"""报告产物发现测试（第 10 批地基）"""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_store, write_report_tree, make_report
from app.storage.report_store import ReportStore


class TestReportStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = make_store(self.tmp, ("2026-08-30", "2026-09-01"))

    def test_dates_sorted(self):
        self.assertEqual(self.store.report_dates(), ["2026-08-30", "2026-09-01"])

    def test_latest_is_newest(self):
        self.assertEqual(self.store.latest().date, "2026-09-01")

    def test_primary_pdf_prefers_base(self):
        art = self.store.get("2026-09-01")
        self.assertIn("2026-09-01", art.primary_pdf().name)
        self.assertNotIn("_v2", art.primary_pdf().name)

    def test_load_report_model(self):
        rep = self.store.load_report("2026-09-01")
        self.assertIsNotNone(rep)
        self.assertEqual(rep.report_date, "2026-09-01")
        self.assertGreater(rep.total_items, 0)

    def test_load_runlog(self):
        rl = self.store.load_runlog("2026-09-01")
        self.assertTrue(rl["success"])
        self.assertEqual(rl["articles"], 50)

    def test_missing_date_no_report(self):
        art = self.store.get("2020-01-01")
        self.assertFalse(art.has_report)
        self.assertIsNone(art.primary_pdf())

    def test_empty_store(self):
        empty = ReportStore(self.tmp / "nope")
        self.assertIsNone(empty.latest())
        self.assertEqual(len(empty), 0)

    def test_variant_segregation(self):
        # 写出一个 _us 变体，主报告仍应是基础版
        write_report_tree(self.tmp, "2026-09-02", make_report("2026-09-02"), variant="CyberGm")
        write_report_tree(self.tmp, "2026-09-02", make_report("2026-09-02"), variant="us")
        art = self.store.get("2026-09-02")
        self.assertIsNotNone(art.daily_json)
        self.assertGreaterEqual(len(art.variant_jsons), 1)


if __name__ == "__main__":
    unittest.main()
