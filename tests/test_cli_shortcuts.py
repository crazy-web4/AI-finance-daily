"""快捷命令 today/latest 测试（建议 #2 T-A2）"""
import argparse
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_store, write_report_tree, make_report
from app.cli import shortcuts
from app.storage.report_store import ReportStore


def ns(**kw):
    base = dict(open=False, no_open=True, json=False, stats=False, section=None, limit=10)
    base.update(kw)
    return argparse.Namespace(**base)


class TestShortcuts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = make_store(self.tmp, ("2026-08-31", "2026-09-01"))

    def test_locate_latest(self):
        r = shortcuts.locate(self.store, "latest")
        self.assertTrue(r.found)
        self.assertEqual(r.date, "2026-09-01")
        self.assertTrue(r.pdf.exists())

    def test_locate_today_falls_back(self):
        r = shortcuts.locate(self.store, "today")
        self.assertTrue(r.found)  # 回退到最近一天
        self.assertIn("回退", r.message)

    def test_empty_store_friendly(self):
        empty = ReportStore(self.tmp / "x")
        r = shortcuts.locate(empty, "today")
        self.assertFalse(r.found)
        rc = shortcuts.cmd_today(ns(), empty)
        self.assertEqual(rc, 0)

    def test_no_pdf_report(self):
        write_report_tree(self.tmp, "2026-09-03", make_report("2026-09-03"), with_pdf=False)
        r = shortcuts.locate(self.store, "latest")
        # 最新 09-03 无 pdf → found False（友好提示），不抛异常
        self.assertEqual(r.date, "2026-09-03")

    def test_report_summary(self):
        raw = self.store.load_raw("2026-09-01")
        summ = shortcuts.report_summary(raw, limit=1)
        self.assertEqual(summ["total_items"], raw["total_items"])
        self.assertTrue(all(len(s["items"]) <= 1 for s in summ["sections"]))

    def test_run_stats(self):
        rl = self.store.load_runlog("2026-09-01")
        st = shortcuts.run_stats(rl)
        self.assertTrue(st["available"])
        self.assertEqual(st["articles"], 50)
        self.assertEqual(st["llm_calls"], 7)

    def test_run_stats_missing(self):
        self.assertFalse(shortcuts.run_stats(None)["available"])

    def test_open_file_missing_binary(self):
        # 不存在的程序不应抛异常
        self.assertIsInstance(shortcuts.open_file(Path("/tmp/definitely_not_exist_xyz")), bool)


if __name__ == "__main__":
    unittest.main()
