"""资源动态并发调整（app/utils/resource.py）测试。"""

import unittest

from app.utils.resource import ResourceOptimizer, ConcurrencySettings


class TestResourceOptimizer(unittest.TestCase):
    def setUp(self):
        self.opt = ResourceOptimizer(
            collector_max_workers=5,
            analyzer_max_workers=3,
            extract_max_workers=4,
        )

    def test_high_load_scales_down(self):
        s = self.opt.recommend(load_ratio=1.0)
        self.assertLessEqual(s.collector, self.opt.base.collector)
        self.assertLessEqual(s.analyzer, self.opt.base.analyzer)
        self.assertLessEqual(s.extract, self.opt.base.extract)
        # 任何情况下并发度不能跌破 1
        self.assertGreaterEqual(s.collector, 1)
        self.assertGreaterEqual(s.analyzer, 1)
        self.assertGreaterEqual(s.extract, 1)

    def test_low_load_scales_up(self):
        s = self.opt.recommend(load_ratio=0.1)
        self.assertGreaterEqual(s.collector, self.opt.base.collector)
        self.assertGreaterEqual(s.analyzer, self.opt.base.analyzer)
        self.assertGreaterEqual(s.extract, self.opt.base.extract)
        # 不超过上限
        self.assertLessEqual(s.collector, self.opt.cap.collector)
        self.assertLessEqual(s.analyzer, self.opt.cap.analyzer)
        self.assertLessEqual(s.extract, self.opt.cap.extract)

    def test_normal_load_keeps_base(self):
        s = self.opt.recommend(load_ratio=0.5)
        self.assertEqual(s, self.opt.base)

    def test_monotonic_relation(self):
        high = self.opt.recommend(load_ratio=0.95)
        normal = self.opt.recommend(load_ratio=0.5)
        low = self.opt.recommend(load_ratio=0.05)
        self.assertLessEqual(high.collector, normal.collector)
        self.assertLessEqual(normal.collector, low.collector)

    def test_system_load_is_float(self):
        load = self.opt.system_load()
        self.assertIsInstance(load, float)
        self.assertGreaterEqual(load, 0.0)

    def test_cpu_load_ratio(self):
        ratio = ResourceOptimizer.cpu_load_ratio()
        # 不支持时返回 None，否则为非负浮点
        self.assertTrue(ratio is None or ratio >= 0.0)

    def test_from_config(self):
        opt = ResourceOptimizer.from_config()
        self.assertIsInstance(opt, ResourceOptimizer)
        self.assertGreaterEqual(opt.base.collector, 1)

    def test_settings_as_dict(self):
        s = ConcurrencySettings(collector=2, analyzer=1, extract=2)
        self.assertEqual(
            s.as_dict(),
            {"collector": 2, "analyzer": 1, "extract": 2},
        )


if __name__ == "__main__":
    unittest.main()
