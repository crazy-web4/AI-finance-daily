"""搜索层解析器测试（架构评审 #15：最脆弱组件的 golden sample）"""
import unittest
from datetime import datetime, timedelta, timezone

import _path  # noqa: F401
from app.search.anysearch import (
    _extract_published_date,
    _parse_flexible_date,
    _parse_search_results,
)

GOLDEN_MD = """## Search Results (3 results, 297ms)

### 1. OpenAI releases GPT-6
- **URL**: https://openai.com/blog/gpt-6
- OpenAI announced GPT-6 on Aug 19, 2026 with new reasoning capabilities.

### 2. 智谱发布新一代模型
- **URL**: https://36kr.com/p/12345
- 智谱于2026年8月18日发布新一代模型，主打推理。

### 3. No date article
- **URL**: https://example.com/a/b
- Some content without any date mention.
"""


class TestMarkdownParser(unittest.TestCase):
    def test_parse_counts_and_fields(self):
        total, results = _parse_search_results(GOLDEN_MD)
        self.assertEqual(total, 3)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].title, "OpenAI releases GPT-6")
        self.assertEqual(str(results[0].url), "https://openai.com/blog/gpt-6")
        self.assertEqual(results[0].source_domain, "openai.com")
        self.assertIn("reasoning", results[0].snippet)

    def test_parse_empty(self):
        total, results = _parse_search_results("## Search Results (0 results, 10ms)\n")
        self.assertEqual(total, 0)
        self.assertEqual(results, [])

    def test_dates_extracted(self):
        _, results = _parse_search_results(GOLDEN_MD)
        self.assertEqual(results[0].published_at.day, 19)   # 英文日期
        self.assertEqual(results[1].published_at.day, 18)   # 中文日期
        self.assertIsNone(results[2].published_at)          # 无日期

    def test_url_date_priority(self):
        d = _extract_published_date("https://axios.com/2026-08-17/x", "no date")
        self.assertEqual(d.day, 17)

    def test_out_of_range_rejected(self):
        self.assertIsNone(_extract_published_date("https://x.com", "back in 2023-01-01"))

    def test_month_level_stale_signal(self):
        now = datetime.now(timezone.utc)
        stale = now - timedelta(days=150)
        text = f"{stale.year}年{stale.month}月的一些旧闻汇总"
        d = _extract_published_date("https://x.com", text)
        self.assertIsNotNone(d)  # 明显旧 → 标记
        # 当月 → 保留(None)
        self.assertIsNone(_extract_published_date("https://x.com", f"{now.year}年{now.month}月最新"))
        # 第四轮 T30: 上一自然月 → 标记为旧
        prev = (now.replace(day=1) - timedelta(days=1))
        self.assertIsNotNone(
            _extract_published_date("https://x.com", f"{prev.year}年{prev.month}月动态回顾"))

    def test_flexible_date(self):
        self.assertIsNotNone(_parse_flexible_date("2026-08-19T08:00:00"))
        self.assertIsNotNone(_parse_flexible_date("Aug 19, 2026"))
        self.assertIsNone(_parse_flexible_date(None))
        self.assertIsNone(_parse_flexible_date("not a date"))


if __name__ == "__main__":
    unittest.main()

# 第二轮 R18: _parse_batch_results 测试
from app.search.anysearch import _parse_batch_results

BATCH_GOLDEN_MD = """## Query 1: OpenAI new model

## Search Results (2 results, 150ms)
### 1. OpenAI unveils GPT-6
- **URL**: https://openai.com/blog/gpt6
- OpenAI announced GPT-6 today.

### 2. GPT-6 release date confirmed
- **URL**: https://techcrunch.com/2026/08/20/gpt6
- TechCrunch reports on the release date.

## Query 2: Anthropic funding

## Search Results (1 result, 200ms)
### 1. Anthropic raises \$2B
- **URL**: https://reuters.com/anthropic-funding
- Reuters reports on Anthropic funding round.

## Query 3: empty result

## Search Results (0 results, 50ms)
"""


class TestBatchParser(unittest.TestCase):
    def test_parse_batch_counts(self):
        results = _parse_batch_results(BATCH_GOLDEN_MD)
        self.assertEqual(len(results), 3)
        # (query_text, total_found, result_list)
        self.assertEqual(results[0][0], "OpenAI new model")
        self.assertEqual(results[0][1], 2)
        self.assertEqual(len(results[0][2]), 2)

        self.assertEqual(results[1][0], "Anthropic funding")
        self.assertEqual(results[1][1], 1)
        self.assertEqual(len(results[1][2]), 1)

        self.assertEqual(results[2][0], "empty result")
        self.assertEqual(results[2][1], 0)
        self.assertEqual(len(results[2][2]), 0)

    def test_parse_batch_first_result_fields(self):
        results = _parse_batch_results(BATCH_GOLDEN_MD)
        first = results[0][2][0]
        self.assertEqual(first.title, "OpenAI unveils GPT-6")
        self.assertEqual(str(first.url), "https://openai.com/blog/gpt6")
        self.assertEqual(first.source_domain, "openai.com")
        self.assertEqual(first.query_origin, "OpenAI new model")

    def test_parse_batch_empty(self):
        results = _parse_batch_results("")
        self.assertEqual(results, [])

    def test_parse_batch_single_query(self):
        md = """## Query 1: test query

## Search Results (1 result, 10ms)
### 1. Test Title
- **URL**: https://example.com/test
- Test snippet.
"""
        results = _parse_batch_results(md)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "test query")
        self.assertEqual(results[0][1], 1)
