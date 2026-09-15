"""订阅与个性化测试（建议 #11 T-D11）"""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_report
from app.personalization.store import SubscriptionStore, Subscription, DEFAULT_USER
from app.personalization.filter import filter_report


class TestSubscriptionStore(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "subs"
        self.store = SubscriptionStore(self.dir)

    def test_add_and_get(self):
        sub = self.store.add("default", companies=["OpenAI"], categories=["funding"])
        self.assertEqual(sub.companies, ["OpenAI"])
        self.assertEqual(sub.categories, ["funding"])
        got = self.store.get("default")
        self.assertEqual(got.companies, ["OpenAI"])

    def test_dedup_add(self):
        self.store.add("default", companies=["OpenAI"])
        self.store.add("default", companies=["OpenAI", "Anthropic"])
        self.assertEqual(self.store.get("default").companies, ["OpenAI", "Anthropic"])

    def test_list_all(self):
        self.store.add("alice", companies=["Google"])
        self.store.add("bob", categories=["policy"])
        names = {s.name for s in self.store.list_all()}
        self.assertEqual(names, {"alice", "bob"})

    def test_remove(self):
        self.store.add("default", companies=["OpenAI", "xAI"])
        self.store.remove("default", companies=["OpenAI"])
        self.assertEqual(self.store.get("default").companies, ["xAI"])

    def test_delete(self):
        self.store.add("default", companies=["OpenAI"])
        self.assertTrue(self.store.delete("default"))
        self.assertFalse(self.store.exists("default"))

    def test_get_missing_returns_empty(self):
        sub = self.store.get("ghost")
        self.assertEqual(sub.companies, [])


class TestFilter(unittest.TestCase):
    def setUp(self):
        self.report = make_report("2026-09-01")

    def test_company_filter(self):
        out = filter_report(self.report, ["OpenAI"], [], "u")
        self.assertLess(out.total_items, self.report.total_items)
        titles = " ".join(it.title for s in out.sections for it in s.items)
        self.assertIn("OpenAI", titles)

    def test_category_filter(self):
        out = filter_report(self.report, [], ["funding"], "u")
        self.assertTrue(all(
            sid in ("funding", "top_news") for s in out.sections
            for sid in [s.section_id.value if hasattr(s.section_id, "value") else s.section_id]
        ))

    def test_empty_subscription_returns_original(self):
        out = filter_report(self.report, [], [], "u")
        self.assertEqual(out.total_items, self.report.total_items)

    def test_personalized_id_and_banner(self):
        out = filter_report(self.report, ["OpenAI"], ["funding"], "alice")
        self.assertIn("alice", out.report_id)
        self.assertIn("个性化", out.editor_summary)

    def test_chinese_company_substring(self):
        out = filter_report(self.report, ["月之暗面"], [], "u")
        titles = " ".join(it.title for s in out.sections for it in s.items)
        self.assertIn("月之暗面", titles)

    def test_rerank_starts_at_one(self):
        out = filter_report(self.report, ["OpenAI"], ["funding"], "u")
        for s in out.sections:
            if s.items:
                self.assertEqual(s.items[0].rank, 1)


if __name__ == "__main__":
    unittest.main()
