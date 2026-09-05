# Codex 长任务 Prompt 优化指南(跑完《资深架构师优化建议_产品化.md》全部 12 条)

> 目标:让 `codex` 在少则 2 天、多则 1 周的时间窗口内,**稳定、可恢复、可回滚**地依次跑完 12 条建议 + 8 条锦上添花。
> 适用版本:Codex CLI ≥ 0.40.x

---

## 0. 核心矛盾与解题思路

### 0.1 长任务跑 12 条的三大陷阱

| 陷阱 | 后果 |
|---|---|
| **单 prompt 一次塞 12 条** | 上下文爆炸 → 后半段细节丢失、token 超限、codex 自己"跑偏" |
| **裸 `codex exec "把文档全做了"`** | codex 不知道成功标准,会偷工减料、跳过测试、提前 commit |
| **任务间无状态** | 中途断电/失败 → 必须从头来,前面成果丢失 |

### 0.2 解题思路:**三层 prompt + 状态机 + 串行执行器**

```
┌─────────────────────────────────────────────────────────────┐
│  第 1 层:AGENTS.md(站立指令,所有任务都生效)            │
│  ─ 项目禁区 / 跑测约定 / 提交规范 / 失败处理               │
├─────────────────────────────────────────────────────────────┤
│  第 2 层:顶层总 prompt(Orchestrator,只跑一次)        │
│  ─ 全局目标 / 4 批节奏 / 验收口径 / 状态机契约            │
├─────────────────────────────────────────────────────────────┤
│  第 3 层:单任务 prompt(Worker,跑 12 次)               │
│  ─ 单条任务的最小可执行描述,内含验收清单                  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
        ┌──────────────────────────────────┐
        │ runner.sh:串行调度 + 状态写盘        │
        │ 失败重试 + 断点续传 + 报告汇总         │
        └──────────────────────────────────┘
```

---

## 1. 第 1 层:AGENTS.md(站立指令)

**位置**:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/AGENTS.md`
**作用**:codex 每次开新会话自动加载,作为不可违反的边界。

```markdown
# AGENTS.md — AI 财经日报项目 Codex 站立指令

## 项目禁区(绝对不能动)
- 不要自动跑 `deploy` / `push --force` / `rm -rf`
- 不要碰 `data/raw/`、`data/reports/` 下已沉淀的 66 份日报 JSON
- 不要修改 `config/app_config.yaml` 的 `ai` 节(API 配置)
- 不要删除 `tests/conftest.py` / `pytest.ini`
- 不要提交到 `main`,只能在当前 feature 分支

## 必做项(每条任务必须)
1. **必须跑 `pytest -v`** 并贴出末 30 行输出到自己的 run log
2. **必须更新对应文档**:`使用实操文档.md` 加一节、架构评审与优化计划.md 追加批次
3. **必须 commit**,commit 信息格式:`feat(<TASK_ID>): <一句话>` 
4. **必须写到 `runs/codex/<YYYYMMDD-HHMM>/<TASK_ID>.log`** 里,含 diff 摘要 + pytest 结果
5. **必须新建/更新 ≥5 个单测**(已有测覆盖的扩 ≥3 个)

## 工程约定
- Python 3.13 + 标准库优先
- 不要新增 `requirements.txt` 之外的强依赖(可选 Pillow / httpx 已被允许)
- 所有 CLI 命令注册到 `app/cli.py`,统一入口 `ai-daily <subcmd>`
- 测试目录:`tests/test_<module>.py`,命名 `test_xxx_yyy`
- 不要重复造轮子,优先复用 `app/utils/` 下的 `cache`、`alert`、`runlog`、`text_cleaner`

## 失败处理
- 单条任务失败:在 state.json 标 `failed`,**不要自动重试**,把失败原因写到 log
- 连续 2 条失败:停止后续任务,等人工介入
- 遇到歧义:停下,在 log 里写明问题,而不是猜测

## 提交前自检(必跑)
- [ ] pytest -v 全绿
- [ ] 没有 TODO/FIXME 残留
- [ ] 没有 print() 调试残留
- [ ] 新文件有 docstring
- [ ] 文档更新到位
```

---

## 2. 第 2 层:顶层总 prompt(Orchestrator)

**跑法**:只跑一次,让 codex 读文档、建状态机、出调度方案。

```bash
codex exec \
  --sandbox read-only \
  --model gpt-5.6 \
  -o runs/codex/orchestrator.md \
  --json \
  "
你是 AI 财经日报项目的 codex orchestrator。请按以下步骤执行,**只读不写**:

1. 读 README.md、架构评审与优化计划.md、资深架构师优化建议_产品化.md、AGENTS.md
2. 读 .workbuddy/memory/2026-09-05.md(若有)了解上下文
3. 读 pytest.ini、tests/conftest.py、app/ 目录结构
4. 列出《资深架构师优化建议_产品化.md》中全部 12 条建议的 TASK_ID 与依赖关系
5. 输出一份 YAML 状态文件 runs/codex/state.json,字段:
   - tasks: [{id, title, batch, deps:[], status:pending, attempt:0, last_log:null, last_commit:null}]
   - batches: {1:[ids], 2:[ids], 3:[ids], 4:[ids]}
   - 摘要:每条任务的 1 句话目标 + 涉及文件清单
6. 给出**串行执行命令**:`for task in ...; do codex exec ...; done`
7. 列出本次会话**不做任何文件修改**(只读)

输出格式:
- YAML 状态机写到指定文件路径
- 调度命令贴到 stdout
- 最后 30 行:解释为什么按这个顺序(基于依赖图)
"
```

> 这一步**只读**是关键——避免 codex 把"调度"和"执行"混在一起,降低越权风险。

---

## 3. 第 3 层:单任务 prompt(Worker)

**核心原则**:**一条 prompt 只描述一条任务,且必含 5 个固定要素**。

### 3.1 单任务 prompt 五段式模板

```
你是 AI 财经日报项目的 codex worker,任务 ID: <TASK_ID>。

【任务定义】
- 文档来源:资深架构师优化建议_产品化.md §X.Y(<TASK_ID>)
- 目标:<一句话,直接抄文档里的"目标"字段>
- 涉及文件:<列出预计修改/新建的文件路径>

【落地步骤】
1. <步骤 1:具体到操作,例如"在 app/storage/intelligence.py 新增 SQLite + FTS5 封装">
2. <步骤 2>
3. <步骤 3:更新使用实操文档.md 加一节"SQLite 检索">
4. <步骤 4:tests/test_intelligence.py 写 ≥5 个用例>
5. <步骤 5:跑 pytest -v,贴末 30 行>

【验收清单】
- [ ] pytest -v 全绿(贴输出)
- [ ] ≥5 个新单测或 ≥3 个扩测
- [ ] 使用实操文档.md 有对应小节
- [ ] 架构评审与优化计划.md 追加批次记录
- [ ] commit 信息:`feat(<TASK_ID>): <一句话>`
- [ ] runs/codex/<时间戳>/<TASK_ID>.log 完整

【禁止项】
- 不要做本任务之外的事(不要顺手重构)
- 不要跳测、关测
- 不要自动 push

【失败处理】
- 任意验收项不通过 → 不要 commit,把失败原因贴 log 后退出
- 跑不下去 → 在 log 里写明阻塞点,等下一轮

【完成后输出】
- diff stat
- pytest 末 30 行
- commit hash
- 1 句话总结(给 orchestrator 看的)
```

### 3.2 范例:T-C7(SQLite + FTS5)

```bash
codex exec \
  --sandbox workspace-write \
  --ask-for-approval on-request \
  --model gpt-5.6 \
  -o runs/codex/$(date +%Y%m%d-%H%M)-T-C7.log \
  --json \
  "$(cat <<'EOF'
你是 AI 财经日报项目的 codex worker,任务 ID: T-C7。

【任务定义】
- 文档来源:资深架构师优化建议_产品化.md §C.7(SQLite + FTS5)
- 目标:在 app/storage/ 下新增 intelligence.py,封装 SQLite + FTS5,接入日报 JSON 落库与去重,提供 `ai-daily search <keyword> --days 30` CLI
- 涉及文件:
  - 新建: app/storage/__init__.py(若没有)、app/storage/intelligence.py
  - 新建: tests/test_intelligence.py
  - 修改: app/cli.py(注册 search 子命令)、使用实操文档.md、新建 schema 文档

【落地步骤】
1. 在 app/storage/__init__.py 暴露 init_db()、index_report(json_path)、search(query, days)
2. 在 app/storage/intelligence.py 实现:
   - 用 sqlite3 内置 FTS5 虚拟表 `reports_fts(title, summary, key_points, body)`
   - 落库:从 data/reports/*.json 抽取 report_date/title/summary/key_points/body
   - 去重:UNIQUE(report_date) 避免重复落库
   - 检索:`search("OpenAI", days=30)` 返回 [(date, title, snippet), ...]
3. CLI 子命令:python -m app.cli search <keyword> [--days N] [--limit M]
4. 写 ≥5 个单测(空库、1 条、5 条跨日、关键词命中、不命中)
5. 更新使用实操文档.md 加 §5"情报检索"
6. 跑 pytest -v,贴末 30 行

【验收清单】
- [ ] pytest -v 全绿,test_intelligence.py 至少 5 个用例
- [ ] `python -m app.cli search "OpenAI" --days 30` 有真实命中
- [ ] 使用实操文档.md 出现 search 子命令说明
- [ ] commit:`feat(T-C7): sqlite + fts5 全文检索索引日报`
- [ ] runs/codex/<ts>/T-C7.log 完整

【禁止项】
- 不要碰 data/raw、data/reports 已沉淀 JSON
- 不要自动 push
- 不要顺手改 ai 节配置

【失败处理】
- 验收任一不通过 → 不要 commit,贴失败原因退出
- 跑不下去 → 在 log 写阻塞点

【完成后输出】
- diff stat
- pytest 末 30 行
- commit hash
- 1 句话总结
EOF
)"
```

> **关键技巧**:`$(cat <<'EOF' ... EOF)` heredoc 把多行 prompt 直接喂给 codex,避免 shell 转义灾难。

---

## 4. 状态文件 schema(state.json)

**位置**:`runs/codex/state.json`
**作用**:codex 与 runner 共用的"单一事实源",实现断点续传。

```json
{
  "project": "AI财经日报",
  "started_at": "2026-09-05T09:35:00+08:00",
  "batches": {
    "1": ["T-C7", "T-A3", "T-A2", "T-D12"],
    "2": ["T-A1", "T-B4", "T-B6"],
    "3": ["T-C8", "T-C9", "T-D10"],
    "4": ["T-B5", "T-D11"]
  },
  "tasks": {
    "T-C7": {
      "title": "SQLite + FTS5 全文检索",
      "batch": 1,
      "deps": [],
      "status": "pending",
      "attempt": 0,
      "last_log": null,
      "last_commit": null,
      "started_at": null,
      "finished_at": null
    }
  },
  "current_task": null,
  "overall_status": "running"
}
```

**状态机规则**:

| 事件 | status 变更 |
|---|---|
| 开始执行 | `pending` → `running` |
| 验收通过 commit 成功 | `running` → `done` |
| 验收失败 | `running` → `failed` |
| 人工介入后重试 | `failed` → `running`(attempt +1) |
| 跳过(用户决定) | `pending` → `skipped` |

---

## 5. runner.sh:串行执行器

**位置**:`runs/codex/runner.sh`(chmod +x)

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报"
STATE_FILE="$PROJECT_ROOT/runs/codex/state.json"
LOG_DIR="$PROJECT_ROOT/runs/codex/$(date +%Y%m%d-%H%M)"
mkdir -p "$LOG_DIR"

cd "$PROJECT_ROOT"

# 1. 读 state.json,按 batch 顺序跑 pending 任务
TASKS=$(jq -r '
  .batches | to_entries | sort_by(.key) | .[].value[]' "$STATE_FILE" \
  | while read tid; do
      status=$(jq -r --arg t "$tid" '.tasks[$t].status' "$STATE_FILE")
      [ "$status" = "pending" ] && echo "$tid"
    done)

# 2. 依次执行
for TID in $TASKS; do
  echo "==== $TID ===="
  TASK_LOG="$LOG_DIR/$TID.log"

  # 标 running
  jq --arg t "$TID" '.tasks[$t].status="running" | .tasks[$t].started_at=now|todate' \
     "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"

  # 跑 codex exec
  if codex exec \
       --sandbox workspace-write \
       --ask-for-approval on-request \
       --model gpt-5.6 \
       -o "$TASK_LOG" \
       "$(cat prompts/tasks/$TID.md)"; then

    # 验收脚本:读 log 找 commit hash
    COMMIT=$(grep -oE 'commit [0-9a-f]{7,}' "$TASK_LOG" | head -1 | awk '{print $2}')

    jq --arg t "$TID" --arg c "$COMMIT" \
       '.tasks[$t].status="done" | .tasks[$t].last_log=$LOG_DIR | .tasks[$t].last_commit=$c | .tasks[$t].finished_at=now|todate' \
       --arg LOG_DIR "$TASK_LOG" \
       "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"

    echo "✓ $TID done ($COMMIT)"
  else
    jq --arg t "$TID" \
       '.tasks[$t].status="failed" | .tasks[$t].attempt += 1' \
       "$STATE_FILE" > "$STATE_FILE.tmp" && mv "$STATE_FILE.tmp" "$STATE_FILE"
    echo "✗ $TID failed — see $TASK_LOG"
  fi
done

echo "=== Summary ==="
jq '.tasks | to_entries | map({id:.key, status:.value.status, attempt:.value.attempt})' "$STATE_FILE"
```

---

## 6. 断点续传 + 失败重试

### 6.1 续跑(中途断电后)

```bash
# 直接重跑 runner.sh,它会跳过 done/failed 任务,继续 pending
bash runs/codex/runner.sh
```

### 6.2 单条重试(失败后)

```bash
# 把状态打回 pending
jq --arg t "T-C7" '.tasks[$t].status="pending"' runs/codex/state.json \
  > /tmp/x.json && mv /tmp/x.json runs/codex/state.json

# 单独跑
codex exec --sandbox workspace-write --ask-for-approval on-request \
  "$(cat prompts/tasks/T-C7.md)"
```

### 6.3 `codex exec resume --last`

如果某条任务 codex 自己断了(超时/上下文满):

```bash
codex exec resume --last "继续完成 T-C7,前面跑了 X、Y,还差 Z"
```

---

## 7. 优化 prompt 的 12 条具体技巧

### 7.1 必须给"绝对路径"
```
❌ 改一下 storage 目录
✅ /Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/storage/intelligence.py
```

### 7.2 必须给"绝对量化指标"
```
❌ 写一些测试
✅ 至少 5 个单测,pytest -v 全绿
```

### 7.3 必须给"完成 = ?"
```
❌ 完成后告诉我
✅ 完成 = pytest 全绿 + commit hash 出现 + diff stat 输出
```

### 7.4 禁止"顺手重构"
```
✅ "只动本任务涉及文件,其他文件一律不改"
```

### 7.5 用 heredoc 喂多行 prompt
```bash
codex exec "$(cat <<'EOF'
多行
内容
EOF
)"
# 注意 'EOF' 加引号,防止变量展开
```

### 7.6 用 `--json` 留痕
```bash
codex exec --json -o task.log ...
# 失败时:jq '.errors' task.log
```

### 7.7 一次只跑 1 个 TASK_ID
```
❌ 把 12 条都做了
✅ T-C7 这一条
```

### 7.8 显式列出依赖关系
```
依赖:无 / 依赖:T-C7 完成后 / 依赖:T-C7、T-A3
```

### 7.9 显式禁用项
```
禁止:不要自动 push、不要删 data/*、不要碰 ai 配置
```

### 7.10 失败兜底
```
跑不下去 → log 里写明阻塞点,不要瞎试
```

### 7.11 让 codex 自己 review
```
完成后跑:codex review --uncommitted,然后把 review 输出贴 log
```

### 7.12 控制上下文大小
- 单 prompt 控制在 **≤ 2K tokens**
- 让 codex 自己读文件,而不是把文件内容塞 prompt

---

## 8. 12 条任务的实际 prompt 范例

我把 12 条建议的 prompt 都生成到 `prompts/tasks/` 下,每条都是一个独立的 `.md` 文件,直接 `cat` 给 codex:

```bash
mkdir -p prompts/tasks

# 批量生成(用上一份文档 + 本指南 §3.2 模板)
# 推荐做法:用 codex 自己生成(给它本指南)
codex exec --sandbox read-only \
  -o prompts/tasks/ALL.md \
  "读《资深架构师优化建议_产品化.md》和本指南 §3.2 模板,
   为 12 条建议各生成一个独立 .md 到 prompts/tasks/<TASK_ID>.md"
```

每条 prompt 文件结构:

```markdown
# T-C7 — SQLite + FTS5 全文检索

## 任务定义
...

## 落地步骤
1. ...
2. ...

## 验收清单
- [ ] ...

## 禁止项
- ...

## 失败处理
- ...

## 完成后输出
- ...
```

---

## 9. 防止长任务失控的 6 道保险

| # | 保险 | 触发条件 | 应对 |
|---|---|---|---|
| ① | 单任务 prompt 自带**禁用清单** | codex 越权动其他文件 | log 里贴违规操作,人工 review |
| ② | `--ask-for-approval on-request` | 任何不在白名单的命令 | 自动弹确认 |
| ③ | runner.sh **状态机** | 中途断电 | state.json 持久化,可续跑 |
| ④ | **连续 2 失败自动停** | 任务连续失败 | runner 退出非 0,等人工 |
| ⑤ | AGENTS.md 写明**commit 边界** | 误推 main | 不在 main 分支 + 不自动 push |
| ⑥ | 每条任务**独立 log + diff** | 出错定位难 | runs/codex/<ts>/<TID>.log 完整 |

---

## 10. 完整流程一览(给团队看的 SOP)

```
Day 0: 准备
  1. 写 AGENTS.md(§1)
  2. codex exec 跑 Orchestrator(§2)→ 生成 state.json
  3. 让 codex 批量生成 12 个 prompt 文件(§8)
  4. codex doctor --summary 自检环境

Day 1-N: 跑第 1 批(地基)
  bash runs/codex/runner.sh  # 自动跑 T-C7/T-A3/T-A2/T-D12
  # 期间人工抽查 logs

Day N+1: 跑第 2 批
  ...(同上)

Day N+5: 跑第 3、4 批

Day N+8: 汇总
  cat runs/codex/STATE_FINAL.md
  评审 codex review --branch main..feature/...
  合主干 / 拆 PR
```

---

## 11. 一页 SOP(贴墙版)

```
# 三层 prompt
AGENTS.md   ← 站立指令(禁区/必做项/失败处理)
总 prompt   ← Orchestrator 只读,建 state.json
任务 prompt ← Worker 单任务五段式

# 串行执行
bash runs/codex/runner.sh

# 续跑 / 重试
bash runs/codex/runner.sh                          # 跳过完成项
jq '.tasks["T-C7"].status="pending"' state.json && \
  codex exec "$(cat prompts/tasks/T-C7.md)"         # 单条重试

# 关键约定
--sandbox workspace-write
--ask-for-approval on-request
--json -o runs/codex/<ts>/<TID>.log
一行 prompt ≤ 2K tokens
一次只跑 1 个 TASK_ID
失败 → log 留痕,人工 review,不自动重试
```

---

## 12. 12 条建议的实际 prompt 速查(便于复制)

> 想偷懒:把每条 TASK_ID 对应的 prompt 用下面的"任务卡速查表"直接拼。

| TASK_ID | 任务一句话 | 依赖 | 关键文件 |
|---|---|---|---|
| T-C7 | SQLite + FTS5 全文检索 | 无 | `app/storage/intelligence.py`、`tests/test_intelligence.py` |
| T-A3 | `ai-daily doctor` 自检 | 无 | `app/cli.py`、`app/utils/doctor.py` |
| T-A2 | `ai-daily today/latest` 快捷命令 | 无 | `app/cli.py` |
| T-D12 | 优雅降级 + 依赖预检 | T-A3 | `app/pipeline/graceful.py` |
| T-A1 | 本地 Web 看板 | T-C7 | `app/web/server.py`、`templates/dashboard.html` |
| T-B4 | 多格式输出(MD/公众号/邮件) | T-C7 | `app/report/formats/` |
| T-B6 | 本地 RSS / Atom Feed | T-C7 | `app/web/feed.py` |
| T-C8 | 跨期对比与趋势 | T-C7 | `app/storage/trends.py` |
| T-C9 | 周报自动聚合 | T-C7、T-C8 | `app/report/weekly.py` |
| T-D10 | 异常告警增强 | T-C7 | `app/utils/alert.py` |
| T-B5 | 衍生卡片图(1080×1080) | T-B4 | `app/report/card.py` |
| T-D11 | 订阅与个性化 | T-C7 | `app/storage/subscription.py` |

把上表 + §3.2 五段式模板组合,就能为每条任务写出 ≥2K tokens 的优质 prompt。

---

> 把这份指南作为 codex 长任务的"宪法",后续每次跑任务前看一眼;prompt 不清晰的任务,不要让 codex 跑。
