"""
一行健康检查（建议 #3 · T-A3）
=================================================
``python main.py doctor`` 自检整个系统是否可跑，主动给出修复建议。

设计：每个检查项返回 :class:`CheckResult`，纯函数、可注入环境与目录，
便于单测 mock；CLI 层负责打印与退出码。
  - error：阻断性问题（缺 key / 缺 playwright），退出码 1
  - warn ：非阻断（未配降级 LLM、近期无产出），退出码 0
  - ok   ：正常
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app.storage.report_store import ReportStore
from app.utils.timeutil import report_now

OK, WARN, ERROR = "ok", "warn", "error"

ICON = {OK: "✅", WARN: "⚠️ ", ERROR: "❌"}


@dataclass
class CheckResult:
    name: str
    level: str
    message: str
    fix: str | None = None

    @property
    def ok(self) -> bool:
        return self.level != ERROR


def _check_python(min_version: tuple[int, int] = (3, 10)) -> CheckResult:
    cur = sys.version_info[:2]
    if cur >= min_version:
        return CheckResult("Python 版本", OK, f"Python {platform.python_version()}（需要 ≥{min_version[0]}.{min_version[1]}）")
    return CheckResult("Python 版本", ERROR,
                       f"Python {platform.python_version()} 过低",
                       f"升级到 Python {min_version[0]}.{min_version[1]}+")


def _check_env_key(env: dict[str, str], env_path: Path) -> CheckResult:
    key = env.get("ANYSEARCH_API_KEY", "")
    if key and not key.endswith("your_key_here") and len(key) > 8:
        return CheckResult("搜索 API Key", OK, "ANYSEARCH_API_KEY 已配置")
    if not env_path.exists():
        return CheckResult("搜索 API Key", ERROR, "未找到 .env 文件",
                           "复制 .env.example 为 .env 并填入 ANYSEARCH_API_KEY")
    return CheckResult("搜索 API Key", ERROR, "ANYSEARCH_API_KEY 为空或仍是占位符",
                       "编辑 .env，填入有效的 AnySearch API Key")


def _check_llm(env: dict[str, str]) -> CheckResult:
    has_ark = bool(env.get("ARK_API_KEY"))
    has_openai = bool(env.get("OPENAI_API_KEY"))
    if has_ark and has_openai:
        return CheckResult("LLM 配置", OK, "ARK 与 OpenAI 双配置（可互为降级）")
    if has_ark:
        return CheckResult("LLM 配置", WARN, "仅配置 ARK_API_KEY，未配 OPENAI_API_KEY",
                           "建议同时配置两组 LLM，故障时可自动降级")
    if has_openai:
        return CheckResult("LLM 配置", WARN, "仅配置 OPENAI_API_KEY，未配 ARK_API_KEY",
                           "建议同时配置两组 LLM，故障时可自动降级")
    return CheckResult("LLM 配置", ERROR, "未配置任何 LLM（ARK_API_KEY / OPENAI_API_KEY）",
                       "在 .env 中配置 ARK_API_KEY 或 OPENAI_API_KEY")


def _check_playwright() -> CheckResult:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return CheckResult("Playwright", ERROR, "playwright 未安装",
                           "pip install playwright && playwright install chromium")
    try:
        with sync_playwright() as p:
            exe = Path(p.chromium.executable_path)
        if exe.exists():
            return CheckResult("Playwright", OK, "playwright 已安装，chromium 已下载")
        return CheckResult("Playwright", ERROR, "playwright 已安装但 chromium 未下载",
                           "运行 playwright install chromium")
    except Exception as e:
        return CheckResult("Playwright", WARN, f"chromium 探测失败: {type(e).__name__}",
                           "运行 playwright install chromium")


def _check_writable(path: Path, name: str) -> CheckResult:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return CheckResult(f"{name} 写权限", OK, f"{path} 可写")
    except Exception as e:
        return CheckResult(f"{name} 写权限", ERROR, f"{path} 不可写: {e}",
                           f"检查目录权限：chmod -R u+w {path}")


def _check_recent_output(store: ReportStore, days: int = 7) -> list[CheckResult]:
    cutoff = (report_now() - timedelta(days=days)).date().isoformat()
    dates = [d for d in store.report_dates() if d >= cutoff]
    if dates:
        return [CheckResult("近期产出", OK, f"最近 {days} 天有 {len(dates)} 天产出日报（最新 {dates[-1]}）")]
    total = len(store)
    if total == 0:
        return [CheckResult("近期产出", WARN, f"最近 {days} 天无日报，且历史库为空",
                            "运行 python run_daily.py --test 生成首份日报")]
    return [CheckResult("近期产出", WARN, f"最近 {days} 天无新日报（历史 {total} 份）",
                        "检查 cron / launchd 定时任务是否正常")]


def _check_runlog_health(store: ReportStore, days: int = 7, min_rate: float = 0.8) -> CheckResult:
    cutoff = (report_now() - timedelta(days=days)).date().isoformat()
    recent = [(d, rl) for d, rl in store.all_runlogs() if d >= cutoff]
    if not recent:
        return CheckResult("运行成功率", WARN, f"最近 {days} 天无运行报告（run_*.json）",
                           "跑一次 run_daily 后即有运行数据")
    ok = sum(1 for _, rl in recent if rl.get("success"))
    rate = ok / len(recent)
    if rate >= min_rate:
        return CheckResult("运行成功率", OK, f"最近 {days} 天 {ok}/{len(recent)} 次成功（{rate:.0%}）")
    return CheckResult("运行成功率", ERROR,
                       f"最近 {days} 天成功率 {ok}/{len(recent)}（{rate:.0%}）低于 {min_rate:.0%}",
                       "查看 data/reports/{date}/run_*.json 的 flags 字段定位失败阶段")


def _check_optional_services(env: dict[str, str]) -> list[CheckResult]:
    out: list[CheckResult] = []
    if not env.get("TAVILY_API_KEY"):
        out.append(CheckResult("Tavily 补充搜索", WARN, "未配置 TAVILY_API_KEY，补充搜索将自动跳过（无影响）",
                               "需要补充信源时在 .env 配置 TAVILY_API_KEY"))
    if not env.get("ALERT_WEBHOOK_URL"):
        out.append(CheckResult("告警 Webhook", WARN, "未配置 ALERT_WEBHOOK_URL，失败告警将静默跳过",
                               "需要钉钉/企微通知时配置 ALERT_WEBHOOK_URL"))
    return out


def run_checks(base_dir: str | Path = ".", env: dict[str, str] | None = None,
               playwright_probe: Callable[[], CheckResult] | None = None) -> list[CheckResult]:
    """执行全部自检，返回检查结果列表。"""
    base = Path(base_dir)
    env = env if env is not None else dict(os.environ)
    store = ReportStore(base / "data" / "reports")

    results: list[CheckResult] = []
    results.append(_check_python())
    results.append(_check_env_key(env, base / ".env"))
    results.append(_check_llm(env))
    results.append((playwright_probe or _check_playwright)())
    results.append(_check_writable(base / "data" / "cache", "缓存目录"))
    results.append(_check_writable(base / "logs", "日志目录"))
    results.extend(_check_recent_output(store))
    results.append(_check_runlog_health(store))
    results.extend(_check_optional_services(env))
    return results


def format_report(results: list[CheckResult]) -> str:
    lines = ["=" * 56, "  AI 财经日报 · 健康检查 (doctor)", "=" * 56]
    for r in results:
        lines.append(f"{ICON.get(r.level, '?')} {r.name}: {r.message}")
        if r.fix:
            lines.append(f"     → {r.fix}")
    errors = [r for r in results if r.level == ERROR]
    warns = [r for r in results if r.level == WARN]
    lines.append("─" * 56)
    if errors:
        lines.append(f"总评: 异常 ✗（{len(errors)} 个错误，{len(warns)} 个警告）")
    elif warns:
        lines.append(f"总评: 基本可用 ⚠（{len(warns)} 个警告，不阻断运行）")
    else:
        lines.append("总评: 健康 ✓")
    return "\n".join(lines)


def cmd_doctor(args, base_dir: str | Path = ".") -> int:
    results = run_checks(base_dir=base_dir)
    print(format_report(results))
    return 1 if any(r.level == ERROR for r in results) else 0
