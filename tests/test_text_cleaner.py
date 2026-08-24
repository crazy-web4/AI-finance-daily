"""清洗层测试（架构评审第二轮 P0 回归防护）"""
import unittest

import _path  # noqa: F401
from app.utils.text_cleaner import (
    clean_full,
    clean_watermark_digits,
    complete_title,
    fix_broken_words,
    safe_render_clean,
)


class TestNoneSafety(unittest.TestCase):
    def test_all_none_safe(self):
        self.assertEqual(clean_full(None), "")
        self.assertEqual(safe_render_clean(None), "")
        self.assertEqual(complete_title(None), "")
        self.assertEqual(fix_broken_words(None), "")
        self.assertEqual(clean_watermark_digits(None), "")


class TestNoContentCorruption(unittest.TestCase):
    """P0-2/P0-3 回归: 合法内容不得被改写"""

    def test_series_a_preserved(self):
        s = "公司完成 Series A 轮融资，估值翻倍"
        self.assertEqual(clean_full(s), s)
        self.assertEqual(safe_render_clean(s), s)

    def test_grade_a_preserved(self):
        self.assertEqual(clean_full("该模型在 Grade A 评测中领先"), "该模型在 Grade A 评测中领先")

    def test_short_line_digits_preserved(self):
        self.assertEqual(clean_full("评分 9"), "评分 9")
        self.assertEqual(clean_full("榜单第一是 iPhone 1"), "榜单第一是 iPhone 1")

    def test_amounts_preserved(self):
        s = "本轮融资 200亿美元，估值 1000亿"
        self.assertEqual(clean_full(s), s)


class TestUpstreamCleaning(unittest.TestCase):
    """上游清洗应去除水印噪声"""

    def test_broken_words(self):
        self.assertEqual(fix_broken_words("Clau de 发布新模型"), "Claude 发布新模型")
        self.assertEqual(safe_render_clean("Op enAI 公告"), "OpenAI 公告")

    def test_watermark_chars_removed(self):
        self.assertEqual(clean_full("OpenAI 广 发布新模型"), "OpenAI 发布新模型")

    def test_long_line_digit_watermark_removed(self):
        long_line = "台积电宣布扩建新厂预计明年投产将带来显著产能提升 9"
        self.assertTrue(clean_full(long_line).endswith("提升"))

    def test_digits_flag_off(self):
        long_line = "台积电宣布扩建新厂预计明年投产将带来显著产能提升 9"
        self.assertTrue(clean_full(long_line, digits=False).endswith("9"))


class TestCompleteTitle(unittest.TestCase):
    def test_trailing_punct(self):
        self.assertEqual(complete_title("OpenAI 发布 GPT-6 ，"), "OpenAI 发布 GPT-6")

    def test_body_mixed_truncated(self):
        # >60 字且含句号 → 截到第一个句号
        t = "OpenAI 发布 GPT-6 模型主打推理能力。" + "这是正文混入标题的后续内容需要被截断" * 2
        self.assertGreater(len(t), 60)
        self.assertTrue(complete_title(t).endswith("。"))
        self.assertNotIn("截断", complete_title(t))

    def test_short_title_with_period_kept(self):
        # <=60 字不截断，避免误伤合法长标题
        t = "OpenAI 发布 GPT-6。官方称推理能力大幅提升"
        self.assertEqual(complete_title(t), t)


if __name__ == "__main__":
    unittest.main()
