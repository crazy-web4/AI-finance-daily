# AI 财经日报 · 资深架构师优化建议（第 13 批 · Web 看板产品化）

> 评审日期: 2026-09-05 ｜ 基线: 255 测试全绿（scripts/pytest.sh）
> 评审方式: 源码通读 + 真实产物实测（data/reports/2026-09-05）
> 性质: 后端能力已完整（采集/分析/SQLite FTS/趋势/个性化/多格式导出），**用户接触面短板在 Web 看板**。

---

## 一、现状判断（基于实测，非文档推断）

| 能力 | 后端/CLI | Web 看板 | 差距 |
|---|---|---|---|
| 读报内容 | daily JSON 含 details/analysis/key_data/sources | 详情页只列**标题**，正文需下载 PDF | **最大缺口** |
| 全文检索 | `storage/query.search`（FTS5+LIKE） | 无搜索入口 | 能力闲置 |
| 趋势洞察 | `storage/trend`（融资/头条差异/话题热度）+ stats | 无页面 | 能力闲置 |
| 个性化订阅 | `personalization.filter_report` + SubscriptionStore | 仅 CLI 可管理 | 能力闲置 |
| 触发跑出报 | run_daily（--test/--full） | 固定 `--test`，无模式选择/历史 | 体验弱 |

结论：**不新建后端能力，把已有能力 surfaced 到浏览器**，风险低、价值高、可完全复用现有 handler 测试模式。

---

## 二、本批落地项（T13）

- **T13-A 在线读报视图** `/read/<date>`：栏目分组 + 标题 + key_data 表 + 正文段落 + 编辑点评 +
  可点击来源链接 + 质量标记 + 导读。纯渲染函数 `app/web/readview.py`，可单测。
- **T13-B 全站情报搜索** `/search?q=&days=&category=` + 导航栏搜索框：复用 `storage/query.search`，
  结果带日期/栏目/重要度/命中关键词高亮，链接到当日读报页；`/api/search` 出 JSON。缺索引自动构建。
- **T13-C 趋势洞察页** `/insights`：栏目分布（CSS 条形）、公司 TOP、融资热点、本周新增/淡出头条、
  话题热度（纯 SVG/CSS，零新依赖）。
- **T13-D 我的订阅** `/my`（个性化读报，默认订阅过滤最新一期）+ `/subscriptions`（网页增删订阅）。
- **T13-E 触发增强**：`/trigger` 支持 `mode=test|full`，首页给出模式选择与最近触发提示。

## 三、工程约定
- 新增 `app/web/readview.py`（纯 HTML 渲染，无 socket），路由薄接入 `app/web/server.py`。
- 每个新路由在 `tests/test_web.py` 补 handler 级测试（不起 server）。
- 落地后双验证：`scripts/pytest.sh -q` 全绿 + `.venv/bin/python run_daily.py --test` 端到端。
