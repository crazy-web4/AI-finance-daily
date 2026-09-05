"""衍生卡片图测试（建议 #5 T-B5）"""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _factory import make_report
from app.exporter.cards import generate_cards, render_card, wrap_text, CARD_SIZE

from PIL import Image


class _DummyDraw:
    def textlength(self, text, font=None):
        return len(text) * 20  # 每个字符约 20px


class TestCards(unittest.TestCase):
    def setUp(self):
        self.report = make_report("2026-09-01")
        self.tmp = Path(tempfile.mkdtemp())

    def test_generate_top_cards_dimensions(self):
        paths = generate_cards(self.report, self.tmp, style="light", only="top")
        self.assertEqual(len(paths), 2)  # 头条 2 条
        for p in paths:
            im = Image.open(p)
            self.assertEqual(im.size, CARD_SIZE)
            self.assertEqual(im.mode, "RGB")
            self.assertGreater(Path(p).stat().st_size, 1000)

    def test_generate_all_cards(self):
        paths = generate_cards(self.report, self.tmp, style="dark")
        self.assertEqual(len(paths), self.report.total_items)
        # 按栏目分子目录
        subdirs = {p.parent.name for p in paths}
        self.assertIn("top_news", subdirs)

    def test_render_single_card(self):
        out = self.tmp / "single.png"
        render_card("测试标题很长的 OpenAI 发布", "今日头条", "top_news",
                    "2026-09-01", key_data=[{"label": "融资额", "value": "10亿美元"}],
                    body="正文内容", out_path=out)
        self.assertTrue(out.exists())
        self.assertEqual(Image.open(out).size, CARD_SIZE)

    def test_wrap_text_no_long_line(self):
        lines = wrap_text(_DummyDraw(), "OpenAI 发布 GPT-5 模型" * 20, None, max_width=400)
        self.assertGreater(len(lines), 5)
        self.assertTrue(all(len(l) * 20 <= 400 + 60 for l in lines))

    def test_wrap_keeps_latin_word_intact(self):
        # 400px 约可容纳 20 个西文字符，普通单词不会触发硬切，只在词间换行
        lines = wrap_text(_DummyDraw(), "Hugging Face Anthropic OpenAI DeepSeek", None, max_width=400)
        joined = " ".join(lines)
        self.assertIn("Hugging", joined)
        self.assertIn("DeepSeek", joined)


if __name__ == "__main__":
    unittest.main()
