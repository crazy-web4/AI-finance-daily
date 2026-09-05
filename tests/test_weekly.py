"""周报聚合测试（建议 #9 T-C9）"""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_store
from app.storage.report_store import ReportStore
from app.report.weekly import (
    week_range, load_week_reports, aggregate_weekly,
    render_weekly_markdown, render_weekly_html, build_weekly,
)


class TestWeekly(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "data" / "reports"
        # 同一周（2026-08-31 周一 ~ 09-06 周日）内 3 天
        make_store(self.tmp, ("2026-08-31", "2026-09-01", "2026-09-02"))
        self.store = ReportStore(self.reports)

    def test_week_range(self):
        mon, sun = week_range("2026-09-03")
        self.assertEqual(mon, "2026-08-31")
        self.assertEqual(sun, "2026-09-06")

    def test_load_week_reports(self):
        reps, mon, sun = load_week_reports(self.store, "2026-09-03")
        self.assertEqual(len(reps), 3)

    def test_aggregate(self):
        reps, mon, sun = load_week_reports(self.store, "2026-09-03")
        agg = aggregate_weekly(reps, mon, sun)
        self.assertEqual(agg["report_count"], 3)
        self.assertTrue(agg["top_companies"])
        self.assertIn("OpenAI", [c["company"] for c in agg["top_companies"]])
        self.assertTrue(agg["funding"])

    def test_markdown_contains_sections(self):
        reps, mon, sun = load_week_reports(self.store, "2026-09-03")
        md = render_weekly_markdown(aggregate_weekly(reps, mon, sun))
        self.assertIn("周报", md)
        self.assertIn("公司活跃度", md)
        self.assertIn("融资", md)

    def test_html_self_contained(self):
        reps, mon, sun = load_week_reports(self.store, "2026-09-03")
        h = render_weekly_html(aggregate_weekly(reps, mon, sun))
        self.assertIn("<html", h)
        self.assertIn("OpenAI", h)

    def test_build_weekly_outputs(self):
        out = self.tmp / "weekly"
        res = build_weekly("2026-09-03", store=self.store, output_root=out)
        self.assertTrue(res["ok"])
        self.assertTrue(Path(res["markdown"]).exists())
        self.assertTrue(Path(res["html"]).exists())
        self.assertEqual(res["report_count"], 3)

    def test_build_weekly_empty_week(self):
        empty = ReportStore(self.tmp / "nope")
        res = build_weekly("2026-01-01", store=empty, output_root=self.tmp / "w2")
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()
