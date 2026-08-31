"""事实核查测试（第三轮 P0-3: 数值词边界匹配）"""
import unittest

import _path  # noqa: F401
from app.agents.factcheck import ground_key_data, _numeric_core


class TestNumericCore(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_numeric_core("200亿美元"), "200")
        self.assertEqual(_numeric_core("1.8万亿"), "1.8")
        self.assertEqual(_numeric_core("无数字"), "无数字")


class TestGroundKeyData(unittest.TestCase):
    SRC = "公司融资1200亿元，估值达到45 billion，2026年3月发布。"

    def test_exact_value_kept(self):
        kd = [{"label": "融资额", "value": "1200亿元"}]
        grounded, dropped = ground_key_data(kd, self.SRC)
        self.assertEqual(len(grounded), 1)
        self.assertEqual(dropped, [])

    def test_substring_penetration_blocked(self):
        """P0-3: '200' 不得命中 '1200'"""
        kd = [{"label": "融资额", "value": "200亿美元"}]
        grounded, dropped = ground_key_data(kd, self.SRC)
        self.assertEqual(grounded, [])
        self.assertEqual(len(dropped), 1)

    def test_year_prefix_not_hit(self):
        """P0-3: '005' 不得命中 '2026年' 的子串幻觉场景"""
        kd = [{"label": "时间", "value": "005年"}]
        grounded, dropped = ground_key_data(kd, self.SRC)
        self.assertEqual(grounded, [])

    def test_empty_key_data(self):
        grounded, dropped = ground_key_data([], self.SRC)
        self.assertEqual((grounded, dropped), ([], []))

    def test_non_dict_skipped(self):
        grounded, dropped = ground_key_data(["not a dict", None], self.SRC)
        self.assertEqual((grounded, dropped), ([], []))


if __name__ == "__main__":
    unittest.main()
