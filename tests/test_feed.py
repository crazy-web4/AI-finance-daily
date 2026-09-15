"""RSS/Atom feed 测试（建议 #6 T-B6）"""
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_store
from app.storage.report_store import ReportStore
from app.web.feed import build_rss, build_atom, collect_items


class TestFeed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = make_store(self.tmp, ("2026-08-31", "2026-09-01"))

    def test_rss_wellformed_and_items(self):
        rss = build_rss(self.store)
        root = ET.fromstring(rss)
        items = root.findall("./channel/item")
        self.assertEqual(len(items), 2)
        for it in items:
            self.assertIsNotNone(it.find("title"))
            self.assertIsNotNone(it.find("link"))
            self.assertIsNotNone(it.find("pubDate"))
            self.assertIsNotNone(it.find("description"))
            self.assertIsNotNone(it.find("guid"))

    def test_rss_title_uses_headline(self):
        rss = build_rss(self.store)
        root = ET.fromstring(rss)
        title = root.find("./channel/item/title").text
        self.assertIn("2026-09-01", title)  # 最新在前

    def test_atom_wellformed(self):
        atom = build_atom(self.store)
        root = ET.fromstring(atom)
        ns = "{http://www.w3.org/2005/Atom}"
        entries = root.findall(f"{ns}entry")
        self.assertEqual(len(entries), 2)
        self.assertIsNotNone(root.find(f"{ns}id"))

    def test_collect_newest_first(self):
        items = collect_items(self.store)
        self.assertEqual(items[0]["date"], "2026-09-01")

    def test_empty_feed(self):
        empty = ReportStore(self.tmp / "nope")
        rss = build_rss(empty)
        root = ET.fromstring(rss)
        self.assertEqual(len(root.findall("./channel/item")), 0)
        self.assertIsNotNone(root.find("./channel/title"))

    def test_description_contains_summary(self):
        rss = build_rss(self.store)
        self.assertIn("模型", rss)  # editor_summary / 条目


if __name__ == "__main__":
    unittest.main()
