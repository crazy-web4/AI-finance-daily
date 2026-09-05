# AGENTS.md — AI 财经日报 · 协作约定

面向在本仓库工作的 codex / agent / 人。核心目标：基线可回滚、环境可复现、每批可验证。

## 单一 Python 解释器（强制）

项目锁定 **Python 3.12**，统一使用项目内虚拟环境 `.venv`，避免多解释器依赖漂移
（历史踩坑：`playwright` 装在 3.14、`pytest` 装在 homebrew 3.12，而 PATH 上的
`python3.12` 又命中一个无依赖的 uv 裸解释器，导致 `python3.12 -m pytest` 直接
`ModuleNotFoundError`，以及跑完 40 分钟才在 PDF 阶段崩）。

首次初始化（或依赖变更后）：

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/playwright install chromium      # 仅 PDF 需要，可选
```

日常统一用 `.venv/bin/python`（或先 `source .venv/bin/activate`）。**不要**直接用
PATH 上的 `python3` / `python3.12`，那可能是另一个没装依赖的解释器。装包永远用
`"<当前解释器>" -m pip install ...`，不要用裸 `pip`，以免装错解释器。

健康自检：`.venv/bin/python main.py doctor` 会校验解释器/venv、运行依赖、测试依赖
(pytest)、playwright/chromium 等，缺失时给出可直接执行的修复命令。

## 双验证约定（每批落地后强制）

每一批 codex 改动提交后，必须在**同一解释器**（`.venv`）下跑通两项，缺一不可：

1. **单元测试全绿**：`.venv/bin/python -m pytest -q`
   - 必须全绿；新增功能需在对应 `tests/test_*.py` 补测试。
2. **真实链路跑通**：`.venv/bin/python run_daily.py --test`
   - 采集→分析→渲染→导出端到端跑通；playwright/chromium 缺失时会在**启动预检**阶段
     就告警并降级为 HTML+Markdown（非崩溃），此时需在 run log 明确记录“PDF 降级”，
     并确认其余产物正常。

两项都过，方可进入下一批；任一失败，先修复或在 log 留痕，不得带病提交。

## 提交与安全边界

- 一个批次一个聚焦 commit，message 形如 `feat(T11-xx): ...` / `fix(...): ...`。
- **不要** `git push`（除非用户显式要求）；**不要**删除 `data/` 下任何产物。
- 依赖变更同步更新 `requirements.txt`（锁版本）。
- `.venv/`、`data/`、`logs/`、`.env` 均已 gitignore，不得提交。
