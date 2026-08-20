"""聚类测试（含 #9 公司感知阈值）"""
import unittest
from datetime import datetime, timezone

import _path  # noqa: F401
from app.pipeline.cluster import cluster_articles
from app.pipeline.collector import RawNewsArticle

NOW = datetime.now(timezone.utc)


def mk(url, title, domain="e.com"):
    return RawNewsArticle(
        article_id=RawNewsArticle.make_id(url), title=title, url=url,
        source_domain=domain, content="x" * 120, snippet="x" * 120, fetched_at=NOW,
    )


class TestCluster(unittest.TestCase):
    def test_similar_titles_merge(self):
        arts = [
            mk("https://a.com/1", "OpenAI releases GPT-6 model"),
            mk("https://b.com/2", "OpenAI releases GPT-6 model today"),
            mk("https://c.com/3", "Anthropic announces new funding round"),
        ]
        events = cluster_articles(arts, title_threshold=0.6)
        self.assertEqual(len(events), 2)
        multi = [e for e in events if e.article_count > 1]
        self.assertEqual(len(multi), 1)

    def test_company_aware_threshold(self):
        # 共享公司 + 中等相似度(0.45~0.6) → 公司感知下应合并
        arts = [
            mk("https://a.com/1", "NVIDIA 发布新一代 AI 芯片"),
            mk("https://b.com/2", "NVIDIA 推出新一代 AI 芯片产品"),
        ]
        events = cluster_articles(arts, title_threshold=0.6)
        self.assertEqual(len(events), 1, "共享公司时应放宽阈值合并")

    def test_no_company_no_merge_at_low_sim(self):
        # 无共享公司 + 低于阈值相似度 → 不合并
        arts = [
            mk("https://a.com/1", "某公司发布新一代 AI 芯片"),
            mk("https://b.com/2", "另一家推出新一代 AI 芯片产品"),
        ]
        events = cluster_articles(arts, title_threshold=0.6)
        self.assertEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()
