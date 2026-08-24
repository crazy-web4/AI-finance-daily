"""渲染器测试（None 导读不崩 + CSS 内联）"""
import unittest
from datetime import datetime, timezone

import _path  # noqa: F401
from app.report.renderer import PDFRenderer
from app.schemas.models import Category, DailyReport, ReportItem, ReportSection

NOW = datetime.now(timezone.utc)


def mk_report(editor_summary=None, with_item=False):
    items = []
    if with_item:
        items.append(ReportItem(
            item_id="item_001", event_id="evt_1", rank=1, category=Category.TOP_NEWS,
            title="Clau de 发布新模型", lead="", details="第一段内容。\n\n第二段内容。",
            word_count=20))
    return DailyReport(
        report_id="daily_t", report_date="2026-08-24",
        time_window_start=NOW, time_window_end=NOW,
        total_items=len(items), total_word_count=20,
        editor_summary=editor_summary,
        sections=[ReportSection(section_id=Category.TOP_NEWS, section_name="今日头条",
                                item_count=len(items), items=items)],
    )


class TestRenderer(unittest.TestCase):
    def test_none_summary_no_crash(self):
        html = PDFRenderer().render_html(mk_report(editor_summary=None))
        self.assertIn("<html", html)

    def test_css_inlined(self):
        html = PDFRenderer().render_html(mk_report(editor_summary="导读文字"))
        self.assertIn("<style>", html)
        self.assertNotIn('href="css/style.css"', html)

    def test_broken_word_fixed_in_output(self):
        html = PDFRenderer().render_html(mk_report(editor_summary="x", with_item=True))
        self.assertIn("Claude 发布新模型", html)
        self.assertNotIn("Clau de", html)


if __name__ == "__main__":
    unittest.main()
