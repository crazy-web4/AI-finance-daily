"""跨天去重测试"""
import json
import shutil
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import _path  # noqa: F401
from app.pipeline.history import filter_seen_events, load_recent_event_titles
from app.schemas.models import NewsEvent


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = Path("/tmp/hist_test")
        shutil.rmtree(self.tmp, ignore_errors=True)
        yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        (self.tmp / yest).mkdir(parents=True)
        (self.tmp / yest / "events_1.json").write_text(
            json.dumps([{"canonical_title": "OpenAI 发布 GPT-6 模型"}]), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_and_filter(self):
        titles = load_recent_event_titles(days=3, exclude_date=datetime.now().strftime("%Y-%m-%d"), events_dir=self.tmp)
        self.assertEqual(len(titles), 1)

        def mkev(eid, t):
            return NewsEvent(event_id=eid, canonical_title=t, article_ids=[], article_count=1, source_domains=[])
        fresh, seen = filter_seen_events(
            [mkev("e1", "OpenAI 发布 GPT-6 模型"), mkev("e2", "Anthropic 融资")], titles)
        self.assertEqual([e.event_id for e in fresh], ["e2"])
        self.assertEqual([e.event_id for e, _ in seen], ["e1"])

    def test_exclude_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        (self.tmp / today).mkdir(parents=True)
        (self.tmp / today / "events_9.json").write_text(
            json.dumps([{"canonical_title": "今日事件"}]), encoding="utf-8")
        titles = load_recent_event_titles(days=3, exclude_date=today, events_dir=self.tmp)
        self.assertNotIn((today, "今日事件"), titles)


if __name__ == "__main__":
    unittest.main()
