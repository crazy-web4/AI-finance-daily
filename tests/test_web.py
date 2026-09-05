"""本地 Web 看板路由测试（建议 #1 T-A1，不起 server）"""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_store
from app.web.server import WebApp


class TestWeb(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        store = make_store(self.tmp, ("2026-08-31", "2026-09-01"))
        self.app = WebApp(reports_dir=self.tmp / "data" / "reports", base_dir=self.tmp)

    def test_index_ok(self):
        r = self.app.handle("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn("text/html", r.content_type)
        self.assertIn("AI 财经日报", r.body.decode())

    def test_health_page_and_api(self):
        r = self.app.handle("GET", "/health")
        self.assertEqual(r.status, 200)
        api = self.app.handle("GET", "/api/health")
        data = json.loads(api.body)
        self.assertIn("success_rate", data)
        self.assertEqual(data["runs"], 2)
        self.assertEqual(data["success"], 2)

    def test_config_page_masks_keys(self):
        r = self.app.handle("GET", "/config")
        self.assertEqual(r.status, 200)
        self.assertNotIn("as_sk_realkey", r.body.decode())

    def test_report_detail(self):
        r = self.app.handle("GET", "/report/2026-09-01")
        self.assertEqual(r.status, 200)
        self.assertIn("OpenAI", r.body.decode())

    def test_report_missing_404(self):
        r = self.app.handle("GET", "/report/1999-01-01")
        self.assertEqual(r.status, 404)

    def test_feed_route(self):
        r = self.app.handle("GET", "/feed.xml")
        self.assertEqual(r.status, 200)
        self.assertIn("rss", r.content_type)

    def test_api_reports(self):
        r = self.app.handle("GET", "/api/reports")
        data = json.loads(r.body)
        self.assertEqual(data["count"], 2)

    def test_file_serving_pdf(self):
        r = self.app.handle("GET", "/file/2026-09-01/AI行业全球动态日报_2026-09-01@Cyber_Gm.pdf")
        self.assertEqual(r.status, 200)
        self.assertIn("pdf", r.content_type)
        self.assertTrue(r.body.startswith(b"%PDF"))

    def test_path_traversal_blocked(self):
        r = self.app.handle("GET", "/file/2026-09-01/../../etc/passwd")
        self.assertIn(r.status, (400, 404))

    def test_unknown_route_404(self):
        r = self.app.handle("GET", "/no-such-page")
        self.assertEqual(r.status, 404)


if __name__ == "__main__":
    unittest.main()


class TestWebT13(unittest.TestCase):
    """第13批：在线读报 / 搜索 / 洞察 / 订阅。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        store = make_store(self.tmp, ("2026-08-31", "2026-09-01"))
        self.app = WebApp(reports_dir=self.tmp / "data" / "reports", base_dir=self.tmp)

    def test_read_view_full_content(self):
        r = self.app.handle("GET", "/read/2026-09-01")
        self.assertEqual(r.status, 200)
        body = r.body.decode()
        self.assertIn("GPT-5", body)          # 标题
        self.assertIn("编辑点评", body)        # analysis
        self.assertIn("reuters.com", body)    # 来源链接
        self.assertIn("今日导读", body)

    def test_read_view_missing_404(self):
        r = self.app.handle("GET", "/read/1999-01-01")
        self.assertEqual(r.status, 404)

    def test_read_view_escapes_html(self):
        # 正文里的 <script> 必须被转义，不能原样出现
        from app.schemas.models import DailyReport
        import tests._factory as fx
        report = fx.make_report("2026-09-02")
        report.sections[0].items[0].title = "XSS <script>alert(1)</script> 头条"
        fx.write_report_tree(self.tmp, "2026-09-02", report=report)
        r = self.app.handle("GET", "/read/2026-09-02")
        self.assertEqual(r.status, 200)
        self.assertNotIn("<script>alert(1)", r.body.decode())
        self.assertIn("&lt;script&gt;", r.body.decode())

    def test_search_page_requires_db(self):
        # 合成 store 无 intel.db -> _open_db 自动构建索引
        r = self.app.handle("GET", "/search?q=OpenAI")
        self.assertEqual(r.status, 200)
        self.assertIn("OpenAI", r.body.decode())

    def test_search_empty_shows_form(self):
        r = self.app.handle("GET", "/search")
        self.assertEqual(r.status, 200)
        self.assertIn("全站情报搜索", r.body.decode())

    def test_api_search_json(self):
        r = self.app.handle("GET", "/api/search?q=融资")
        self.assertEqual(r.status, 200)
        data = json.loads(r.body)
        self.assertIn("results", data)
        self.assertGreaterEqual(data["count"], 1)

    def test_insights_page(self):
        r = self.app.handle("GET", "/insights")
        self.assertEqual(r.status, 200)
        body = r.body.decode()
        self.assertIn("栏目分布", body)
        self.assertIn("高频公司", body)

    def test_subscriptions_post_and_my(self):
        body = "name=default&companies=OpenAI&categories=funding".encode()
        r = self.app.handle("POST", "/subscriptions", body=body)
        self.assertEqual(r.status, 200)
        self.assertIn("已保存", r.body.decode())
        r2 = self.app.handle("GET", "/my")
        self.assertEqual(r2.status, 200)
        self.assertIn("订阅版", r2.body.decode())
        r3 = self.app.handle("GET", "/api/subscriptions")
        subs = json.loads(r3.body)["subscriptions"]
        self.assertTrue(any(s["name"] == "default" for s in subs))

    def test_subscriptions_page_get(self):
        r = self.app.handle("GET", "/subscriptions")
        self.assertEqual(r.status, 200)
        self.assertIn("订阅管理", r.body.decode())

    def test_trigger_full_mode(self):
        r = self.app.handle("POST", "/trigger?mode=full", body=b"")
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(r.body)["mode"], "full")


class TestWebT14(unittest.TestCase):
    """第14批：归档 / 阅读导航 / 条目下钻 / 公司时间线。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        make_store(self.tmp, ("2026-08-31", "2026-09-01", "2026-09-02"))
        self.app = WebApp(reports_dir=self.tmp / "data" / "reports", base_dir=self.tmp)

    def test_archive_lists_all_months(self):
        r = self.app.handle("GET", "/archive")
        self.assertEqual(r.status, 200)
        body = r.body.decode()
        self.assertIn("历史归档", body)
        self.assertIn("2026-08", body)
        self.assertIn("2026-09", body)
        self.assertIn("/read/2026-09-02", body)

    def test_read_pager_and_toc(self):
        r = self.app.handle("GET", "/read/2026-09-01")
        body = r.body.decode()
        self.assertIn("本期目录", body)            # TOC
        self.assertIn("上一期", body)             # pager
        self.assertIn("下一期", body)
        self.assertIn("/item/2026-09-01/", body)  # detail link
        self.assertIn('id="item_001"', body)      # anchor

    def test_read_first_no_prev(self):
        r = self.app.handle("GET", "/read/2026-08-31")
        self.assertIn("无上一期", r.body.decode())

    def test_item_detail(self):
        r = self.app.handle("GET", "/item/2026-09-01/item_001")
        self.assertEqual(r.status, 200)
        body = r.body.decode()
        self.assertIn("原文来源", body)
        self.assertIn("reuters.com", body)
        self.assertIn("返回 2026-09-01 日报", body)

    def test_item_detail_missing_404(self):
        r = self.app.handle("GET", "/item/2026-09-01/item_999")
        self.assertEqual(r.status, 404)

    def test_item_route_bad_format(self):
        r = self.app.handle("GET", "/item/2026-09-01")
        self.assertEqual(r.status, 404)

    def test_company_timeline(self):
        r = self.app.handle("GET", "/company/OpenAI")
        self.assertEqual(r.status, 200)
        body = r.body.decode()
        self.assertIn("OpenAI", body)
        self.assertIn("/read/2026-09-02", body)

    def test_insights_company_links(self):
        r = self.app.handle("GET", "/insights")
        self.assertEqual(r.status, 200)
        self.assertIn("/company/", r.body.decode())


class TestWebWeekly(unittest.TestCase):
    """第14批续：周报在线页 + 周报离线产物下载。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        make_store(self.tmp, ("2026-08-31", "2026-09-01", "2026-09-02"))
        # 造一个离线周报产物
        wdir = self.tmp / "data" / "reports" / "weekly" / "2026-08-31"
        wdir.mkdir(parents=True, exist_ok=True)
        (wdir / "周报_2026-08-31_to_2026-09-06.html").write_text("<html>weekly</html>", encoding="utf-8")
        self.app = WebApp(reports_dir=self.tmp / "data" / "reports", base_dir=self.tmp)

    def test_weekly_page(self):
        r = self.app.handle("GET", "/weekly")
        self.assertEqual(r.status, 200)
        body = r.body.decode()
        self.assertIn("AI 行业周报", body)
        self.assertIn("上一周", body)
        self.assertIn("/read/2026-09-02", body)
        self.assertIn("/company/", body)

    def test_weekly_empty_week(self):
        r = self.app.handle("GET", "/weekly?date=2026-01-05")
        self.assertEqual(r.status, 200)
        self.assertIn("无日报数据", r.body.decode())

    def test_weekly_offline_file(self):
        r = self.app.handle("GET", "/file/weekly/2026-08-31/周报_2026-08-31_to_2026-09-06.html")
        self.assertEqual(r.status, 200)
        self.assertIn("text/html", r.content_type)

    def test_weekly_nav_link(self):
        r = self.app.handle("GET", "/")
        self.assertIn("/weekly", r.body.decode())
