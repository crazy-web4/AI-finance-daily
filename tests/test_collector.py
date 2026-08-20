"""采集器去重/分级测试"""
import unittest
from datetime import datetime, timezone

import _path  # noqa: F401
from app.pipeline.collector import (
    RawNewsArticle,
    _detect_language,
    _normalize_url,
    _rate_reliability,
    dedup_by_title,
    dedup_by_url,
)

NOW = datetime.now(timezone.utc)


def mk(aid, title, url, domain="e.com", rel="unknown", snippet="x" * 100):
    return RawNewsArticle(
        article_id=RawNewsArticle.make_id(url), title=title, url=url,
        source_domain=domain, content=snippet, snippet=snippet,
        fetched_at=NOW, source_reliability=rel,
    )


class TestDedup(unittest.TestCase):
    def test_url_dedup_merges_and_counts(self):
        a1 = mk("a1", "T", "https://e.com/x?utm_source=tw", snippet="short")
        a2 = mk("a2", "T", "https://e.com/x", snippet="much longer snippet here")
        # article_id 基于归一化 URL，两者应相同
        self.assertEqual(RawNewsArticle.make_id("https://e.com/x?utm_source=tw"),
                         RawNewsArticle.make_id("https://e.com/x"))
        out = dedup_by_url([a1, a2])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].result_count, 2)
        self.assertIn("much longer", out[0].snippet)  # 保留更长摘要

    def test_title_dedup_keeps_reliable(self):
        a = mk("a", "OpenAI releases GPT-6 model", "https://e.com/a", rel="high")
        b = mk("b", "OpenAI releases GPT-6 model", "https://e.com/b", rel="low")
        out = dedup_by_title([a, b], similarity_threshold=0.9)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].source_reliability, "high")

    def test_title_dedup_keeps_distinct(self):
        a = mk("a", "OpenAI releases GPT-6", "https://e.com/a")
        b = mk("b", "Anthropic raises funding", "https://e.com/b")
        self.assertEqual(len(dedup_by_title([a, b])), 2)

    def test_normalize_url_strips_trackers(self):
        self.assertEqual(
            _normalize_url("https://E.com/path/?utm_source=x&id=1#frag"),
            "https://e.com/path?id=1",
        )

    def test_reliability_tiers(self):
        self.assertEqual(_rate_reliability("openai.com"), "high")
        self.assertEqual(_rate_reliability("www.sec.gov"), "high")
        self.assertEqual(_rate_reliability("reuters.com"), "medium")
        self.assertEqual(_rate_reliability("36kr.com"), "low")
        self.assertEqual(_rate_reliability("random-blog.io"), "unknown")

    def test_language(self):
        self.assertEqual(_detect_language("中文内容测试"), "zh")
        self.assertEqual(_detect_language("english text here"), "en")


if __name__ == "__main__":
    unittest.main()
