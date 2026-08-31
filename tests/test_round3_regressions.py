"""第三轮评审（2026-08-31）回归测试

覆盖 T1/T2 入口级冒烟（第 8 批两个 NameError 回归的拦截网）、
T3 内联水印清洗、T4 跨天窗口、T6 无年份月日、T9 美股选条、T11 异常体系。
"""
import ast
import asyncio
import importlib.util
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _path  # noqa: F401

ROOT = Path(__file__).parent.parent


# ═══════════════════════════════════════════════════
# T1: run_daily 入口冒烟（拦截模块级 NameError 回归）
# ═══════════════════════════════════════════════════

class TestEntrySmoke(unittest.TestCase):
    def test_run_daily_imports_os_at_module_level(self):
        """T1 回归网: 模块顶层必须 import os（第 8 批曾漏掉导致入口即崩）。"""
        tree = ast.parse((ROOT / "run_daily.py").read_text(encoding="utf-8"))
        mod_imports = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                mod_imports.update(a.name for a in node.names)
        self.assertIn("os", mod_imports)

    def test_main_without_mode_exits_cleanly(self):
        """T1 回归网: 无模式参数时应走到提示并 SystemExit，而非 NameError。"""
        sys.path.insert(0, str(ROOT))
        import run_daily

        stub = (
            SimpleNamespace(environment="development"),
            mock.Mock(),  # logger
            mock.Mock(),  # perf_monitor
        )
        with mock.patch.object(run_daily, "init_system", return_value=stub), \
             mock.patch.object(sys, "argv", ["run_daily.py"]):
            with self.assertRaises(SystemExit):
                asyncio.run(run_daily.main())


class TestMainCollectClusterPath(unittest.TestCase):
    """入口冒烟: --test --no-agent 跑通 collect→cluster→落盘（无网络/无 LLM）。

    第三轮补充: 拦截 run_daily 主路径上的顶层 NameError/缺失导入类回归
    （基线曾缺 load_strategy/generate_queries 导入，被 T1 崩溃掩盖）。
    """

    def test_test_mode_no_agent_path(self):
        sys.path.insert(0, str(ROOT))
        import run_daily
        from datetime import datetime, timezone
        from app.pipeline.collector import RawNewsArticle

        now = datetime.now(timezone.utc)
        arts = [
            RawNewsArticle(
                article_id=f"art_{i}", title=f"OpenAI 发布新模型 GPT-{i} 系列",
                url=f"https://openai.com/{i}", source_domain="openai.com",
                snippet="x" * 120, content="x" * 120, fetched_at=now,
                category="model_tech",
            )
            for i in range(6)
        ]

        class StubCollector:
            def __init__(self, *a, **kw):
                self.last_stats = {"engine": "stub", "total_queries": 1}

            async def collect(self, queries, **kw):
                return arts

            def save_to_file(self, articles, filename, date_str=None):
                return Path("/tmp/stub_raw.json")

            async def close(self):
                pass

        with mock.patch.object(run_daily, "init_system",
                               return_value=(SimpleNamespace(environment="development"),
                                             mock.Mock(), mock.Mock())), \
             mock.patch.object(run_daily, "load_api_key", return_value="k"), \
             mock.patch.object(run_daily, "NewsCollector", StubCollector), \
             mock.patch.object(sys, "argv", ["run_daily.py", "--test", "--no-agent"]):
            try:
                asyncio.run(run_daily.main())
            except SystemExit as e:
                self.fail(f"主路径不应退出: {e}")


# ═══════════════════════════════════════════════════
# T2: collect() 的 Tavily 分支冒烟（拦截 tasks NameError 回归）
# ═══════════════════════════════════════════════════

class TestCollectTavilyBranch(unittest.TestCase):
    def test_collect_with_tavily_enabled(self):
        """T2 回归网: 启用 Tavily 时 collect 必须跑通双引擎合并。"""
        from app.pipeline.collector import NewsCollector
        from app.search.anysearch import (
            SearchQuery, SearchQueryResponse, SearchBatchResponse, SearchResultItem,
        )
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        def mk_item(url, title):
            return SearchResultItem(
                result_id=SearchResultItem.make_id(url, title),
                title=title, url=url, source_domain=url.split("/")[2],
                snippet="snippet text long enough", fetched_at=now,
            )

        class FakeAny:
            async def search_batch(self, queries, batch_id=None):
                return SearchBatchResponse(
                    batch_id="b", total_queries=len(queries),
                    success_queries=len(queries), failed_queries=0,
                    total_results=1, unique_results=1,
                    responses=[SearchQueryResponse(
                        query=queries[0].query, total_found=1,
                        results=[mk_item("https://a.com/1", "AnySearch 结果")],
                    )],
                    started_at=now, finished_at=now,
                )

            async def close(self):
                pass

        class FakeTavily:
            async def search(self, query, **kw):
                return [mk_item("https://t.com/1", "Tavily 结果")]

            async def close(self):
                pass

        collector = NewsCollector(api_key="k", tavily_api_key="tk")
        collector.client = FakeAny()
        collector.tavily = FakeTavily()
        try:
            articles = asyncio.run(collector.collect(
                [SearchQuery(query="q1", category="model_tech")],
                tavily_top_n=1,
            ))
        finally:
            asyncio.run(collector.close())
        titles = {a.title for a in articles}
        self.assertIn("AnySearch 结果", titles)
        self.assertIn("Tavily 结果", titles)


# ═══════════════════════════════════════════════════
# T3: 内联水印清洗
# ═══════════════════════════════════════════════════

class TestInlineWatermark(unittest.TestCase):
    def setUp(self):
        from app.utils.text_cleaner import clean_inline_watermark, light_clean
        self.clean = clean_inline_watermark
        self.light = light_clean

    def test_observed_artifacts_removed(self):
        self.assertEqual(self.clean("长鑫科技起诉美26国国防部", ), "长鑫科技起诉美国国防部")
        self.assertEqual(self.clean("要求20推翻认定"), "要求推翻认定")
        self.assertEqual(self.clean("整合20进 Siri"), "整合进 Siri")
        self.assertEqual(self.clean("被列为8-被告"), "被列为被告")
        self.assertEqual(self.clean("纪念版8-iPhone 同期"), "纪念版iPhone 同期")
        self.assertEqual(self.clean("AI 视频价8-"), "AI 视频价")
        self.assertEqual(self.clean("-08 月 28-30 日"), "8 月 28-30 日")

    def test_legit_numbers_preserved(self):
        for t in ["约20亿美元", "前20的AI大模型", "超过20起", "8月20日消息",
                  "累计20亿元", "沪指-0.11%", "沪指 -0.11%", "Series A 轮融资"]:
            self.assertEqual(self.clean(t), t, t)

    def test_light_clean_applies_to_titles(self):
        self.assertEqual(self.light("被列为8-被告"), "被列为被告")


# ═══════════════════════════════════════════════════
# T4: 跨天记忆窗口足天覆盖
# ═══════════════════════════════════════════════════

class TestHistoryWindow(unittest.TestCase):
    def test_days3_covers_three_full_days(self):
        import json, shutil
        from app.utils.timeutil import report_now
        from app.pipeline.history import load_recent_event_titles

        tmp = Path("/tmp/hist_test_r3")
        shutil.rmtree(tmp, ignore_errors=True)
        now = report_now()
        for back in (1, 2, 3):
            d = (now - timedelta(days=back)).strftime("%Y-%m-%d")
            (tmp / d).mkdir(parents=True)
            (tmp / d / "events_1.json").write_text(
                json.dumps([{"canonical_title": f"事件{back}"}]), encoding="utf-8")
        try:
            titles = load_recent_event_titles(
                days=3, exclude_date=now.strftime("%Y-%m-%d"), events_dir=tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(len(titles), 3, "days=3 应完整覆盖 3 天历史（T4 修复前只有 2 天）")


# ═══════════════════════════════════════════════════
# T6: 无年份月日信号
# ═══════════════════════════════════════════════════

class TestMonthDayDate(unittest.TestCase):
    def test_md_slash_recognized(self):
        from app.search.anysearch import _extract_published_date
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=3)
        d = _extract_published_date(
            "https://x.com/a", f"美股 {old.month}/{old.day}（周五）收盘")
        self.assertIsNotNone(d, "M/D 旧行情应获得 published_at 以便时效过滤")
        self.assertEqual((d.month, d.day), (old.month, old.day))

    def test_recent_md_kept(self):
        from app.search.anysearch import _extract_published_date
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        d = _extract_published_date("https://x.com/b", f"快讯 {now.month}月{now.day}日发布")
        self.assertIsNotNone(d)


# ═══════════════════════════════════════════════════
# T9: 美股选条先过滤后取 N
# ═══════════════════════════════════════════════════

class TestUsStocksItems(unittest.TestCase):
    def _load_mod(self):
        spec = importlib.util.spec_from_file_location(
            "add_us_stocks", ROOT / "scripts" / "add_us_stocks.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_short_articles_skipped_without_losing_quota(self):
        from datetime import datetime, timezone
        from app.pipeline.collector import RawNewsArticle
        mod = self._load_mod()
        now = datetime.now(timezone.utc)
        arts = []
        for i in range(10):
            short = i < 3
            arts.append(RawNewsArticle(
                article_id=f"a{i}", title=f"T{i}", url=f"https://e.com/{i}",
                source_domain="e.com", snippet="x" * (10 if short else 100),
                fetched_at=now,
            ))
        items = mod.articles_to_items(arts, max_items=6)
        self.assertEqual(len(items), 6, "前 3 篇过短时应从后续文章补足到 6 条")


# ═══════════════════════════════════════════════════
# T11: 异常体系 kwargs 修复
# ═══════════════════════════════════════════════════

class TestHandleApiError(unittest.TestCase):
    def test_401_raises_apperror_not_typeerror(self):
        from app.utils.exceptions import AppError, ErrorType, handle_api_error

        class FakeResp:
            status_code = 401
            headers = {}
            url = "http://x"

        with self.assertRaises(AppError) as cm:
            handle_api_error(FakeResp())
        self.assertEqual(cm.exception.error_type, ErrorType.API_AUTH_ERROR)


if __name__ == "__main__":
    unittest.main()
