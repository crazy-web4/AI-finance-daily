"""多格式导出测试（建议 #4 T-B4）"""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_report
from app.exporter import run_all_exporters, ALL_EXPORTERS
from app.exporter.markdown import report_to_markdown
from app.exporter.wechat import report_to_wechat_html
from app.exporter.email import report_to_email_html, email_subject
from app.exporter.notion import report_to_notion_blocks, report_to_notion_json


class TestExporters(unittest.TestCase):
    def setUp(self):
        self.report = make_report("2026-09-01")
        self.tmp = Path(tempfile.mkdtemp())

    def test_all_exporters_write_files(self):
        res = run_all_exporters(self.report, self.tmp)
        self.assertEqual(set(res.keys()), set(ALL_EXPORTERS))
        for fmt, r in res.items():
            self.assertTrue(r["ok"], f"{fmt} failed: {r['error']}")
            self.assertTrue(Path(r["path"]).exists())

    def test_markdown_gfm(self):
        md = report_to_markdown(self.report)
        self.assertIn("# AI 行业全球动态日报", md)
        self.assertIn("## 今日头条", md)
        self.assertIn("OpenAI 发布 GPT-5", md)
        self.assertIn("[", md)  # 来源链接

    def test_wechat_inline_html(self):
        h = report_to_wechat_html(self.report)
        self.assertIn("<section", h)
        self.assertIn("style=", h)
        self.assertNotIn("<link", h)  # 无外部依赖
        self.assertIn("OpenAI", h)

    def test_email_inline_css(self):
        h = report_to_email_html(self.report)
        self.assertIn("max-width", h)
        self.assertIn("融资", h)
        self.assertTrue(email_subject(self.report).endswith("条）"))

    def test_notion_blocks_valid(self):
        blocks = report_to_notion_blocks(self.report)
        self.assertTrue(all(b["object"] == "block" for b in blocks))
        types_ = {b["type"] for b in blocks}
        self.assertIn("heading_2", types_)
        payload = report_to_notion_json(self.report)
        self.assertIn("children", payload)
        json.dumps(payload, ensure_ascii=False)  # 可序列化

    def test_disabled_exporter_skipped(self):
        res = run_all_exporters(self.report, self.tmp, enabled=("markdown",))
        self.assertIn("markdown", res)
        self.assertNotIn("wechat", res)

    def test_individual_failure_isolated(self):
        # 传入坏 report 不应让其它格式崩溃
        class Bad:
            pass
        res = run_all_exporters(Bad(), self.tmp)  # type: ignore
        # 所有格式都失败但 run_all_exporters 不抛
        self.assertTrue(all(not r["ok"] for r in res.values()))


if __name__ == "__main__":
    unittest.main()
