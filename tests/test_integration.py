"""
集成测试 - 端到端流水线
"""

import unittest
import asyncio
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

from app.schemas.models import RawNewsArticle, NewsEvent
from app.pipeline.collector import NewsCollector
from app.pipeline.cluster import cluster_articles
from app.agents.pipeline import AnalystAgent
from app.config import AppConfig
from app.utils.cache import get_cache
from app.utils.logger import get_logger


class TestFullPipeline(unittest.TestCase):
    """完整流水线集成测试"""

    def setUp(self):
        # 创建临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir) / "data"
        self.data_dir.mkdir()

    def tearDown(self):
        # 清理临时目录
        shutil.rmtree(self.temp_dir)

    def test_cluster_articles_integration(self):
        """测试聚类集成"""
        # 创建测试数据
        articles = self._create_test_articles()

        # 执行聚类
        events = cluster_articles(articles, title_threshold=0.65)

        # 验证结果
        self.assertGreater(len(events), 0)
        self.assertLessEqual(len(events), len(articles))

        # 验证事件完整性
        total_articles = sum(e.article_count for e in events)
        self.assertEqual(total_articles, len(articles))

    def test_collector_integration(self):
        """测试采集器集成"""
        from datetime import datetime, timezone
        from app.schemas.models import SearchResultItem
        from app.search.anysearch import (
            SearchQuery, SearchQueryResponse, SearchBatchResponse,
        )

        # 模拟API响应
        now = datetime.now(timezone.utc)
        item = SearchResultItem(
            result_id="res_1",
            title="OpenAI发布了新模型",
            url="https://openai.com/news",
            source_domain="openai.com",
            snippet="OpenAI发布了新模型",
            fetched_at=now,
        )
        batch = SearchBatchResponse(
            batch_id="test",
            total_queries=1,
            success_queries=1,
            failed_queries=0,
            total_results=1,
            unique_results=1,
            responses=[SearchQueryResponse(query="OpenAI", total_found=1, results=[item])],
            started_at=now,
            finished_at=now,
        )

        # NewsCollector 把 AnySearchClient 导入到自身模块命名空间，需 patch 该引用
        with patch('app.pipeline.collector.AnySearchClient') as mock_client:
            mock_instance = mock_client.return_value
            mock_instance.search_batch = AsyncMock(return_value=batch)
            mock_instance.close = AsyncMock()

            collector = NewsCollector(
                api_key="test",
                output_dir=str(self.data_dir),
                use_tavily=False,
            )
            queries = [SearchQuery(query="OpenAI", max_results=10)]
            articles = asyncio.run(collector.collect(queries))

            self.assertEqual(len(articles), 1)
            self.assertEqual(articles[0].title, "OpenAI发布了新模型")

    def test_analyzer_integration(self):
        """测试分析器集成"""
        # 创建测试事件
        articles = self._create_test_articles()
        events = cluster_articles(articles, title_threshold=0.65)

        # 创建分析器
        analyst = AnalystAgent()

        # 模拟文章映射
        article_map = {a.article_id: a for a in articles}

        # 执行分析（使用少量事件进行测试）
        with patch.object(analyst.llm, 'chat_text') as mock_chat:
            # 设置mock响应
            mock_chat.return_value = json.dumps({
                "is_valid": True,
                "category": "model_tech",
                "importance_score": 85,
                "title": "测试事件",
                "details": "测试详情",
                "key_data": [],
                "published_at": None,
                "source_names": ["测试来源"],
                "topics": ["AI"]
            })


            # 执行分析
            results = asyncio.run(
                analyst.analyze_batch_async(events[:1], article_map, max_events=1)
            )

            # 验证结果
            self.assertEqual(len(results), 1)
            _, analysis = results[0]
            self.assertEqual(analysis['category'], 'model_tech')

    @patch('app.config.AppConfig')
    def test_config_integration(self, mock_config):
        """测试配置集成"""
        # 设置mock配置
        config = AppConfig()
        config.cache.max_memory_items = 500
        config.concurrency.collector_max_workers = 3

        # 验证配置
        self.assertEqual(config.cache.max_memory_items, 500)
        self.assertEqual(config.concurrency.collector_max_workers, 3)

    def test_cache_integration(self):
        """测试缓存集成"""
        # 使用测试缓存
        cache = get_cache()

        # 设置缓存
        cache.set("integration_test", "value")

        # 获取缓存
        value = cache.get("integration_test")
        self.assertEqual(value, "value")

    def test_logger_integration(self):
        """测试日志集成"""
        # logger 直接写进传入的 log_dir
        log_dir = str(Path(self.temp_dir) / "logs")
        # 创建日志记录器
        logger = get_logger("test_integration", log_dir=log_dir)

        # 记录日志
        logger.info("测试日志", test_param="value")

        # 验证日志文件创建
        log_file = Path(log_dir) / "test_integration.log"
        self.assertTrue(log_file.exists())

    def test_error_scenarios(self):
        """测试错误场景"""
        # 测试空数据
        articles = []
        events = cluster_articles(articles)
        self.assertEqual(len(events), 0)

        # 测试单篇文章
        single_article = self._create_single_article()
        events = cluster_articles([single_article])
        self.assertEqual(len(events), 1)

    def _create_test_articles(self) -> list[RawNewsArticle]:
        """创建测试文章"""
        return [
            RawNewsArticle(
                article_id="art_001",
                title="OpenAI发布了GPT-4模型",
                url="https://openai.com/gpt4",
                source_domain="openai.com",
                content="GPT-4是OpenAI的最新模型",
                snippet="GPT-4发布",
                fetched_at="2026-08-20T10:00:00Z"
            ),
            RawNewsArticle(
                article_id="art_002",
                title="OpenAI推出新版GPT-4",
                url="https://openai.com/gpt4-new",
                source_domain="openai.com",
                content="新版GPT-4性能提升",
                snippet="GPT-4新版发布",
                fetched_at="2026-08-20T11:00:00Z"
            ),
            RawNewsArticle(
                article_id="art_003",
                title="Google发布Gemini模型",
                url="https://google.com/gemini",
                source_domain="google.com",
                content="Google的Gemini模型发布",
                snippet="Gemini模型发布",
                fetched_at="2026-08-20T12:00:00Z"
            )
        ]

    def _create_single_article(self) -> RawNewsArticle:
        """创建单篇文章"""
        return RawNewsArticle(
            article_id="art_single",
            title="单一文章",
            url="https://example.com/single",
            source_domain="example.com",
            content="这是单一文章",
            snippet="单一文章摘要",
            fetched_at="2026-08-20T10:00:00Z"
        )


class TestPerformanceIntegration(unittest.TestCase):
    """性能集成测试"""

    def test_large_dataset_performance(self):
        """大数据集性能测试"""
        # 创建大量测试数据
        articles = []
        for i in range(100):
            articles.append(RawNewsArticle(
                article_id=f"art_{i:03d}",
                title=f"文章标题 {i}",
                url=f"https://example.com/article/{i}",
                source_domain="example.com",
                content=f"文章内容 {i}",
                snippet=f"摘要 {i}",
                fetched_at="2026-08-20T10:00:00Z"
            ))

        # 测试聚类性能
        import time
        start_time = time.time()
        events = cluster_articles(articles, title_threshold=0.6)
        duration = time.time() - start_time

        # 验证性能（100篇文章应该在60秒内处理完成）
        self.assertLess(duration, 60)
        self.assertGreater(len(events), 0)


if __name__ == '__main__':
    unittest.main()
