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
