"""优雅降级测试（建议 #12 T-D12）"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_report
from app.schemas.models import (
    NewsEvent, RawNewsArticle, EventType, Category, SourceReliability,
)
from app.utils.fallback import (
    build_template_report, event_category, playwright_available, FALLBACK_FLAG,
    render_outputs_with_fallback,
)


def make_article(aid, domain="reuters.com", title="文章"):
    return RawNewsArticle(
        article_id=aid, title=title, url=f"https://{domain}/story",
        source_domain=domain, source_name=domain,
        content="这是文章正文内容，包含事件详情。", snippet="摘要片段。",
        fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        source_reliability=SourceReliability.HIGH,
    )


def make_event(eid, title, etype, domains, count=2):
    aids = [f"art_{eid}_{i}" for i in range(count)]
    return NewsEvent(
        event_id=f"evt_{eid}", canonical_title=title, article_ids=aids,
        article_count=count, event_type_guess=etype, source_domains=domains,
    ), aids


class TestFallback(unittest.TestCase):
    def setUp(self):
        self.article_map = {}
        self.events = []
        specs = [
            ("OpenAI 发布 GPT-5", EventType.MODEL_RELEASE, ["openai.com"]),
            ("Anthropic 完成融资", EventType.FUNDING_ROUND, ["anthropic.com"]),
            ("欧盟发布 AI 监管新规", EventType.REGULATION_UPDATE, ["europa.eu"]),
        ]
        for i, (t, et, doms) in enumerate(specs):
            ev, aids = make_event(i, t, et, doms)
            self.events.append(ev)
            for j, aid in enumerate(aids):
                self.article_map[aid] = make_article(aid, doms[0], t)

    def test_event_category_mapping(self):
        self.assertEqual(event_category(self.events[0]), Category.MODEL_TECH)
        self.assertEqual(event_category(self.events[1]), Category.FUNDING)
        self.assertEqual(event_category(self.events[2]), Category.POLICY)

    def test_template_report_structure(self):
        rep = build_template_report(self.events, self.article_map, "2026-09-01")
        self.assertEqual(rep.report_date, "2026-09-01")
        self.assertGreater(rep.total_items, 0)
        # 头条按 article_count 排序，有栏目
        sec_ids = [s.section_id for s in rep.sections]
        self.assertIn(Category.TOP_NEWS, sec_ids)

    def test_template_report_flags_fallback(self):
        rep = build_template_report(self.events, self.article_map, "2026-09-01")
        self.assertTrue(any("降级" in f or "LLM" in f for f in rep.quality_flags))
        self.assertIn(FALLBACK_FLAG, rep.quality_flags)

    def test_template_report_has_sources(self):
        rep = build_template_report(self.events, self.article_map, "2026-09-01")
        all_items = [it for s in rep.sections for it in s.items]
        with_src = [it for it in all_items if it.sources]
        self.assertTrue(with_src)

    def test_template_report_top_news_dedup(self):
        rep = build_template_report(self.events, self.article_map, "2026-09-01", top_n=2)
        top = rep.sections[0]
        self.assertEqual(top.section_id, Category.TOP_NEWS)
        self.assertLessEqual(top.item_count, 2)

    def test_render_outputs_returns_markdown(self):
        # playwright 在测试环境（py3.12）可能不可用，函数必须返回 markdown/html 兜底
        from app.report.renderer import PDFRenderer, RenderConfig
        tmp = Path(tempfile.mkdtemp())
        rep = make_report("2026-09-01")
        renderer = PDFRenderer(RenderConfig(output_dir=str(tmp)))
        out = render_outputs_with_fallback(rep, renderer=renderer)
        self.assertIn("markdown", out)
        self.assertIsNotNone(out["markdown"])
        self.assertTrue(Path(out["markdown"]).exists())
        self.assertIsInstance(out["degraded"], bool)
        self.assertTrue(str(tmp) in str(out["markdown"]))

    def test_playwright_available_returns_bool(self):
        self.assertIsInstance(playwright_available(), bool)

    def test_playwright_probe_safe_inside_event_loop(self):
        # 回归：do_pdf 是 async，sync_playwright 不能在事件循环线程启动；
        # playwright_available() 放到独立线程，两种上下文都必须返回 bool 且不抛。
        import asyncio
        self.assertIsInstance(playwright_available(), bool)

        async def _in_loop():
            return playwright_available()

        self.assertIsInstance(asyncio.run(_in_loop()), bool)


if __name__ == "__main__":
    unittest.main()
