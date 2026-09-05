"""订阅推送闭环测试（第14批续）：注入假 sender，不走网络。"""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_report
from app.personalization.digest import (
    PushResult, digest_markdown, digest_text, push_all, push_one,
)
from app.personalization.store import Subscription, SubscriptionStore


class TestDigest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.subs = self.tmp / "subs"
        self.report = make_report("2026-09-01")

    def _add_sub(self, name, companies=None, categories=None, webhook="", emails=None):
        store = SubscriptionStore(self.subs)
        store.save(Subscription(name=name, companies=companies or [],
                                categories=categories or [], webhook=webhook,
                                emails=emails or []))

    def test_digest_text_contains_filtered_items(self):
        sub = Subscription(name="alice", companies=["OpenAI"])
        res = push_one(self.report, sub,
                       sender=lambda url, t, m: (True, "webhook"),
                       webhook_url="https://example.com/hook")
        self.assertTrue(res.ok)
        self.assertIn("webhook", res.channels)
        self.assertGreaterEqual(res.items, 1)

    def test_no_hit_skips_push(self):
        sub = Subscription(name="bob", companies=["不存在的公司ZZZ"])
        calls = []
        res = push_one(self.report, sub,
                       sender=lambda *a: calls.append(a) or (True, "webhook"),
                       webhook_url="https://example.com/hook")
        self.assertEqual(res.items, 0)
        self.assertEqual(calls, [])  # 无命中不推送

    def test_no_channel_returns_empty(self):
        sub = Subscription(name="carol", companies=["OpenAI"])
        res = push_one(self.report, sub)  # 无 webhook / 无 email
        self.assertEqual(res.channels, [])

    def test_email_channel(self):
        sub = Subscription(name="dave", companies=["OpenAI"], emails=["d@x.com"])
        sent = []
        def email_sender(report, to_addrs):
            sent.append(to_addrs)
            return True, "email"
        res = push_one(self.report, sub, email_sender=email_sender)
        self.assertTrue(res.ok)
        self.assertIn("email", res.channels)
        self.assertEqual(sent, [["d@x.com"]])

    def test_push_all_iterates_subs(self):
        self._add_sub("alice", companies=["OpenAI"], webhook="https://e.com/h")
        self._add_sub("bob", categories=["funding"], webhook="https://e.com/h")
        results = push_all(self.report, subs_dir=self.subs,
                           sender=lambda url, t, m: (True, "webhook"))
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.ok for r in results))

    def test_push_all_no_subs_dir(self):
        results = push_all(self.report, subs_dir=self.tmp / "nope")
        self.assertEqual(results, [])

    def test_failed_channel_recorded(self):
        sub = Subscription(name="erin", companies=["OpenAI"], webhook="https://e.com/h")
        res = push_one(self.report, sub, sender=lambda *a: (False, "webhook:Timeout"))
        self.assertFalse(res.ok)
        self.assertTrue(any("Timeout" in e for e in res.errors))

    def test_markdown_contains_link_when_base_url(self):
        md = digest_markdown(self.report, "alice", base_url="http://127.0.0.1:8910")
        self.assertIn("http://127.0.0.1:8910/my?user=alice", md)


if __name__ == "__main__":
    unittest.main()
