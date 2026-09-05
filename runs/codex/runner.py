#!/usr/bin/env python3
"""
第 11 批 codex 长任务执行器（串行 + 状态机 + 断点续传）

用法:
  python3 runs/codex/runner.py               # 跑全部 pending 任务（按批次顺序）
  python3 runs/codex/runner.py --only T11-P0 # 只跑单个任务
  python3 runs/codex/runner.py --batch 1     # 只跑某批次

状态: runs/codex/state.json (单一事实源)
日志: runs/codex/<ts>/<TASK_ID>.log
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path("/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报")
STATE = ROOT / "runs/codex/state.json"
TASK_DIR = ROOT / "prompts/tasks"
LOG_ROOT = ROOT / "runs/codex"
CODEX = shutil.which("codex") or "/opt/homebrew/bin/codex"
TEST_PY = "/opt/homebrew/bin/python3.12"


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8"))


def save_state(state: dict):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def pending_tasks(state: dict, only: str | None, batch: int | None) -> list[str]:
    order: list[str] = []
    for bid in sorted(state["batches"], key=int):
        if batch is not None and int(bid) != batch:
            continue
        for tid in state["batches"][bid]:
            order.append(tid)
    if only:
        return [t for t in order if t == only]
    return [t for t in order if state["tasks"][t]["status"] == "pending"]


def last_commit() -> str:
    r = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %s"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def run_one(state: dict, tid: str) -> bool:
    task = state["tasks"][tid]
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = LOG_ROOT / ts
    log_dir.mkdir(parents=True, exist_ok=True)
    logf = log_dir / f"{tid}.log"
    prompt_file = TASK_DIR / f"{tid}.md"

    if not prompt_file.exists():
        log(f"✗ {tid}: 缺少提示词文件 {prompt_file}")
        task["status"] = "failed"
        task["last_log"] = str(logf)
        return False

    # 标记 running
    task["status"] = "running"
    task["started_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    log(f"▶ {tid} 开始执行 → {logf}")

    cmd = [
        CODEX, "exec",
        "--approve-for-me",   # 隐含 workspace-write 沙箱；不可与 --sandbox 同用
        "--cd", str(ROOT),
        "--output-last-message", str(logf),
        prompt_file.read_text(encoding="utf-8"),
    ]
    try:
        # stdin=DEVNULL 是关键：codex exec 在 stdin 未关闭时会阻塞等待额外输入
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=3600 * 4)
        with logf.open("a", encoding="utf-8") as f:
            f.write("\n=== CODEX STDOUT (tail) ===\n" + proc.stdout[-3000:] + "\n")
            f.write("=== CODEX STDERR (tail) ===\n" + proc.stderr[-2000:] + "\n")
            f.write(f"=== exit={proc.returncode} ===\n")
        commit = last_commit()
        task["last_log"] = str(logf)
        task["last_commit"] = commit
        task["finished_at"] = datetime.now().isoformat(timespec="seconds")
        if proc.returncode == 0:
            task["status"] = "done"
            log(f"✓ {tid} done (commit: {commit})")
            return True
        task["status"] = "failed"
        task["attempt"] += 1
        log(f"✗ {tid} failed (exit={proc.returncode}), 见 {logf}")
        return False
    except subprocess.TimeoutExpired:
        task["status"] = "failed"
        task["attempt"] += 1
        log(f"✗ {tid} 超时, 见 {logf}")
        return False
    finally:
        save_state(state)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--batch", type=int, default=None)
    args = ap.parse_args()

    state = load_state()
    tasks = pending_tasks(state, args.only, args.batch)
    if not tasks:
        log("无 pending 任务（或已全部完成）。")
        return

    consecutive_fails = 0
    for tid in tasks:
        ok = run_one(state, tid)
        consecutive_fails = 0 if ok else consecutive_fails + 1
        if consecutive_fails >= 2:
            log("连续 2 个任务失败，停止后续任务，等待人工介入。")
            break

    log("=== 汇总 ===")
    state = load_state()
    for bid in sorted(state["batches"], key=int):
        for tid in state["batches"][bid]:
            t = state["tasks"][tid]
            log(f"  {tid:8s} {t['status']:8s} attempt={t['attempt']} commit={t['last_commit'] or '-'}")


if __name__ == "__main__":
    main()
