"""
性能监控模块测试
"""

import unittest
import time
import asyncio

from app.utils.performance import PerformanceMetrics, get_performance_monitor


class TestPerformanceMetrics(unittest.TestCase):
    """性能指标测试"""

    def setUp(self):
        self.metrics = PerformanceMetrics()

    def test_counter(self):
        """测试计数器"""
        self.metrics.record_counter("test.counter", 5)
        stats = self.metrics.get_stats()

        self.assertEqual(stats['counters']['test.counter'], 5)

    def test_gauge(self):
        """测试测量值"""
        self.metrics.record_gauge("test.gauge", 85.5)
        stats = self.metrics.get_stats()

        self.assertEqual(stats['gauges']['test.gauge'], 85.5)

    def test_timing(self):
        """测试耗时记录"""
        start = time.time()
        time.sleep(0.1)
        duration = time.time() - start

        self.metrics.record_timing("test.timing", duration)
        stats = self.metrics.get_stats()

        recorded_duration = stats['performance']['test.timing']['avg']
        self.assertAlmostEqual(recorded_duration, duration, places=2)

    def test_context_manager(self):
        """测试上下文管理器"""
        with self.metrics.measure("test.op"):
            time.sleep(0.05)

        stats = self.metrics.get_stats()
        self.assertIn('test.op', stats['performance'])
        self.assertEqual(stats['performance']['test.op']['count'], 1)

    def test_save_report(self):
        """测试保存报告（写到临时目录，校验 JSON 结构）"""
        import json
        import tempfile
        from pathlib import Path as _Path

        with tempfile.TemporaryDirectory() as tmp:
            report_path = _Path(tmp) / "subdir" / "test_report.json"
            self.metrics.record_counter("test", 10)
            self.metrics.save_report(str(report_path))

            self.assertTrue(report_path.exists())
            data = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIn("stats", data)
            self.assertEqual(data["stats"]["counters"]["test"], 10)


class TestGlobalMonitor(unittest.TestCase):
    """全局监控器测试"""

    def test_global_instance(self):
        """测试全局实例"""
        monitor1 = get_performance_monitor()
        monitor2 = get_performance_monitor()

        self.assertIs(monitor1, monitor2)

    def test_multiple_operations(self):
        """测试多操作记录"""
        monitor = get_performance_monitor()

        # 模拟多个操作
        for i in range(5):
            with monitor.measure(f"op_{i}"):
                time.sleep(0.01)

        stats = monitor.get_stats()

        # 验证所有操作都被记录
        for i in range(5):
            self.assertIn(f"op_{i}", stats['performance'])


if __name__ == '__main__':
    unittest.main()
