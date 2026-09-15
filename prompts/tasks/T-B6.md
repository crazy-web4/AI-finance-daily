# T-B6 — 本地 RSS / Atom Feed(`ai-daily feed`)

> 任务来源:`资深架构师优化建议_产品化.md` §#6 · 批次:2(看板)
> 优先级:P1 · 预估代码量:200~300 行 · 依赖:无(标准库)

## 任务定义

- **文档来源**:`资深架构师优化建议_产品化.md` §二.6
- **目标**:日报自动生成 RSS / Atom,订阅器(Feedly / NetNewsWire / Reeder)可订阅
- **现状**:想"每天 8 点打开订阅器看昨天日报",但日报是 PDF/HTML,无法被 RSS 阅读器识别
- **落地后**:
  ```bash
  python main.py feed --port 8911
  # 输出:http://127.0.0.1:8911/feed.xml
  # 在 NetNewsWire 添加订阅 → 每天自动拉取日报标题,点进去看完整 PDF
  ```

## 涉及文件(必动)

- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/web/feed.py`(~200 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/tests/test_feed.py`(≥5 个)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/main.py`(注册 `feed` 子命令)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/使用实操文档.md`
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/架构评审与优化计划.md`

## 落地步骤

1. **`feed.py`**:
   - 扫 `data/reports/{date}/daily_*.json`,按日期倒序
   - 生成 RSS 2.0:`channel/title/link/description`,每个 item 含 title(头条 1~3 条)/pubDate/link(本地路径)/description(摘要)
   - 生成 Atom 1.0:同样的语义
   - 同时输出 `/feed.xml`(RSS) 和 `/atom.xml`(Atom),两者双格式
2. **HTTP server**:复用 stdlib `http.server` 或挂到 T-A1 的 server(简化起见独立,端口 8911)
3. **空 feed**:无日报时输出只含 metadata 的空 feed
4. **测试**(≥5 个):
   - feed.xml 结构合法(`xml.etree` 解析通过)
   - 必填字段齐全(title/link/pubDate/description)
   - 30 天日报全部出现在 items
   - 中文不丢字
   - 空 feed 仍可解析
5. **commit**:`feat(T-B6): local RSS/Atom feed`

## 验收清单

- [ ] `python main.py feed --port 8911` 启动后,`http://127.0.0.1:8911/feed.xml` 返回合法 RSS XML
- [ ] NetNewsWire/Reeder 添加订阅 → 列表显示日报标题,点击进入 HTML 预览页
- [ ] `/atom.xml` 同等可用
- [ ] 无任何日报时输出空 feed(只 metadata)
- [ ] pytest 全绿(123 + ≥5 个)
- [ ] 使用实操文档.md 加 §"RSS Feed"
- [ ] 架构评审与优化计划.md 追加
- [ ] commit:`feat(T-B6): local RSS/Atom feed`
- [ ] log 完整

## 禁止项

- 不要引入 feedparser 等第三方依赖(标准库 `xml.etree` 足够)
- 不要自动 push
- 不要顺手改 T-A1 的 server(独立端口 8911)

## 失败处理

- 验收不过 → log 留痕,不 commit

## 完成后输出

```
=== T-B6 Report ===
diff stat: ...
pytest 末 30 行: ...
commit hash: ...
总结: <1 句话>
```
