"""
性能监控模块
用于记录关键操作的耗时和性能指标
"""

import time
import json
import asyncio
from contextlib import asynccontextmanager, contextmanager
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import threading


class PerformanceMetrics:
    """性能指标收集器"""

    def __init__(self) -> None:
        self.metrics = defaultdict(list)
        self.counters = defaultdict(int)
        self.gauges = defaultdict(float)
        self._lock = threading.Lock()

    def record_counter(self, name: str, value: int = 1) -> None:
        """记录计数器"""
        with self._lock:
            self.counters[name] += value

    def record_gauge(self, name: str, value: float) -> None:
        """记录测量值"""
        with self._lock:
            self.gauges[name] = value

    def record_timing(self, name: str, duration: float) -> None:
        """记录耗时"""
        with self._lock:
            self.metrics[name].append({
                'duration': duration,
                'timestamp': datetime.now().isoformat()
            })

    @contextmanager
    def measure(self, name: str):
        """上下文管理器，测量代码块耗时"""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.record_timing(name, duration)
            self.record_counter(f"{name}_count")

    @asynccontextmanager
    async def async_measure(self, name: str):
        """异步上下文管理器"""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.record_timing(name, duration)
            self.record_counter(f"{name}_count")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {}

        # 计数器
        stats['counters'] = dict(self.counters)

        # 测量值
        stats['gauges'] = dict(self.gauges)

        # 性能指标统计
        perf_stats = {}
        for name, measurements in self.metrics.items():
            if measurements:
                durations = [m['duration'] for m in measurements]
                perf_stats[name] = {
                    'count': len(durations),
                    'total': sum(durations),
                    'avg': sum(durations) / len(durations),
                    'min': min(durations),
                    'max': max(durations),
                    'p95': sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 1 else 0
                }

        stats['performance'] = perf_stats
        return stats

    def save_report(self, filepath: str) -> None:
        """保存性能报告"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'stats': self.get_stats()
        }

        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)


# 全局性能监控实例
performance_monitor = PerformanceMetrics()


def get_performance_monitor() -> PerformanceMetrics:
    """获取全局性能监控实例"""
    return performance_monitor
