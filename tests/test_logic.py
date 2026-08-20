"""选稿/编辑/核查/时区/查询 逻辑测试"""
import os
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import _path  # noqa: F401
import run_daily
from app.agents.factcheck import ground_key_data
from app.pipeline.collector import RawNewsArticle
from app.schemas.models import NewsEvent
from app.search.queries import _add_time_qualifier
from app.utils.timeutil import report_day_start, report_today

NOW = datetime.now(timezone.utc)


def mkart(aid, cat):
    return RawNewsArticle(
        article_id=aid, title="t", url=f"https://e.com/{aid}", source_domain="e.com",
        content="x" * 120, snippet="x" * 120, fetched_at=NOW, category=cat)


class TestSelection(unittest.TestCase):
    def test_balanced_selection(self):
        amap = {}
        def mkev(eid, cat, n):
            aids = [f"{eid}_{i}" for i in range(2)]
            for a in aids:
                amap[a] = mkart(a, cat)
            return NewsEvent(event_id=eid, canonical_title=eid, article_ids=aids,
                             article_count=n, source_domains=["d.com"])
        evs = [mkev("m1", "model_tech", 5), mkev("m2", "model_tech", 3),
               mkev("m3", "model_tech", 2), mkev("f1", "funding", 4),
               mkev("f2", "funding", 1), mkev("p1", "policy", 2),
               mkev("r1", "research", 2), mkev("i1", "industry", 6)]
        sel = run_daily._balanced_select_events(evs, amap, max_total=8)
        self.assertEqual(len(sel), 8)
        ids = [e.event_id for e in sel]
        self.assertIn("i1", ids)  # 热度最高必选
        self.assertIn("m2", ids)  # model_tech 保底2
        self.assertIn("f1", ids)  # funding 保底2


class TestFactCheck(unittest.TestCase):
    def test_grounding(self):
        kd = [{"label": "融资额", "value": "200亿美元"},
              {"label": "员工数", "value": "35000人"}]
        text = "本轮融资 200亿美元，由某基金领投。"
        grounded, dropped = ground_key_data(kd, text)
        self.assertEqual(len(grounded), 1)
        self.assertEqual(dropped, ["员工数=35000人"])


class TestTimezone(unittest.TestCase):
    def test_default_shanghai(self):
        expect = NOW.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        self.assertEqual(report_today(), expect)
        self.assertEqual(str(report_day_start("2026-08-20").tzinfo), "Asia/Shanghai")

    def test_override(self):
        os.environ["REPORT_TIMEZONE"] = "America/New_York"
        try:
            expect = NOW.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
            self.assertEqual(report_today(), expect)
        finally:
            del os.environ["REPORT_TIMEZONE"]


class TestQueryQualifier(unittest.TestCase):
    def test_dynamic_year(self):
        year = NOW.strftime("%Y")
        self.assertIn(year, _add_time_qualifier("EU AI Act implementation", "policy"))
        self.assertNotIn("august", _add_time_qualifier("x", None))

    def test_no_double_update(self):
        q = _add_time_qualifier("EU AI Act implementation update", "policy")
        self.assertEqual(q.count("update"), 1)


if __name__ == "__main__":
    unittest.main()
