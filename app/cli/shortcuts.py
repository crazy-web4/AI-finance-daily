"""
快捷命令（建议 #2 · T-A2）
=================================================
``python main.py today``   打开今天的日报 PDF
``python main.py latest``  打开最近一次日报 PDF
``--json`` 打印日报摘要 / ``--stats`` 打印运行数字 / ``--no-open`` 仅打印路径

逻辑与终端解耦，便于单测：核心函数返回数据结构，CLI 层负责打印/唤起。
"""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.storage.report_store import ReportArtifacts, ReportStore


@dataclass
class ShortcutResult:
    """快捷命令定位结果。"""

    found: bool
    date: Optional[str] = None
    pdf: Optional[Path] = None
    artifacts: Optional[ReportArtifacts] = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "date": self.date,
            "pdf": str(self.pdf) if self.pdf else None,
            "message": self.message,
        }


def locate(store: ReportStore, prefer: str = "today") -> ShortcutResult:
    """
    定位日报。

    prefer="today": 今天有则今天，否则回退最近一天（并在 message 注明回退）。
    prefer="latest": 直接取最近一天。
    无任何日报时返回 found=False（调用方按友好提示处理，退出码 0）。
    """
    if prefer == "today":
        art = store.today()
        if art is not None:
            pdf = art.primary_pdf()
            if pdf is not None:
                return ShortcutResult(True, art.date, pdf, art, "今日报告")
        latest = store.latest()
        if latest is None:
            return ShortcutResult(False, message="暂无任何历史日报，请先运行 python run_daily.py --test")
        pdf = latest.primary_pdf()
        if pdf is None:
            return ShortcutResult(False, message=f"{latest.date} 有日报数据但未找到 PDF（可能用了 --no-pdf）")
        return ShortcutResult(True, latest.date, pdf, latest, f"今日暂无，回退到最近一日 {latest.date}")

    # latest
    art = store.latest()
    if art is None:
        return ShortcutResult(False, message="暂无任何历史日报，请先运行 python run_daily.py --test")
    pdf = art.primary_pdf()
    if pdf is None:
        return ShortcutResult(False, date=art.date, artifacts=art,
                              message=f"{art.date} 有日报数据但未找到 PDF（可能用了 --no-pdf）")
    return ShortcutResult(True, art.date, pdf, art, "最近一次报告")


def open_file(path: Path) -> bool:
    """跨平台用系统默认应用打开文件，返回是否成功唤起。"""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif system == "Windows":
            import os
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception:
        return False


# ── 摘要 / 统计 ────────────────────────────────────────

def report_summary(raw: dict[str, Any], section: str | None = None, limit: int = 10) -> dict[str, Any]:
    """从日报 JSON dict 提取终端友好摘要。"""
    out: dict[str, Any] = {
        "report_id": raw.get("report_id"),
        "report_date": raw.get("report_date"),
        "total_items": raw.get("total_items"),
        "total_word_count": raw.get("total_word_count"),
        "editor_summary": raw.get("editor_summary"),
        "sections": [],
    }
    for sec in raw.get("sections", []):
        sid = sec.get("section_id")
        if section and sid != section:
            continue
        items = []
        for it in sec.get("items", [])[:limit]:
            items.append({
                "rank": it.get("rank"),
                "title": it.get("title"),
                "category": it.get("category"),
                "key_data": it.get("key_data", []),
            })
        out["sections"].append({
            "section_id": sid,
            "section_name": sec.get("section_name"),
            "item_count": sec.get("item_count"),
            "items": items,
        })
    return out


def run_stats(runlog: dict[str, Any] | None) -> dict[str, Any]:
    """从 runlog 提取核心数字。"""
    if not runlog:
        return {"available": False}
    return {
        "available": True,
        "mode": runlog.get("mode"),
        "success": runlog.get("success"),
        "elapsed_sec": runlog.get("elapsed_sec"),
        "articles": runlog.get("articles"),
        "events": runlog.get("events"),
        "stages": runlog.get("stages", {}),
        "llm_calls": (runlog.get("llm_stats") or {}).get("calls"),
        "flags": runlog.get("flags", []),
        "quality_flags": runlog.get("quality_flags", []),
    }


# ── CLI 处理 ──────────────────────────────────────────

def _print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_today(args, store: ReportStore | None = None) -> int:
    store = store or ReportStore()
    res = locate(store, prefer="today")
    if not res.found:
        print(f"ℹ️  {res.message}")
        return 0
    print(f"📰 {res.message}")
    print(f"   日期: {res.date}")
    print(f"   PDF:  {res.pdf}")
    if getattr(args, "json", False):
        raw = store.load_raw(res.date)
        _print_json(report_summary(raw, getattr(args, "section", None), getattr(args, "limit", 10)))
        return 0
    if getattr(args, "stats", False):
        _print_json(run_stats(store.load_runlog(res.date)))
        return 0
    if getattr(args, "open", True) and not getattr(args, "no_open", False):
        if open_file(res.pdf):
            print("   已用默认应用打开")
        else:
            print("   （未能自动打开，请手动复制上面路径）")
    return 0


def cmd_latest(args, store: ReportStore | None = None) -> int:
    store = store or ReportStore()
    res = locate(store, prefer="latest")
    if not res.found:
        print(f"ℹ️  {res.message}")
        return 0
    print(f"📰 {res.message}")
    print(f"   日期: {res.date}")
    print(f"   PDF:  {res.pdf}")
    if getattr(args, "json", False):
        raw = store.load_raw(res.date)
        if raw is None:
            print("   （日报 JSON 不可用）")
        else:
            _print_json(report_summary(raw, getattr(args, "section", None), getattr(args, "limit", 10)))
        return 0
    if getattr(args, "stats", False):
        _print_json(run_stats(store.load_runlog(res.date)))
        return 0
    if getattr(args, "open", True) and not getattr(args, "no_open", False):
        if open_file(res.pdf):
            print("   已用默认应用打开")
        else:
            print("   （未能自动打开，请手动复制上面路径）")
    return 0
