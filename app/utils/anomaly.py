"""
异常告警增强（建议 #10 · T-D10）
=================================================
基于 SQLite 索引主动发现异常（不只是失败才告警）：

- ``company_spike``   某公司单日事件数远超周均（突发热点）
- ``topic_drop``      某栏目连续 N 天 0 条（采集/分类异常）
- ``collection_drop`` 今日采集量较昨日骤降（key/网络异常）

规则阈值在 ``config/watch.yaml``，缺省走内置默认。检测为纯函数，
``watch --dry-run`` 只打印不发送。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

from app.storage.db import DEFAULT_DB_PATH, connect

DEFAULT_CONFIG: dict[str, Any] = {
    "company_spike": {"factor": 4.0, "window_days": 7, "min_count": 3},
    "topic_drop": {"consecutive_days": 3},
    "collection_drop": {"ratio": 0.5, "min_baseline": 20},
}


@dataclass
class Anomaly:
    rule: str
    severity: str          # info / warning / error
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def format(self) -> str:
        icon = {"error": "❌", "warning": "⚠️ ", "info": "ℹ️"}.get(self.severity, "📢")
        return f"{icon} [{self.rule}] {self.message}"


def load_watch_config(path: str | Path = "config/watch.yaml") -> dict[str, Any]:
    """加载规则配置，缺失字段用默认补齐。"""
    cfg = {k: dict(v) for k, v in DEFAULT_CONFIG.items()}
    p = Path(path)
    if p.exists():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for k, v in data.items():
                if isinstance(v, dict):
                    cfg.setdefault(k, {}).update(v)
        except Exception:
            pass
    return cfg


def _latest_date(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT MAX(date) d FROM items").fetchone()
    return row["d"] if row and row["d"] else None


def check_company_spike(conn: sqlite3.Connection, cfg: dict[str, Any]) -> list[Anomaly]:
    latest = _latest_date(conn)
    if not latest:
        return []
    factor = float(cfg.get("factor", 4.0))
    window = int(cfg.get("window_days", 7))
    min_count = int(cfg.get("min_count", 3))
    cutoff = (date.fromisoformat(latest) - timedelta(days=window)).isoformat()

    today_rows = conn.execute(
        "SELECT name, COUNT(*) n FROM entities WHERE date=? GROUP BY name", (latest,)
    ).fetchall()
    prior = conn.execute(
        "SELECT name, COUNT(DISTINCT date) days, COUNT(*) n FROM entities "
        "WHERE date >= ? AND date < ? GROUP BY name",
        (cutoff, latest),
    ).fetchall()
    prior_map = {r["name"]: r for r in prior}

    out: list[Anomaly] = []
    for r in today_rows:
        if r["n"] < min_count:
            continue
        p = prior_map.get(r["name"])
        avg = (p["n"] / p["days"]) if p and p["days"] else 0.0
        if avg == 0:
            ratio = float("inf")
        else:
            ratio = r["n"] / avg
        if ratio >= factor:
            out.append(Anomaly(
                rule="company_spike", severity="warning",
                message=f"{r['name']} 单日 {r['n']} 条事件，约为近 {window} 天日均（{avg:.1f}）的 {ratio:.1f} 倍，疑似突发热点",
                context={"company": r["name"], "today": r["n"], "baseline_avg": round(avg, 2), "ratio": round(ratio, 2)},
            ))
    return out


def check_topic_drop(conn: sqlite3.Connection, cfg: dict[str, Any]) -> list[Anomaly]:
    latest = _latest_date(conn)
    if not latest:
        return []
    threshold = int(cfg.get("consecutive_days", 3))
    sections = [r["section_id"] for r in conn.execute(
        "SELECT DISTINCT section_id FROM items WHERE section_id IS NOT NULL"
    ).fetchall()]
    dates = [r["date"] for r in conn.execute("SELECT DISTINCT date FROM items ORDER BY date").fetchall()]
    if latest not in dates:
        return []
    latest_idx = dates.index(latest)

    out: list[Anomaly] = []
    for sid in sections:
        active = {
            r["date"] for r in conn.execute(
                "SELECT DISTINCT date FROM items WHERE section_id=?", (sid,)
            ).fetchall()
        }
        streak = 0
        for i in range(latest_idx, -1, -1):
            if dates[i] in active:
                break
            streak += 1
        if streak >= threshold:
            name_row = conn.execute(
                "SELECT section_name FROM items WHERE section_id=? LIMIT 1", (sid,)
            ).fetchone()
            name = name_row["section_name"] if name_row else sid
            out.append(Anomaly(
                rule="topic_drop", severity="warning",
                message=f"栏目「{name}」已连续 {streak} 天 0 条，疑似采集/分类异常",
                context={"section": sid, "section_name": name, "consecutive_days": streak},
            ))
    return out


def check_collection_drop(runlogs: list[tuple[str, dict[str, Any]]], cfg: dict[str, Any]) -> list[Anomaly]:
    """runlogs: 按日期升序的 (date, runlog_dict)。比较最近两天采集量。"""
    ratio_th = float(cfg.get("ratio", 0.5))
    min_baseline = int(cfg.get("min_baseline", 20))
    dated = [(d, rl.get("articles")) for d, rl in runlogs if isinstance(rl.get("articles"), int)]
    if len(dated) < 2:
        return []
    (_, prev), (d, cur) = dated[-2], dated[-1]
    if not prev or prev < min_baseline:
        return []
    ratio = cur / prev
    if ratio < ratio_th:
        return [Anomaly(
            rule="collection_drop", severity="error",
            message=f"{d} 采集 {cur} 篇，较前一日 {prev} 篇骤降至 {ratio:.0%}（阈值 {ratio_th:.0%}），疑似 key 失效/网络故障",
            context={"date": d, "current": cur, "previous": prev, "ratio": round(ratio, 2)},
        )]
    return []


def run_checks(
    db_path: str | Path = DEFAULT_DB_PATH,
    runlogs: list[tuple[str, dict[str, Any]]] | None = None,
    config_path: str | Path = "config/watch.yaml",
) -> list[Anomaly]:
    cfg = load_watch_config(config_path)
    conn = connect(db_path)
    try:
        anomalies: list[Anomaly] = []
        anomalies.extend(check_company_spike(conn, cfg["company_spike"]))
        anomalies.extend(check_topic_drop(conn, cfg["topic_drop"]))
        if runlogs:
            anomalies.extend(check_collection_drop(runlogs, cfg["collection_drop"]))
        return anomalies
    finally:
        conn.close()


def notify_local(message: str, title: str = "AI 财经日报") -> bool:
    """
    本地桌面通知（macOS osascript / Linux notify-send）。
    无可用通道时静默返回 False，不抛异常。
    """
    import platform
    import shutil
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin" and shutil.which("osascript"):
            safe = message.replace('"', "'")
            subprocess.Popen([
                "osascript", "-e",
                f'display notification "{safe}" with title "{title}"',
            ])
            return True
        if system == "Linux" and shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, message])
            return True
    except Exception:
        return False
    return False
