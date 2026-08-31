"""
聚类算法优化测试
"""

import unittest
from datetime import datetime, timezone

from app.schemas.models import RawNewsArticle, NewsEvent
from app.pipeline.cluster import (
    cluster_articles,
    _preprocess_buckets,
    _get_bucket_key,
    _greedy_cluster_articles,
    _single_to_event,
    _merge_similar_events
)


class TestPreprocessBuckets(unittest.TestCase):
    """测试预处理分桶"""

    def setUp(self):
        self.articles = [
            self._create_article("OpenAI发布了GPT-4模型", "openai.com"),
            self._create_article("OpenAI融资10亿美元", "openai.com"),
            self._create_article("Google发布Gemini模型", "google.com"),
            self._create_article("特斯拉发布了新车", "tesla.com"),
        ]

    def _create_article(self, title, domain):
        return RawNewsArticle(
            article_id=f"art_{hash(title)}",
            title=title,
            url=f"https://{domain}",
            source_domain=domain,
            content="",
            snippet=title,
            fetched_at=datetime.now(timezone.utc)
        )

    def test_company_bucketing(self):
        """测试按公司分桶"""
        buckets = _preprocess_buckets(self.articles)

        # OpenAI的文章应该在同一个桶
        openai_bucket = buckets.get("openai", [])
        self.assertEqual(len(openai_bucket), 2)

        # Google的文章在单独的桶
        google_bucket = buckets.get("google", [])
        self.assertEqual(len(google_bucket), 1)

    def test_domain_bucketing(self):
        """测试按域名分桶"""
        articles = [
            self._create_article("Test 1", "unknown1.com"),
            self._create_article("Test 2", "unknown2.com"),
        ]
        buckets = _preprocess_buckets(articles)

        # 应该按域名分桶
        self.assertIn("unknown1.com", buckets)
        self.assertIn("unknown2.com", buckets)


class TestGetBucketKey(unittest.TestCase):
    """测试获取分桶键"""

    def test_company_key(self):
        """测试公司名作为键"""
        article = self._create_article("OpenAI发布了GPT-4模型", "openai.com")
        key = _get_bucket_key(article)
        self.assertEqual(key, "openai")

    def test_domain_key(self):
        """测试域名作为键"""
        article = self._create_article("Unknown company news", "unknown.com")
        key = _get_bucket_key(article)
        self.assertEqual(key, "unknown.com")

    def _create_article(self, title, domain):
        return RawNewsArticle(
            article_id=f"art_{hash(title)}",
            title=title,
            url=f"https://{domain}",
            source_domain=domain,
            content="",
            snippet=title,
            fetched_at=datetime.now(timezone.utc)
        )


class TestGreedyClusterArticles(unittest.TestCase):
    """测试贪心聚类算法"""

    def setUp(self):
        self.articles = [
            self._create_article("OpenAI发布了GPT-4模型", "openai.com"),
            self._create_article("OpenAI推出新版GPT-4", "openai.com"),
            self._create_article("Google发布Gemini模型", "google.com"),
            self._create_article("OpenAI融资成功", "openai.com"),
        ]

    def _create_article(self, title, domain):
        return RawNewsArticle(
            article_id=f"art_{hash(title)}",
            title=title,
            url=f"https://{domain}",
            source_domain=domain,
            content="",
            snippet=title,
            fetched_at=datetime.now(timezone.utc)
        )

    def test_clustering_with_same_company(self):
        """测试相同公司的文章聚类"""
        events = _greedy_cluster_articles(self.articles, title_threshold=0.65)

        # 应该聚类成3个事件
        self.assertEqual(len(events), 3)

        # 验证事件ID和文章数量
        event_articles = [e.article_count for e in events]
        self.assertIn(2, event_articles)  # 两个相似的文章聚类
        self.assertIn(1, event_articles)  # 单独的文章


class TestSingleToEvent(unittest.TestCase):
    """测试单篇文章转事件"""

    def test_single_event_creation(self):
        """测试单篇文章事件创建"""
        article = self._create_article("Single article", "example.com")
        event = _single_to_event(article)

        self.assertEqual(event.article_count, 1)
        self.assertEqual(len(event.article_ids), 1)
        self.assertEqual(event.source_domains, ["example.com"])

    def _create_article(self, title, domain):
        return RawNewsArticle(
            article_id=f"art_{hash(title)}",
            title=title,
            url=f"https://{domain}",
            source_domain=domain,
            content="",
            snippet=title,
            fetched_at=datetime.now(timezone.utc)
        )


class TestMergeSimilarEvents(unittest.TestCase):
    """测试事件合并"""

    def setUp(self):
        self.events = [
            self._create_event("OpenAI news 1", ["openai"], ["openai.com"]),
            self._create_event("OpenAI news 2", ["openai"], ["openai.com"]),
            self._create_event("Google news", ["google"], ["google.com"]),
        ]

    def _create_event(self, title, companies, domains):
        return NewsEvent(
            event_id=f"evt_{hash(title)}",
            canonical_title=title,
            article_ids=[f"art_{hash(title)}"],
            article_count=1,
            companies_mentioned=companies,
            source_domains=domains,
            cluster_score=0.8,
        )

    def test_merge_similar_events(self):
        """测试相似事件合并"""
        merged = _merge_similar_events(self.events[:2])

        # 合并后应该有2篇文章
        self.assertEqual(merged.article_count, 2)
        self.assertEqual(len(merged.article_ids), 2)
        self.assertEqual(len(merged.companies_mentioned), 1)


class TestFullClusteringPipeline(unittest.TestCase):
    """测试完整的聚类流水线"""

    def setUp(self):
        self.articles = [
            # OpenAI 相关
            self._create_article("OpenAI发布了GPT-4模型", "openai.com"),
            self._create_article("OpenAI推出新版GPT-4", "openai.com"),
            self._create_article("OpenAI获得融资", "openai.com"),

            # Google 相关
            self._create_article("Google发布Gemini模型", "google.com"),
            self._create_article("Google推出新搜索", "google.com"),

            # 其他
            self._create_article("特斯拉新车发布", "tesla.com"),
            self._create_article("苹果发布新手机", "apple.com"),
        ]

    def _create_article(self, title, domain):
        return RawNewsArticle(
            article_id=f"art_{hash(title)}",
            title=title,
            url=f"https://{domain}",
            source_domain=domain,
            content="",
            snippet=title,
            fetched_at=datetime.now(timezone.utc)
        )

    def test_clustering_performance(self):
        """测试聚类性能"""
        start_time = datetime.now()
        events = cluster_articles(self.articles, title_threshold=0.6)
        duration = (datetime.now() - start_time).total_seconds()

        # 应该聚类成合理数量的事件
        self.assertGreater(len(events), 1)
        self.assertLessEqual(len(events), 7)

        # 验证事件完整性
        total_articles = sum(e.article_count for e in events)
        self.assertEqual(total_articles, len(self.articles))

        # 验证排序（按文章数量降序）
        for i in range(len(events) - 1):
            self.assertGreaterEqual(
                events[i].article_count,
                events[i + 1].article_count
            )

    def test_clustering_with_different_thresholds(self):
        """测试不同阈值的聚类效果"""
        # 高阈值（更严格的聚类）
        high_threshold_events = cluster_articles(self.articles, title_threshold=0.8)
        # 低阈值（更宽松的聚类）
        low_threshold_events = cluster_articles(self.articles, title_threshold=0.5)

        # 阈值越宽松（低）合并越多、事件数越少：低阈值事件数应 <= 高阈值事件数
        self.assertLessEqual(len(low_threshold_events), len(high_threshold_events))


if __name__ == '__main__':
    unittest.main()
