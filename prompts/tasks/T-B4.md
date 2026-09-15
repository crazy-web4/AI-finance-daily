# T-B4 — 多格式输出(`ai-daily export`)

> 任务来源:`资深架构师优化建议_产品化.md` §#4 · 批次:2(看板)
> 优先级:P1 · 预估代码量:700~900 行 · 依赖:无

## 任务定义

- **文档来源**:`资深架构师优化建议_产品化.md` §二.4
- **目标**:一份日报可同时输出 PDF / Markdown / 公众号富文本 / HTML 邮件版 / Notion 导入 JSON
- **现状**:跑完只能拿到 PDF + JSON,JSON 给程序看,人想"二次消费"只能从 PDF 复制
- **落地后**:
  ```bash
  python run_daily.py --full                 # 默认额外输出 MD + 公众号 + 邮件版
  python main.py export --date 2026-09-05 --format markdown
  python main.py export --date 2026-09-05 --format wechat
  python main.py export --date 2026-09-05 --format email
  python main.py export --date 2026-09-05 --format notion
  python main.py export --date 2026-09-05 --all
  ```

## 涉及文件(必动)

- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/exporter/__init__.py`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/exporter/markdown.py`(~100 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/exporter/wechat.py`(~200 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/exporter/email.py`(~150 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/exporter/notion.py`(~150 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/exporter/runner.py`(~80 行,统一调度 + 并发)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/tests/test_exporters.py`(≥5 个)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/main.py`(注册 `export` 子命令)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/run_daily.py`(渲染后自动调用 `run_all_exporters`)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/config/app_config.yaml`(增加 `enabled_exporters` 字段)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/使用实操文档.md`
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/架构评审与优化计划.md`

## 落地步骤

1. **统一接口**:`BaseExporter.export(report_dict, out_dir) -> Path`,每个 exporter 实现
2. **markdown.py**:日报 → 标准 GFM,可被 Typora/VSCode/GitHub 渲染
3. **wechat.py**:日报 → 公众号 HTML(标题 + 封面 + 每事件一段,字号限制内,图片 alt 完整)
4. **email.py**:日报 → 邮件 inline HTML(无外部依赖,inline CSS,Gmail 直发)
5. **notion.py**:日报 → Notion 块 JSON(blocks 数组,可直接 `curl -X POST` 到 Notion API)
6. **runner.py**:用 `concurrent.futures.ThreadPoolExecutor` 并发执行,失败标记但不阻塞 PDF 主流程
7. **CLI**:`python main.py export --date YYYY-MM-DD [--format X | --all]`
8. **配置**:`config.app_config.render.enabled_exporters: [markdown, wechat, email, notion]`,某项关闭 → 不生成
9. **测试**(≥5 个):每种格式 golden sample(用 `tests/golden/` 存期望输出)
10. **commit**:`feat(T-B4): multi-format export (md/wechat/email/notion)`

## 验收清单

- [ ] `--full` 跑完后,`data/reports/{date}/` 下新增 4 个文件:`*.md` / `*_wechat.html` / `*_email.html` / `*_notion.json`
- [ ] Markdown 用标准 GFM,Typora/VSCode 正确渲染
- [ ] 公众号版:每事件独立段落,字号限制内,图片 alt 完整
- [ ] 邮件版:无外部依赖资源,Gmail 直发可用
- [ ] Notion 版:blocks 数组结构正确
- [ ] 关闭某 exporter → 该文件不生成
- [ ] pytest 全绿(123 + ≥5 个)
- [ ] 使用实操文档.md 加 §"多格式输出"
- [ ] 架构评审与优化计划.md 追加
- [ ] commit:`feat(T-B4): multi-format export (md/wechat/email/notion)`
- [ ] log 完整

## 禁止项

- 不要硬依赖第三方渲染库(纯 Python jinja2 即可)
- 不要阻塞 PDF 主流程(exporter 失败只 warn)
- 不要自动 push

## 失败处理

- 单个 exporter 失败 → 标 quality_flags,继续其他
- 全部失败 → log 记录 + 终端提示

## 完成后输出

```
=== T-B4 Report ===
diff stat: ...
pytest 末 30 行: ...
commit hash: ...
总结: <1 句话>
```
