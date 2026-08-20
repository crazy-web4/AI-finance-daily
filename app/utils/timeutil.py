"""
时间工具（架构评审 #19）
统一报告时区：默认 Asia/Shanghai，可用环境变量 REPORT_TIMEZONE 覆盖。
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo


def report_tz() -> ZoneInfo:
    """报告使用的时区。"""
    return ZoneInfo(os.environ.get("REPORT_TIMEZONE", "Asia/Shanghai"))


def report_now() -> datetime:
    """报告时区下的当前时间。"""
    return datetime.now(report_tz())


def report_today() -> str:
    """报告日期（YYYY-MM-DD，报告时区）。"""
    return report_now().strftime("%Y-%m-%d")


def report_day_start(date_str: str) -> datetime:
    """某报告日期的 00:00（报告时区，带 tzinfo）。"""
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=report_tz())
