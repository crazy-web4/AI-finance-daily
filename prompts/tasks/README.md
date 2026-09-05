# Codex 任务 Prompt 索引

> 12 条建议的**完整可直接运行的 prompt**,按批次组织。
> 用法见 §"快速使用"。

## 给所有 T12-* 任务的通用约束（必读，优先级最高）

**唯一测试入口**：本仓库跑单元测试一律用 `scripts/pytest.sh -q`（单测某文件：
`scripts/pytest.sh -q tests/test_xxx.py`）。它等价于 `python -m pytest`，但会先清除
WorkBuddy 沙箱注入的 4 个 `CODEBUDDY_SANDBOX_BROKER_*` 环境变量。**不要**直接跑
`.venv/bin/python -m pytest`。

**环境假象红线（mkdir EEXIST）**：

- 若测试失败项全部为 `PermissionError: EEXIST: file already exists, mkdir '<path>'`，
  这是沙箱 `sitecustomize.py` 劫持 `Path.mkdir()` 造成的**环境假象**，
  **不是项目代码缺陷**（受影响用例约 16 个，集中在 `test_cache.py` /
  `test_analysis_cache.py` / `test_integration.py`）。
- **禁止以任何此类失败为由修改项目源码** —— 尤其不要去"修"本来正确的
  `mkdir(exist_ok=True)` 调用；那会把正确代码改坏，且测试会因环境波动假绿。
- 正确动作：重跑 `scripts/pytest.sh -q`。若 `tests/test_pytest_env.py`
  （环境哨兵）失败，即明确表示运行环境被污染，按 `AGENTS.md`
  「测试环境的已知陷阱」一节处理。
- 真实链路验证仍为 `.venv/bin/python run_daily.py --test`（见 `AGENTS.md`
  「双验证约定」）。

## 文件清单

| # | 文件 | 任务一句话 | 批次 | 依赖 | 预估代码 | 优先级 |
|---|---|---|---|---|---|---|
| 1 | [T-C7.md](./T-C7.md) | SQLite + FTS5 全文检索(情报库地基) | 1 | 无 | 700~900 | P0 |
| 2 | [T-A3.md](./T-A3.md) | `ai-daily doctor` 一行健康检查 | 1 | 无 | 300~400 | P0 |
| 3 | [T-A2.md](./T-A2.md) | `ai-daily today/latest` 快捷命令 | 1 | 无 | 150~250 | P0 |
| 4 | [T-D12.md](./T-D12.md) | 优雅降级与依赖预检 | 1 | T-A3(可选) | 500~700 | P0 |
| 5 | [T-A1.md](./T-A1.md) | 本地 Web 看板(`http://127.0.0.1:8910`) | 2 | 无 | 800~1200 | P0 |
| 6 | [T-B4.md](./T-B4.md) | 多格式输出(MD/公众号/邮件/Notion) | 2 | 无 | 700~900 | P1 |
| 7 | [T-B6.md](./T-B6.md) | 本地 RSS / Atom Feed | 2 | 无 | 200~300 | P1 |
| 8 | [T-C8.md](./T-C8.md) | 跨期对比与趋势 | 3 | **T-C7** | 400~500 | P1 |
| 9 | [T-C9.md](./T-C9.md) | 周报自动聚合 | 3 | **T-C7** | 500~700 | P1 |
| 10 | [T-D10.md](./T-D10.md) | 异常告警增强 | 3 | **T-C7** | 400~600 | P1 |
| 11 | [T-B5.md](./T-B5.md) | 衍生卡片图(1080×1080) | 4 | 无 | 400~500 | P2 |
| 12 | [T-D11.md](./T-D11.md) | 订阅与个性化 | 4 | **T-C7** | 400~600 | P2 |

**合计**:~6,000 行新增代码(主代码 + 测试)

## 第 11 批任务（T11-*，自动化与情报深化）

> 完整设计见 `../资深架构师优化建议_第11批_单体深化.md`。
> 执行器:`runs/codex/runner.py`（状态机 + 断点续传），用法:

```bash
python3 runs/codex/runner.py               # 跑全部 pending（按批次）
python3 runs/codex/runner.py --only T11-P0 # 单任务
python3 runs/codex/runner.py --batch 1     # 单批次
```

| # | 文件 | 任务一句话 | 批次 | 依赖 | 预估代码 | 优先级 |
|---|---|---|---|---|---|---|
| 1 | [T11-P0.md](./T11-P0.md) | 基线固化：提交第10批改动+固定解释器+双验证 | 1 | 无 | 少量 | P0 |
| 2 | [T11-A1.md](./T11-A1.md) | `ai-daily` 统一命令入口 | 1 | T11-P0 | 150~250 | P0 |
| 3 | [T11-A2.md](./T11-A2.md) | 内置定时调度 `ai-daily schedule` | 1 | T11-A1 | 250~400 | P0 |
| 4 | [T11-B1.md](./T11-B1.md) | 公司档案与时间线 `ai-daily company` | 2 | 无 | 300~450 | P0 |
| 5 | [T11-B2.md](./T11-B2.md) | 看板内联 SVG 图表 | 2 | T11-B1 | 250~350 | P1 |
| 6 | [T11-B3.md](./T11-B3.md) | 精选 RSS 源摄入 `ai-daily sources` | 2 | 无 | 250~350 | P1 |
| 7 | [T11-C1.md](./T11-C1.md) | 人工编排覆盖 `ai-daily edit` | 3 | 无 | 350~500 | P1 |
| 8 | [T11-C2.md](./T11-C2.md) | 发布前复核队列 `ai-daily review` | 3 | T11-C1 | 250~350 | P2 |
| 9 | [T11-A3.md](./T11-A3.md) | 漏报补跑 + 成功摘要推送 `ai-daily catchup` | 3 | T11-A1 | 300~400 | P1 |
| 10 | [T11-D1.md](./T11-D1.md) | 3 分钟简报版 `ai-daily brief` | 4 | 无 | 200~300 | P2 |
| 11 | [T11-D2.md](./T11-D2.md) | 公司库管理 `ai-daily companies` | 4 | T11-B1 | 200~300 | P2 |
| 12 | [T11-D3.md](./T11-D3.md) | 数据生命周期治理 `prune/archive/disk` | 4 | 无 | 200~300 | P2 |

> 测试解释器固定为 `/opt/homebrew/bin/python3.12`（已确认 pytest 9.1.1 与全量依赖）。

## 快速使用

### 单条任务(推荐起点)

```bash
cd /Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报

# 先确保 AGENTS.md 已就位(项目根目录)
ls -la AGENTS.md  # 若无则从 codex_长任务_prompt_优化指南.md §1 复制

# 跑 T-C7(SQLite 全文检索)
codex exec \
  --sandbox workspace-write \
  --ask-for-approval on-request \
  --model gpt-5.6 \
  -o runs/codex/$(date +%Y%m%d-%H%M)-T-C7.log \
  --json \
  "$(cat prompts/tasks/T-C7.md)"
```

### 批量跑第 1 批(地基)

```bash
# 先跑无依赖的 4 个 P0
for tid in T-C7 T-A3 T-A2 T-D12; do
  codex exec \
    --sandbox workspace-write \
    --ask-for-approval on-request \
    -o "runs/codex/$(date +%Y%m%d-%H%M)-${tid}.log" \
    "$(cat prompts/tasks/${tid}.md)"
done
```

### 跑后续批次

```bash
# 第 2 批(看板 + 多形态):T-A1、T-B4、T-B6
# 第 3 批(智能 + 沉淀):T-C8、T-C9、T-D10(依赖 T-C7)
# 第 4 批(个性化):T-B5、T-D11(依赖 T-C7)
```

## 每个 prompt 文件的结构(五段式 + 完整约束)

```
1. 任务元信息     任务来源 / 批次 / 优先级 / 依赖 / 预估代码量
2. 任务定义       文档来源 / 目标 / 现状 / 落地后
3. 涉及文件(必动) 绝对路径列表
4. 落地步骤       具体到操作(顺序)
5. 验收清单       可勾选的量化项
6. 禁止项         明确禁用行为
7. 失败处理       不自动重试,留 log 等人工
8. 完成后输出     diff stat + pytest 末 30 行 + commit hash
```

## 串行调度建议

不要一次性跑 12 条 — 上下文会爆炸。**强烈建议分 4 批跑**:

```bash
# 第 1 批(地基,无依赖):D0-D1
for tid in T-C7 T-A3 T-A2 T-D12; do
  bash runs/codex/run-one.sh "$tid"
done

# 第 2 批(看板):D2
for tid in T-A1 T-B4 T-B6; do
  bash runs/codex/run-one.sh "$tid"
done

# 第 3 批(智能):D3(等 T-C7 完成)
for tid in T-C8 T-C9 T-D10; do
  bash runs/codex/run-one.sh "$tid"
done

# 第 4 批(个性化):D4
for tid in T-B5 T-D11; do
  bash runs/codex/run-one.sh "$tid"
done
```

## 故障排查

| 现象 | 处理 |
|---|---|
| T-C8/T-C9/T-D10/T-D11 跑失败 | 检查 T-C7 是否完成(读 data/intel.db) |
| log 里看不到 diff stat | 检查 codex 是否用了 `--json` |
| pytest 部分用例失败 | 看 log 末尾,贴给 codex 让它修 |
| 提交到了 main | 立刻 `git reset` + 重切 feature 分支 |
| codex 自动 push | 改用 `--ask-for-approval on-request` |

## 相关文档

- `../资深架构师优化建议_产品化.md` — 12 条建议的完整设计
- `../Codex_CLI_使用手册_详细命令分类.md` — codex 命令参考
- `../codex_长任务_prompt_优化指南.md` — 三层 prompt 体系 + runner.sh
- `../AGENTS.md` — 站立指令(必先建)
