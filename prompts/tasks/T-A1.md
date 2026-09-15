# T-A1 — 本地 Web 看板(`ai-daily web`)

> 任务来源:`资深架构师优化建议_产品化.md` §#1 · 批次:2(看板)
> 优先级:P0 · 预估代码量:800~1200 行 · 依赖:无

## 任务定义

- **文档来源**:`资深架构师优化建议_产品化.md` §二.1
- **目标**:浏览器打开 `http://127.0.0.1:8910` 即可看到历史日报、运行健康、配置状态
- **现状**:看历史 `ls data/reports/`、看健康 grep runlog、看今天 PDF 命令长
- **落地后**:
  - 首页:今日报告卡片 + 近 7 天列表(缩略图、字数、状态)
  - 详情页:PDF / HTML / JSON 三种产物 + runlog 摘要
  - "健康"页:近 30 天成功率、平均耗时、缓存命中率、LLM 调用成本
  - "触发"按钮:点击即启动端到端出报(后台线程跑)
  - "配置"页:可视化显示当前配置(.env / yaml),可一键校验

## 涉及文件(必动)

- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/web/__init__.py`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/web/server.py`(~400 行,ASGI/WSGI 入口)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/web/routes.py`(~200 行,路由)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/web/templates/index.html`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/web/templates/report.html`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/web/templates/health.html`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/web/templates/config.html`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/web/static/style.css`
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/tests/test_web.py`(≥5 个)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/main.py`(注册 `web --port 8910`)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/使用实操文档.md`
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/架构评审与优化计划.md`

## 落地步骤

1. **技术选型**:**Python 标准库 `http.server` + Jinja2** 优先(避免 FastAPI/uvicorn 重依赖);如果开发效率受限,可选 `starlette + uvicorn`(在 requirements 标注 optional)
2. **`server.py`**:实现 `make_app()` 工厂,接收 `port` 参数,挂载路由
3. **`routes.py`**:
   - `GET /` → 首页(今日 + 近 7 天列表)
   - `GET /report/<date>` → 详情页(PDF/HTML/JSON 链接 + runlog 摘要)
   - `GET /health` → 健康页(扫 `data/reports/*/run_*.json` 聚合 30 天成功率/平均耗时)
   - `GET /config` → 配置页(读 `app.config` + `app.search.queries.load_strategy`)
   - `POST /trigger` → 启动后台线程跑 `run_daily.py --full`(用 `threading.Thread(daemon=True)`),立即返回 202
4. **关闭时不留孤儿**:监听 `SIGTERM/SIGINT`,关闭 socket,等所有 daemon 线程
5. **测试**(≥5 个):用 `wsgiref` / `TestClient` 测试 handler 函数,不真启 server
6. **commit**:`feat(T-A1): local web dashboard`

## 验收清单

- [ ] `python main.py web --port 8910` → 浏览器访问首页列出近 7 天日报
- [ ] 点击某日报 → 显示 PDF 路径(供下载)+ HTML 预览 + runlog 摘要
- [ ] "健康"页 → 30 天成功率 + 平均耗时(读 `run_*.json` 聚合)
- [ ] "配置"页 → 显示 LLM 模型/时区/缓存配置
- [ ] "触发"按钮 → 后台线程跑出报,不阻塞页面,202 立即返回
- [ ] 关闭 web 进程时不留孤儿线程,无 Python 致命错误
- [ ] pytest 全绿(123 + ≥5 个),handler 测试不启动 server
- [ ] 使用实操文档.md 加 §"Web 看板"
- [ ] 架构评审与优化计划.md 追加
- [ ] commit:`feat(T-A1): local web dashboard`
- [ ] log 完整

## 禁止项

- 不要引入新的强制依赖(starlette/uvicorn 标 optional)
- 不要自动 push
- 不要顺手改其他模块

## 失败处理

- 验收不过 → log 留痕,不 commit

## 完成后输出

```
=== T-A1 Report ===
diff stat: ...
pytest 末 30 行: ...
commit hash: ...
总结: <1 句话>
```
