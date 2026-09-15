# T-A2 — 今日/最新快捷命令(`ai-daily today/latest`)

> 任务来源:`资深架构师优化建议_产品化.md` §#2 · 批次:1(地基)
> 优先级:P0 · 预估代码量:150~250 行 · 依赖:无

## 任务定义

- **文档来源**:`资深架构师优化建议_产品化.md` §二.2
- **目标**:一行命令打开今天的(或最近的)日报 PDF
- **现状**:要查今天的 PDF 路径 → `ls data/reports/{today}/AI行业...pdf`(文件名长,日期易错)
- **落地后**:
  ```bash
  python main.py today                  # 自动用系统默认 PDF 阅读器打开今天的报告
  python main.py today --open           # 等价于 macOS open / Linux xdg-open
  python main.py latest                 # 打开最近一次产出的 PDF(无论日期)
  python main.py latest --json          # 在终端打印最近一次日报 JSON 摘要
  python main.py latest --stats         # 打印最近一次 runlog 核心数字
  ```

## 涉及文件(必动)

- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/cli/shortcuts.py`(~150 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/tests/test_cli_shortcuts.py`(≥5 个)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/main.py`(注册 `today` / `latest`)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/使用实操文档.md`
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/架构评审与优化计划.md`

## 落地步骤

1. **辅助函数**(`shortcuts.py`):
   - `find_today_report() -> Path | None`:按 `datetime.now().strftime("%Y-%m-%d")` 找 `data/reports/{today}/daily_*.pdf`
   - `find_latest_report() -> Path | None`:遍历 `data/reports/*/daily_*.pdf`,按 mtime 排,取最新
   - `open_with_default_app(path)`:macOS `open`、Linux `xdg-open`、Windows `start`,异常捕获
2. **`today` 子命令**:
   - 默认:终端打印 PDF 路径
   - `--open`:调用 `open_with_default_app`
3. **`latest` 子命令**:
   - 默认:打开最近一日
   - `--json`:加载 `daily_*.json`,按 section/limit 打印摘要
   - `--stats`:加载最近一次 `run_*.json`,打印 文章数/事件数/耗时/LLM 调用数
4. **兜底**:无任何日报 → 友好提示"还没有日报产出,跑一次 run_daily.py --full 试试",退出码 0
5. **测试**(≥5 个):
   - 无今日 → fallback 到 latest
   - 无任何 → 友好提示
   - today --open mock 调用
   - latest --json 结构正确
   - latest --stats 数字合理
6. **commit**:`feat(T-A2): today/latest 快捷命令`

## 验收清单

- [ ] `python main.py today` 健全环境打印今日 PDF 路径 + (可选)打开
- [ ] 无今日 → fallback 到 latest,打印最近一日
- [ ] `python main.py latest --json` 终端打印日报 JSON(标题+前 N 个 events)
- [ ] `python main.py latest --stats` 打印核心数字
- [ ] 无任何日报 → 友好提示 + 退出码 0
- [ ] pytest 全绿(123 + ≥5 个)
- [ ] 使用实操文档.md 加 §"快捷命令"
- [ ] 架构评审与优化计划.md 追加
- [ ] commit:`feat(T-A2): today/latest 快捷命令`
- [ ] log 完整

## 禁止项

- 不要碰 data/reports 历史日报
- 不要新增依赖
- 不要自动 push

## 失败处理

- 验收不过 → log 留痕,不 commit

## 完成后输出

```
=== T-A2 Report ===
diff stat: ...
pytest 末 30 行: ...
commit hash: ...
总结: <1 句话>
```
