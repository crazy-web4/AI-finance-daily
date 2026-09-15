"""测试共用工厂：在临时目录构建合成日报/产物，供多个产品化测试复用。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.models import (
    Category,
    DailyReport,
    ReportItem,
    ReportSection,
    ReportSource,
    ReportKeyData,
)
from app.storage.report_store import ReportStore


def make_item(rank, title, category, details="", companies=None, sources=None):
    srcs = [ReportSource(name=s, url=f"https://{s}.com/") for s in (sources or ["reuters"])]
    return ReportItem(
        item_id=f"item_{rank:03d}",
        event_id=f"evt_{rank:03d}",
        rank=rank,
        category=category,
        title=title,
        key_data=[ReportKeyData(label="融资额", value="10 亿美元")] if category == Category.FUNDING else [],
        details=details or (title + " 的详细内容，包含更多背景信息。"),
        analysis="编辑点评。",
        sources=srcs,
        word_count=len(title) + 20,
    )


def make_report(date="2026-09-01", variant=""):
    """构造一份含 7 栏的合成日报。"""
    specs = [
        (Category.TOP_NEWS, "今日头条", [
            "OpenAI 发布 GPT-5 编码模型",
            "Anthropic 完成 18 亿美元融资",
        ]),
        (Category.MODEL_TECH, "模型发布与技术进展", [
            "Google 发布 Gemini 3.8 Flash 模型",
        ]),
        (Category.FUNDING, "融资与资本动态", [
            "xAI 完成 60 亿美元融资",
            "月之暗面 Moonshot 启动港股 IPO 估值大涨",
        ]),
        (Category.POLICY, "政策与监管", [
            "美司法部表态 AI 训练属合理使用",
        ]),
        (Category.RESEARCH, "学术与研究突破", [
            "UC Berkeley 发布智能体安全研究论文",
        ]),
        (Category.INDUSTRY, "市场与产业动态", [
            "Nvidia 英伟达发布新款算力芯片",
        ]),
        (Category.US_STOCKS, "美股盘前资讯", [
            "美股期货盘前上涨",
        ]),
    ]
    sections = []
    counter = 0
    for cat, name, titles in specs:
        items = []
        for i, t in enumerate(titles, 1):
            counter += 1
            items.append(make_item(i, t, cat))
        sections.append(ReportSection(section_id=cat, section_name=name, item_count=len(items), items=items))
    suffix = f"_{variant}" if variant else ""
    return DailyReport(
        report_id=f"daily_{date.replace('-', '')}{suffix}",
        report_date=date,
        time_window_start=datetime(2026, 9, 1, tzinfo=timezone.utc),
        time_window_end=datetime(2026, 9, 1, 23, tzinfo=timezone.utc),
        total_items=sum(s.item_count for s in sections),
        total_word_count=sum(it.word_count for s in sections for it in s.items),
        editor_summary="今日 AI 领域模型与资本两线提速。",
        sections=sections,
        generated_at=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
    )


def write_report_tree(base: Path, date: str, report: DailyReport | None = None,
                      with_pdf=True, runlog=None, variant="") -> Path:
    """在 base/data/reports/{date} 下写出完整产物，返回日期目录。"""
    report = report or make_report(date, variant=variant)
    d = Path(base) / "data" / "reports" / date
    d.mkdir(parents=True, exist_ok=True)
    name = f"daily_{date}{('_' + variant) if variant else ''}.json"
    (d / name).write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (d / f"report_{date}.html").write_text("<html><body>report</body></html>", encoding="utf-8")
    if with_pdf:
        (d / f"AI行业全球动态日报_{date}@Cyber_Gm.pdf").write_bytes(b"%PDF-1.4 fake")
    if runlog is not None:
        import time
        (d / f"run_{int(time.time() * 1000)}_{date}.json").write_text(
            json.dumps(runlog), encoding="utf-8")
    return d


def make_store(tmp_path: Path, dates=("2026-08-31", "2026-09-01"), runlog_ok=True) -> ReportStore:
    for i, date in enumerate(dates):
        rl = None
        if runlog_ok is not None:
            rl = {"mode": "test", "success": runlog_ok, "elapsed_sec": 100 + i,
                  "articles": 50, "events": 40, "llm_stats": {"calls": 7},
                  "stages": {"collect": 10}, "flags": []}
        write_report_tree(tmp_path, date, runlog=rl)
    return ReportStore(tmp_path / "data" / "reports")
