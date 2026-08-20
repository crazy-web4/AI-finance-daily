"""
运行报告（架构评审 #16）
每次运行落盘 data/reports/{date}/run_{ts}.json:
  各阶段耗时 / 搜索查询成功率 / 去重与聚类漏斗 / LLM 调用统计 / 质量告警
cron 失败排查与日常质量巡检的机器可读依据。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


class RunReport:
    def __init__(self, mode: str) -> None:
        self.data: dict = {
            "mode": mode,
            "started_at": datetime.now().isoformat(),
            "stages": {},
            "flags": [],
        }
        self._t0 = time.time()
        self._stage_t = time.time()

    def stage(self, name: str) -> None:
        now = time.time()
        self.data["stages"][name] = round(now - self._stage_t, 1)
        self._stage_t = now

    def set(self, key: str, value) -> None:
        self.data[key] = value

    def flag(self, msg: str) -> None:
        self.data["flags"].append(msg)

    def finish(self, out_dir: str | Path, ok: bool = True) -> Path:
        self.data["elapsed_sec"] = round(time.time() - self._t0, 1)
        self.data["finished_at"] = datetime.now().isoformat()
        self.data["success"] = ok
        path = Path(out_dir)
        path.mkdir(parents=True, exist_ok=True)
        f = path / f"run_{int(time.time())}.json"
        f.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return f
