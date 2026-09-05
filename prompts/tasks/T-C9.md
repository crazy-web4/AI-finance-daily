# T-C9 — 周报自动聚合(`ai-daily weekly`)

> 任务来源:`资深架构师优化建议_产品化.md` §#9 · 批次:3(智能)
> 优先级:P1 · 预估代码量:500~700 行 · 依赖:**T-C7**

## 任务定义

- **文档来源**:`资深架构师优化建议_产品化.md` §二.9
- **目标**:周日自动生成"本周回顾"——把 7 天日报合并为 1 份周报(深度研究版)
- **现状**:每天出日报,但"一周回顾"需要人肉做
- **落地后**:
  ```bash
  python main.py weekly --week-of 2026-08-31
  # 输出:data/reports/weekly/{week_start}/周报_2026-08-31_to_2026-09-06.pdf
  ```

## 涉及文件(必动)

- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/report/weekly.py`(~400 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/templates/weekly.html`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/templates/css/weekly.css`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/tests/test_weekly.py`(≥5 个)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/main.py`(注册 `weekly` 子命令)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/使用实操文档.md`
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/架构评审与优化计划.md`

## 落地步骤

1. **`weekly.py`**:
   - `load_week(start_date)`:加载本周 7 天 daily JSON(从 `data/reports/{date}/daily_*.json` 或 T-C7 DB)
   - `aggregate_weekly(daily_list)`:
     - 本周总条目数
     - 头条合并去重(同一公司/同一事件合并)
     - 主题热度 TOP 5
     - 公司活跃度 TOP 10
     - 本周关键政策
     - 模型发布时间轴
   - `render_weekly_pdf(weekly_data)`:复用现有 PDFRenderer,传新模板名
2. **`weekly.html`** + **`weekly.css`**:周报版式(类似 daily 但每页聚合 N 天)
3. **CLI**:`python main.py weekly [--week-of YYYY-MM-DD]`(默认本周)
4. **测试**(≥5 个,基于 mock 7 天数据集):
   - 7 天 → 8~15 页 PDF
   - 头条合并去重正确
   - 公司 TOP 10 排序正确
   - 时间轴正确
   - 复用 PDFRenderer(传入新模板名)
5. **commit**:`feat(T-C9): weekly auto-aggregation`

## 验收清单

- [ ] `weekly --week-of 2026-08-31` 跑通,生成 1 份 PDF(8~15 页)
- [ ] 周报内容:本周总条目数 / 头条合并去重 / 主题热度 TOP 5 / 公司活跃度 TOP 10 / 本周关键政策 / 模型发布时间轴
- [ ] 复用现有 PDFRenderer
- [ ] pytest 全绿(123 + ≥5 个)
- [ ] 使用实操文档.md 加 §"周报"
- [ ] 架构评审与优化计划.md 追加
- [ ] commit:`feat(T-C9): weekly auto-aggregation`
- [ ] log 完整

## 禁止项

- 不要重写 PDFRenderer(复用)
- 不要自动 push
- 不要硬依赖第三方模板引擎

## 失败处理

- T-C7 未完成 → log 写明阻塞点
- 验收不过 → log 留痕,不 commit

## 完成后输出

```
=== T-C9 Report ===
diff stat: ...
pytest 末 30 行: ...
commit hash: ...
总结: <1 句话>
```
