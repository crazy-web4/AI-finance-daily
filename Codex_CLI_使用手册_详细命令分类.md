# Codex CLI 使用手册(详细命令分类 + 快速查 prompt)

> OpenAI Codex CLI · 截至 2026-08 的命令与特性完全参考
> 适用版本:`@openai/codex` ≥ 0.40.x
> 配套本项目落地方式:把上一份《资深架构师优化建议_产品化.md》的 12 条建议作为 `codex exec` 任务批量执行

---

## 0. 30 秒速览

| 你想做的事 | 一行命令 |
|---|---|
| 打开交互终端 | `codex` |
| 启动就带一段指令 | `codex "把 auth.py 里所有 try/except 换成结构化日志"` |
| 跑一次就退出(脚本/CI) | `codex exec "重构 utils 目录并跑 pytest"` |
| 跑审计(只读) | `codex exec --sandbox read-only "列出所有 systemd root 单元"` |
| 评审当前 git diff | `codex review --uncommitted` |
| 列出最近会话 | `codex resume` |
| 继续上一次对话 | `codex resume --last` |
| 跑自检 | `codex doctor --summary` |
| 升级 | `codex update` |

---

## 1. 安装与登录

```bash
# 方式 1:官方一键脚本(macOS/Linux)
curl -fsSL https://chatgpt.com/codex/install.sh | sh

# 方式 2:Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1"

# 方式 3:NPM 全局
npm install -g @openai/codex

# 方式 4:Homebrew
brew install --cask codex

# 验证
codex --version
```

登录:

```bash
codex login                  # 浏览器 OAuth
codex login --with-api-key   # 直接喂 API Key(适合 CI)
codex login status           # 查看当前登录状态
codex logout                 # 清除凭证
```

---

## 2. 命令分类(本手册核心)

Codex CLI 命令按**作用域**分成 **6 大类**,理解分类就能瞬间定位命令:

### 2.1 交互类 — 进 TUI

| 命令 | 用途 | 备注 |
|---|---|---|
| `codex` | 启动交互终端 UI | 无参数则进 picker |
| `codex [PROMPT]` | 启动时附带一段初始指令 | 等价于先 `codex` 再粘 prompt |
| `codex --cd <DIR>` | 在指定目录启动 | 适合临时换工作区 |
| `codex --remote ws://host:port` | 远程连 app-server | 需配 token |

### 2.2 任务执行类 — `codex exec`

**最关键的子命令**,所有自动化、CI、cron 都走这一类。

```bash
codex exec "TASK"                          # 跑一次任务,退出
codex exec -s read-only -o /tmp/x.md "..."  # 只读 + 输出到文件
codex exec --json "..."                     # 输出 NDJSON,方便 jq 处理
codex exec -                               # 从 stdin 读 prompt
codex exec resume --last "Fix race"         # 续上次会话
codex exec resume <SESSION_ID> "继续"       # 续指定会话
codex exec fork --last "另一种实现"          # fork 出新会话
```

> **强烈建议**:落地《资深架构师优化建议_产品化.md》时,12 条建议每一条都用 `codex exec` 跑,而不是进 TUI 一条条敲——既能复现又能留痕。

### 2.3 会话管理类 — session 存档/恢复

| 命令 | 用途 |
|---|---|
| `codex resume` | 打开会话选择器(按日期/目录/关键词筛) |
| `codex resume --last` | 直接进最近一次 |
| `codex resume --all` | 不限当前目录,看所有会话 |
| `codex resume <SESSION_ID>` | 精确恢复某个会话 |
| `codex archive <SESSION>` | 归档(不删 transcript) |
| `codex unarchive <SESSION>` | 取消归档 |
| `codex delete <SESSION>` | **永久删除** |
| `codex fork <SESSION>` | fork 出新会话,保留原 |
| `codex apply <TASK_ID>` | 把云端 chat 生成的 diff 应用到本地 |

### 2.4 评审类 — `codex review`

```bash
codex review --uncommitted              # 评审当前未提交变更
codex review --branch main..feature/x   # 评审分支差异
codex review --commit abc123            # 评审指定 commit
codex review "自定义评审标准"            # 自由描述评审维度
```

### 2.5 自检与诊断 — `codex doctor`

```bash
codex doctor            # 完整诊断:安装/配置/认证/运行时/Git/终端
codex doctor --summary  # 简洁汇总 + 计数
codex doctor --json     # 输出 JSON(去敏),便于贴 bug report
```

### 2.6 配置与生态 — MCP / 插件 / 远程

```bash
# MCP
codex mcp list            # 列已配 MCP
codex mcp add <NAME> ...  # 增 MCP server
codex mcp remove <NAME>

# 插件
codex plugin install <PKG>
codex plugin list
codex plugin marketplace ...

# 远程/应用服务器
codex app-server --listen ws://127.0.0.1:4500     # 实验性,本机调试
codex exec-server --listen ws://127.0.0.1:8787    # 实验性,远端 exec
codex remote-control pair                         # 远程配对码
codex agents                                     # 浏览本地 agent 会话
```

### 2.7 其他实用命令

| 命令 | 用途 |
|---|---|
| `codex completion <SHELL>` | 生成 bash/zsh/fish/ps1 补全脚本 |
| `codex features list` | 列特性开关 |
| `codex features enable <F>` | 持久化开启某特性 |
| `codex features disable <F>` | 持久化关闭某特性 |
| `codex sandbox -- <CMD>` | 用 Codex 沙箱跑任意 shell |
| `codex --help` / `-h` | 帮助 |
| `codex --version` | 版本 |

---

## 3. TUI 斜杠命令(`/`)

进入 `codex` 后按 `/` 弹命令面板:

### 3.1 模型与上下文

| 斜杠命令 | 作用 |
|---|---|
| `/status` | **每次开新会话先打这条**:看当前模型、审批策略、可写根、上下文剩余 |
| `/model <name>` | 切换模型(`gpt-5.6`、`o3` 等) |
| `/compact` | 长会话压缩上下文 |
| `/clear` | 清屏开始新对话 |
| `/diff` | 看本次会话所有变更(包括 untracked) |

### 3.2 权限与审批

| 斜杠命令 | 作用 |
|---|---|
| `/approvals` | 切换审批 preset(untrusted/on-request/never) |
| `/permissions` | 调整文件/网络权限 |

### 3.3 工程辅助

| 斜杠命令 | 作用 |
|---|---|
| `/review` | 让 Codex 自己审一遍当前 worktree |
| `/init` | 为项目生成 `AGENTS.md` |
| `/mention <keyword>` | 模糊搜索添加文件/目录到上下文 |
| `/mcp` | 列出已配 MCP 工具 |
| `/apps` | 浏览 ChatGPT 应用连接器 |

### 3.4 历史与会话

| 斜杠命令 | 作用 |
|---|---|
| `/history` | **查看本会话历史 prompt**(见 §6) |
| `/export session.json` | 导出会话为 JSON |
| `/load session.json` | 加载会话 |
| `/undo` | 撤销上一次文件修改 |
| `/feedback` | 向 OpenAI 提交诊断日志 |

### 3.5 退出与账号

| 斜杠命令 | 作用 |
|---|---|
| `/exit` / `/quit` | 退出会话 |
| `/logout` | 清除本地凭证 |
| `/ps` | 看后台任务状态 |

---

## 4. 关键 Flag 速查

### 4.1 全局 Flag

| Flag | 作用 |
|---|---|
| `--cd <DIR>` | 指定工作目录 |
| `--model <NAME>` | 指定模型 |
| `--profile <NAME>` | 加载 `~/.codex/config.toml` 中的 profile |
| `-q` / `--quiet` | 静默模式 |
| `-h` / `--help` | 帮助 |
| `--oss` | 走本地模型(Ollama / LM Studio) |
| `--local-provider <ollama\|lmstudio>` | 本地 provider |
| `--add-dir <DIR>` | 给沙箱额外开可写目录 |
| `--remote ws://...` | 远端连接 app-server |

### 4.2 沙箱模式(`--sandbox` / `-s`)

| 值 | 含义 | 何时用 |
|---|---|---|
| `read-only` | 只能读 | 审计、code review、列文件 |
| `workspace-write` | 当前目录可写 | **日常编码(推荐)** |
| `danger-full-access` | 全开 | **仅在隔离容器/虚拟机里用** |

### 4.3 审批策略(`--ask-for-approval` / `-a`)

| 值 | 含义 |
|---|---|
| `untrusted` | 不安全命令每次弹确认 |
| `on-request` | Codex 自己判断要不要问(**默认推荐**) |
| `never` | 全程不弹 |

### 4.4 `codex exec` 专属

| Flag | 作用 |
|---|---|
| `-o <FILE>` | 把最终响应落到文件 |
| `--json` | 输出 NDJSON(给 jq) |
| `-` | 从 stdin 读 prompt |
| `--skip-git-repo-check` | 允许非 Git 目录运行 |
| `--sandbox <mode>` | 同上 |

### 4.5 危险 Flag(慎用)

```bash
--dangerously-bypass-approvals-and-sandbox   # 别名 --yolo
```

**只在已隔离的容器/虚拟机里用**;在有真实数据的机器上等同于"把根权限交给 AI"。

---

## 5. 配置文件与环境变量

```bash
~/.codex/config.toml     # 主配置
~/.codex/AGENTS.md       # 项目级全局站立指令(可选)
./AGENTS.md              # 项目级站立指令(进 TUI 自动加载)
~/.codex/sessions/       # 所有 transcript JSON
```

常用环境变量:

| 变量 | 用途 |
|---|---|
| `OPENAI_API_KEY` | API Key(给 `codex login --with-api-key`) |
| `CODEX_ACCESS_TOKEN` | 替代 API Key(给 `codex login --with-access-token`) |
| `CODEX_HOME` | 改 home 目录(默认 `~/.codex`) |
| `CODEX_REMOTE_TOKEN` | 远端 app-server token |

---

## 6. 如何快速查看前 10 个 prompt(本手册重点)

这一题**有 5 种解法**,按"快 → 慢、临时 → 永久"排序。挑你顺手的一种。

### 6.1 Ctrl+R 模糊搜(最快,推荐)

在 TUI 输入框里:

```
Ctrl+R   → 输入关键词 → Enter 接受匹配 / Esc 取消
```

- 适合:回想"我上次怎么问的"
- 不离开当前会话
- 支持模糊匹配 prompt 全文

### 6.2 ↑/↓ 浏览输入历史

```
↑   # 上一条 draft
↓   # 下一条
```

- 适合:连续追问,最近几条来回翻
- Codex 会恢复 draft 文本和图片占位符

### 6.3 `/history` 看本会话历史

```
codex> /history
```

- TUI 内置命令
- 仅显示**当前会话**内你发过的 prompt
- 不跨会话

### 6.4 `codex resume` 交互选择器(看会话级 prompt)

```bash
codex resume                # 打开 picker,默认按日期/目录筛
codex resume --all          # 看所有目录
codex resume --last         # 直接进最近一次
```

picker 里:
- 选 1 个会话回车
- 进入会话后用 `↑/↓` 或 `Ctrl+R` 看 prompt 历史

### 6.5 直接读 transcripts JSON(脚本/审计用)

所有会话都持久化在 `~/.codex/sessions/`,**前 10 个 prompt** 一行命令搞定:

```bash
# 列出最近 10 个会话文件
ls -t ~/.codex/sessions/*.json 2>/dev/null | head -10

# 抽出所有会话里的 user prompt,按时间倒序,前 10 条
jq -r '
  select(.role=="user")
  | .content[]?
  | select(.type=="input_text" or .type=="text")
  | .text
' ~/.codex/sessions/*.json 2>/dev/null \
  | grep -v '^$' \
  | tac \
  | head -10
```

更精确:**跨所有会话、最近的 10 条 user prompt**:

```bash
# 取出 (timestamp, prompt) 对,按时间排,前 10
jq -r '
  [.timestamp, (.content[]? | select(.type=="input_text" or .type=="text") | .text)]
  | @tsv
' ~/.codex/sessions/*.json 2>/dev/null \
  | sort -k1 \
  | awk -F'\t' '{print $2}' \
  | grep -v '^$' \
  | tail -10
```

### 6.6 用 `codex exec --json` 实时抓

```bash
codex exec --json "..." 2>&1 \
  | jq -r 'select(.type=="user_prompt") | .text'
```

适合 CI 流水线审计。

### 6.7 5 种方案对照表

| 场景 | 用法 | 速度 | 跨会话 |
|---|---|---|---|
| 回想关键词 | `Ctrl+R` | ⚡⚡⚡ | ✅ |
| 连续追问 | `↑/↓` | ⚡⚡⚡ | ❌ |
| 看本会话全部 | `/history` | ⚡⚡ | ❌ |
| 看会话级摘要 | `codex resume` | ⚡⚡ | ✅ |
| 脚本/审计 | `~/.codex/sessions/*.json` + `jq` | ⚡ | ✅ |

**推荐组合**:日常用 `Ctrl+R` + `↑/↓`;周报/审计时跑 `jq` 那行命令。

---

## 7. 常用工作流(本项目落地模板)

### 7.1 跑一条建议(代码落地单条建议)

```bash
cd /Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报

codex exec \
  --sandbox workspace-write \
  --ask-for-approval on-request \
  "落地《资深架构师优化建议_产品化.md》中任务 T-C7(SQLite + FTS5):
   1) 在 app/storage/ 下新建 intelligence.py,封装 SQLite + FTS5
   2) 接入日报 JSON 落库与去重
   3) 提供 CLI 命令:ai-daily search <keyword> --days 30
   4) 写 ≥5 个单测,跑 pytest 必须全绿
   5) 更新 使用实操文档.md"
```

### 7.2 批量跑 12 条建议

```bash
# 12 条建议串行(顺序有依赖:先 SQLite 后 Web)
for task in T-C7 T-A3 T-A2 T-D12 T-A1 T-B4 T-B6 T-C8 T-C9 T-D10 T-B5 T-D11; do
  codex exec --sandbox workspace-write \
    "从《资深架构师优化建议_产品化.md》取任务 $task,严格按'目标/现状/落地后/关键模块/验收/代码量'6 段实现,
     完成后运行 pytest,全绿才提交。提交信息:feat($task): ..."
done
```

### 7.3 评审本批变更

```bash
codex review --uncommitted
# 或者:
codex review --branch main..feature/sqlite-intel "重点检查 SQLite 索引与 JSON 一致性"
```

### 7.4 跑回归

```bash
codex exec --sandbox read-only "运行 pytest -v 并生成报告,/tmp/report.md"
```

---

## 8. 与本项目对接的速查

| 工作流 | 对应 codex 用法 |
|---|---|
| 把 12 条建议落到代码 | `codex exec` 12 次 |
| 看 codex 都改了啥 | `/diff` 或 `codex review --uncommitted` |
| 中途换人接手 | `codex resume --last` 或 `--all` 找会话 |
| 排查 codex 报错 | `codex doctor --summary` |
| 自动跑审计日报 | `codex exec --sandbox read-only "..."` + cron |
| 检查 prompt 是否重复 | `~/.codex/sessions/*.json` + `jq` |

---

## 9. 风险红线(必须遵守)

1. **生产/有数据机器上禁用 `--yolo`**,只在容器或 VM 用
2. 每次开新会话**先 `/status`**,确认沙箱/审批是你期望的
3. 写 `AGENTS.md` 写明:**"不要自动跑 deploy、不要删 data/、不要碰 .env"**
4. 长时间任务跑 `codex exec` 而不是 TUI,能自动 `--resume`
5. transcript 会写本地,定期归档:`codex archive <SESSION>`

---

## 10. 一页 cheat sheet(可贴墙)

```
# 安装
npm i -g @openai/codex && codex login

# 三种用法
codex                              # 进 TUI
codex "把 auth 重构"                # 进 TUI 带 prompt
codex exec "重构 utils 并跑测试"     # 跑一次退

# 沙箱 + 审批(默认组合)
codex --sandbox workspace-write --ask-for-approval on-request

# 看历史 prompt
Ctrl+R / ↑↓  /history  / ~/.codex/sessions/*.json + jq

# 会话
codex resume / --last / --all / archive / unarchive / delete / fork

# 自检
codex doctor --summary

# 评审
codex review --uncommitted

# 危险区(隔离环境用)
--dangerously-bypass-approvals-and-sandbox   # = --yolo
```

---

> 接下来你可以直接把这份手册交给团队,或者把 12 条建议写成 `codex exec` 任务批量跑。
