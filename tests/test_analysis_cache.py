"""AnalystAgent 事件指纹分析缓存测试（Phase 3 · LLM 调用优化）。"""

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone

import _path  # noqa: F401

from app.agents.pipeline import AnalystAgent, _event_fingerprint
from app.pipeline.cluster import cluster_articles, build_article_map
from app.pipeline.collector import RawNewsArticle
from app.utils import cache as cache_mod
from app.utils.cache import SmartCache

NOW = datetime.now(timezone.utc)


def mk(url, title, domain="openai.com"):
    return RawNewsArticle(
        article_id=RawNewsArticle.make_id(url), title=title, url=url,
        source_domain=domain, content="x" * 120, snippet="x" * 120,
        fetched_at=NOW,
    )


class FakeLLM:
    """记录调用次数的假 LLM。"""

    def __init__(self):
        self.calls = 0

    def chat_text(self, system_prompt, user_prompt, temperature=0.3, **kwargs):
        self.calls += 1
        return json.dumps({
            "is_valid": True,
            "category": "model_tech",
            "importance_score": 80,
            "title": "测试事件",
            "details": "测试详情",
            "key_data": [],
            "source_names": ["x"],
            "topics": ["AI"],
        })


def _fixture():
    articles = [
        mk("https://a.com/1", "OpenAI 发布新一代 GPT 模型"),
        mk("https://b.com/2", "OpenAI 推出新一代 GPT 模型功能"),
    ]
    events = cluster_articles(articles, title_threshold=0.6)
    article_map = build_article_map(articles)
    return events, article_map


class TestAnalysisCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # 把全局缓存指向临时目录，避免污染 data/cache
        self._old = cache_mod._cache_instance
        cache_mod._cache_instance = SmartCache(cache_dir=self.tmp)

    def tearDown(self):
        cache_mod._cache_instance = self._old

    def test_second_run_uses_cache(self):
        events, article_map = _fixture()
        self.assertEqual(len(events), 1)
        fake = FakeLLM()
        analyst = AnalystAgent(llm=fake, use_cache=True)

        async def run():
            return await analyst.analyze_batch_async(events, article_map)

        r1 = asyncio.run(run())
        self.assertEqual(fake.calls, 1)
        self.assertEqual(len(r1), 1)

        # 重跑同一事件：应命中缓存，LLM 不再调用
        r2 = asyncio.run(run())
        self.assertEqual(fake.calls, 1, "第二次应命中缓存，LLM 调用数不变")
        self.assertEqual(len(r2), 1)

    def test_new_agent_hits_shared_cache(self):
        events, article_map = _fixture()
        fake1, fake2 = FakeLLM(), FakeLLM()
        asyncio.run(AnalystAgent(llm=fake1).analyze_batch_async(events, article_map))
        self.assertEqual(fake1.calls, 1)
        # 换一个 agent（进程内共享缓存）→ 直接命中，fake2 不被调用
        asyncio.run(AnalystAgent(llm=fake2).analyze_batch_async(events, article_map))
        self.assertEqual(fake2.calls, 0)

    def test_use_cache_false_always_calls(self):
        events, article_map = _fixture()
        fake = FakeLLM()
        analyst = AnalystAgent(llm=fake, use_cache=False)
        async def run():
            return await analyst.analyze_batch_async(events, article_map)
        asyncio.run(run())
        asyncio.run(run())
        self.assertEqual(fake.calls, 2, "关闭缓存时每次都应调用 LLM")

    def test_fingerprint_stable_and_distinct(self):
        events, article_map = _fixture()
        ev = events[0]
        fp1 = _event_fingerprint(ev)
        fp2 = _event_fingerprint(ev)
        self.assertEqual(fp1, fp2)
        self.assertTrue(fp1.startswith("evt_"))
        # 不同事件（不同文章）指纹不同
        other_articles = [mk("https://c.com/3", "Google 发布全新 Gemini", "google.com")]
        other_events = cluster_articles(other_articles, title_threshold=0.6)
        self.assertNotEqual(fp1, _event_fingerprint(other_events[0]))


if __name__ == "__main__":
    unittest.main()
