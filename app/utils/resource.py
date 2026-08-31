"""
资源监控与并发动态调整（无第三方依赖）

根据系统负载（CPU 负载均值 / 可选内存压力）动态给出采集、分析、原文提取
三类并发度，避免在高负载时把机器打满、在低负载时浪费空闲算力。

负载优先用标准库：
- ``os.getloadavg`` 返回 1/5/15 分钟平均就绪进程数（Unix/macOS/Linux 可用）；
- 用 ``load1 / os.cpu_count()`` 归一化成 0~1+ 的负载率。
若安装了 ``psutil`` 则额外纳入内存压力；没有时退化为纯负载判断。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ConcurrencySettings:
    """某一时刻建议的并发度。"""
    collector: int
    analyzer: int
    extract: int

    def as_dict(self) -> dict[str, int]:
        return {"collector": self.collector, "analyzer": self.analyzer, "extract": self.extract}


class ResourceOptimizer:
    """根据系统负载动态调整并发度。"""

    # 负载率阈值：>high 降并发，<low 升并发
    HIGH_LOAD = 0.8
    LOW_LOAD = 0.3

    def __init__(
        self,
        collector_max_workers: int = 5,
        analyzer_max_workers: int = 3,
        extract_max_workers: int = 4,
        collector_cap: int = 10,
        analyzer_cap: int = 8,
        extract_cap: int = 6,
    ) -> None:
        self.base = ConcurrencySettings(
            collector=collector_max_workers,
            analyzer=analyzer_max_workers,
            extract=extract_max_workers,
        )
        self.cap = ConcurrencySettings(
            collector=collector_cap,
            analyzer=analyzer_cap,
            extract=extract_cap,
        )

    @classmethod
    def from_config(cls) -> "ResourceOptimizer":
        """从全局并发配置构造（配置未初始化时用默认值）。"""
        from app.config import get_concurrency_config
        cfg = get_concurrency_config()
        return cls(
            collector_max_workers=cfg.collector_max_workers,
            analyzer_max_workers=cfg.analyzer_max_workers,
            extract_max_workers=cfg.extract_max_workers,
            collector_cap=max(10, cfg.collector_max_workers * 2),
            analyzer_cap=max(8, cfg.analyzer_max_workers * 2),
            extract_cap=max(6, cfg.extract_max_workers * 2),
        )

    # ── 负载测量 ──────────────────────────────────────

    @staticmethod
    def cpu_load_ratio() -> Optional[float]:
        """1 分钟负载率 = load1 / CPU 核数；不支持的平台返回 None。"""
        try:
            load1, _load5, _load15 = os.getloadavg()
        except (OSError, AttributeError):
            return None
        cpus = os.cpu_count() or 1
        return load1 / cpus

    @staticmethod
    def memory_pressure() -> Optional[float]:
        """内存压力 0~1（已用比例）；仅在安装了 psutil 时可用，否则返回 None。"""
        try:
            import psutil  # type: ignore
        except ImportError:
            return None
        try:
            return psutil.virtual_memory().percent / 100.0
        except Exception:
            return None

    def system_load(self) -> float:
        """综合负载率：取 CPU 负载率与内存压力的较大值；都不可用时返回中性值 0.5。"""
        samples = [x for x in (self.cpu_load_ratio(), self.memory_pressure()) if x is not None]
        if not samples:
            return 0.5
        return max(samples)

    # ── 并发决策 ──────────────────────────────────────

    @staticmethod
    def _scale_down(value: int) -> int:
        return max(1, value - 1 if value <= 3 else value - 2)

    @staticmethod
    def _scale_up(value: int, cap: int) -> int:
        return min(cap, value + 1 if value >= 4 else value + 2)

    def recommend(self, load_ratio: Optional[float] = None) -> ConcurrencySettings:
        """返回当前负载下建议的并发度。

        Args:
            load_ratio: 显式指定 0~1+ 的负载率（测试用）；不传则实时测量。
        """
        load = self.system_load() if load_ratio is None else load_ratio

        if load >= self.HIGH_LOAD:
            return ConcurrencySettings(
                collector=self._scale_down(self.base.collector),
                analyzer=self._scale_down(self.base.analyzer),
                extract=self._scale_down(self.base.extract),
            )
        if load <= self.LOW_LOAD:
            return ConcurrencySettings(
                collector=self._scale_up(self.base.collector, self.cap.collector),
                analyzer=self._scale_up(self.base.analyzer, self.cap.analyzer),
                extract=self._scale_up(self.base.extract, self.cap.extract),
            )
        return self.base
