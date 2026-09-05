"""
报告产物发现与访问（产品化地基 · 第 10 批）
=================================================
统一扫描 ``data/reports/``，为快捷命令 / 健康检查 / Web 看板 /
RSS / SQLite 索引 / 趋势 / 周报等功能提供单一的产物发现入口。

目录约定::

    data/reports/
        {YYYY-MM-DD}/
            daily_{date}[_CyberGm][_变体].json   # 日报数据
            report_{date}[...].html              # HTML 产物
            AI行业全球动态日报_{date}*.pdf        # PDF 产物
            run_{ts}.json                        # 运行报告（可多个）
        *.pdf                                    # 早期散落在根目录的 PDF
        weekly/{week_start}/...                  # 周报（T-C9）

"主报告"判定：优先 ``daily_{date}.json``，其次 ``daily_{date}_CyberGm.json``，
其余带 ``_us`` / ``_中文美股`` / ``_withUS`` 等后缀的视为变体（特刊）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date as date_cls
from pathlib import Path
from typing import Any, Iterator, Optional

from app.utils.timeutil import report_today

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ReportArtifacts:
    """某一日期目录下的全部产物。"""

    date: str
    dir: Path
    daily_json: Optional[Path] = None          # 主报告 JSON
    variant_jsons: list[Path] = field(default_factory=list)
    pdfs: list[Path] = field(default_factory=list)
    htmls: list[Path] = field(default_factory=list)
    runlogs: list[Path] = field(default_factory=list)

    @property
    def has_report(self) -> bool:
        return self.daily_json is not None

    @property
    def has_pdf(self) -> bool:
        return bool(self.pdfs)

    def latest_runlog(self) -> Optional[Path]:
        """该日期最近一次运行报告（按文件名时间戳）。"""
        if not self.runlogs:
            return None
        return sorted(self.runlogs, key=lambda p: p.stem)[-1]

    def primary_pdf(self) -> Optional[Path]:
        """主 PDF：优先非 v2/v3 版本号的基础文件。"""
        if not self.pdfs:
            return None
        base = [p for p in self.pdfs if "_v" not in p.stem]
        return sorted(base or self.pdfs)[-1]


def _is_date_dir(p: Path) -> bool:
    return p.is_dir() and DATE_RE.match(p.name) is not None


def _pick_primary_daily(date: str, files: list[Path]) -> tuple[Optional[Path], list[Path]]:
    """从 daily_*.json 中挑出主报告，其余作为变体。"""
    dailies = [f for f in files if f.name.startswith("daily_") and f.suffix == ".json"]
    if not dailies:
        return None, []
    exact = Path(f"daily_{date}.json")
    cybergm = Path(f"daily_{date}_CyberGm.json")
    primary: Optional[Path] = None
    for cand in dailies:
        if cand.name == exact.name:
            primary = cand
            break
    if primary is None:
        for cand in dailies:
            if cand.name == cybergm.name:
                primary = cand
                break
    if primary is None:
        # 退而求其次：文件名最短的主版本（变体通常后缀更长）
        primary = sorted(dailies, key=lambda p: len(p.name))[0]
    variants = [f for f in dailies if f != primary]
    return primary, variants


class ReportStore:
    """扫描并访问 data/reports 下的历史产物。"""

    def __init__(self, reports_dir: str | Path = "data/reports") -> None:
        self.root = Path(reports_dir)

    # ── 目录扫描 ─────────────────────────────────────

    def date_dirs(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted((p for p in self.root.iterdir() if _is_date_dir(p)), key=lambda p: p.name)

    def dates(self) -> list[str]:
        return [p.name for p in self.date_dirs()]

    def report_dates(self) -> list[str]:
        """有主报告 JSON 的日期（升序）。"""
        return [d for d in self.dates() if self.get(d).has_report]

    def __len__(self) -> int:
        return len(self.report_dates())

    def get(self, date: str) -> ReportArtifacts:
        """读取某日期的产物清单（不解析 JSON 内容）。"""
        d = self.root / date
        art = ReportArtifacts(date=date, dir=d)
        if not d.exists():
            return art
        files = [p for p in d.iterdir() if p.is_file()]
        art.daily_json, art.variant_jsons = _pick_primary_daily(date, files)
        art.pdfs = sorted(p for p in files if p.suffix.lower() == ".pdf")
        art.htmls = sorted(p for p in files if p.suffix.lower() == ".html")
        art.runlogs = sorted(p for p in files if p.name.startswith("run_") and p.suffix == ".json")
        return art

    def iter_reports(self) -> Iterator[ReportArtifacts]:
        for d in self.report_dates():
            yield self.get(d)

    # ── 快捷定位 ─────────────────────────────────────

    def latest(self) -> Optional[ReportArtifacts]:
        """最近一次有日报的日期产物。"""
        dates = self.report_dates()
        if not dates:
            return None
        return self.get(dates[-1])

    def today(self) -> Optional[ReportArtifacts]:
        return self.get(report_today()) if report_today() in self.report_dates() else None

    def latest_or_today(self) -> Optional[ReportArtifacts]:
        """今天有就今天，否则最近一天。"""
        t = self.today()
        return t or self.latest()

    def find_on_date(self, target: str | date_cls) -> Optional[ReportArtifacts]:
        date_str = target if isinstance(target, str) else target.isoformat()
        art = self.get(date_str)
        return art if art.has_report else None

    # ── 内容加载 ─────────────────────────────────────

    def load_raw(self, date: str) -> Optional[dict[str, Any]]:
        """加载主报告 JSON 原始 dict。"""
        art = self.get(date)
        if not art.daily_json:
            return None
        with open(art.daily_json, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_report(self, date: str):
        """加载为 :class:`DailyReport` 模型。"""
        from app.schemas.models import DailyReport

        raw = self.load_raw(date)
        if raw is None:
            return None
        return DailyReport.model_validate(raw)

    def load_runlog(self, date: str) -> Optional[dict[str, Any]]:
        art = self.get(date)
        rl = art.latest_runlog()
        if not rl:
            return None
        with open(rl, "r", encoding="utf-8") as f:
            return json.load(f)

    # ── 健康聚合 ─────────────────────────────────────

    def all_runlogs(self) -> list[tuple[str, dict[str, Any]]]:
        """返回 (date, runlog_dict) 列表，按日期升序。"""
        out: list[tuple[str, dict[str, Any]]] = []
        for d in self.dates():
            rl = self.load_runlog(d)
            if rl is not None:
                out.append((d, rl))
        return out
