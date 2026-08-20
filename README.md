# AI 财经日报（AI 行业全球动态日报）

一个**全自动的 AI 行业新闻日报生成流水线**：每天自动从全网采集 AI 行业动态，经过去重、聚类、LLM 分析编辑，最终产出一份排版精美的 A4 PDF 日报。

> 读者花 10 分钟读完这份日报，就能掌握当天 AI 行业最重要的动态。

产出样例：`data/reports/{日期}/AI行业全球动态日报_{日期}@Cyber_Gm.pdf`

---

## 一、核心特性

- **矩阵式全网采集**：529 条查询覆盖 6 大批次 —— 30 家核心 AI 公司 × 15 类事件、行业趋势、热点快讯、政策监管、学术研究、中文媒体补充
- **双搜索引擎**：AnySearch（MCP 协议）为主，Tavily 可选补充
- **来源分级**：域名自动分级（官方一手 / 权威媒体 / 科技媒体），影响排序与去重取舍
- **智能去重聚类**：URL 归一化去重 + 标题相似度（bigram Jaccard）去重 + 事件聚类，多篇报道归并为一个事件
- **LLM 分析编辑**：每个事件由 Analyst Agent 完成分类、重要性打分、中文标题撰写、详情写作、关键数据提取；Chief Editor 完成栏目组织、头条遴选、导读撰写
- **杂志级 PDF 排版**：Jinja2 模板 + Playwright(Chromium) 渲染，含封面、目录、六大栏目、水印
- **全链路可恢复**：采集结果、聚类结果、日报 JSON 均落盘，任意阶段可断点续跑

---

## 二、流水线架构

```
┌──────────────────────────────────────────────────────────────┐
│ STEP 1  新闻采集                                              │
│ config/search_strategy.yaml ──► 529 条查询                    │
│   AnySearch batch_search（5条/批）+ Tavily 补充               │
│   → 归一化 → 来源分级 → 24h 时效过滤 → URL/标题去重            │
│   → data/raw/{date}/raw_*.json                               │
├──────────────────────────────────────────────────────────────┤
│ STEP 2  事件聚类                                              │
│   标题 bigram Jaccard 相似度（阈值0.6）贪心聚类                │
│   多篇文章 → 一个 NewsEvent（含公司识别、事件类型猜测）          │
│   → data/events/{date}/events_*.json                         │
├──────────────────────────────────────────────────────────────┤
│ STEP 3  Agent 分析与编辑                                      │
│   均衡选事件（每分类保底 + 按热度补足）                         │
│   AnalystAgent：分类 / 重要性评分 / 标题 / 详情 / 关键数据      │
│   ChiefEditorAgent：栏目组织 / 头条(≥80分) / LLM导读           │
│   → data/reports/{date}/daily_{date}.json                    │
├──────────────────────────────────────────────────────────────┤
│ STEP 4  PDF 渲染                                              │
│   Jinja2 模板(report.html + style.css) → HTML                │
│   Playwright Chromium → A4 PDF                               │
│   → data/reports/{date}/AI行业全球动态日报_{date}@Cyber_Gm.pdf │
└──────────────────────────────────────────────────────────────┘
```

**数据模型链路**（详见 `app/schemas/models.py`，接口编号 IF-004）：

```
SearchResultItem → RawNewsArticle → NewsEvent → (Agent分析) → ReportItem → DailyReport
```

---

## 三、目录结构

```
AI财经日报/
├── main.py                      # 入口①：仅采集（info / collect）
├── run_daily.py                 # 入口②：端到端生成日报（采集→聚类→分析→PDF）
├── .env.example                 # 环境变量模板
├── config/
│   └── search_strategy.yaml     # IF-002 搜索策略矩阵（公司×事件、批次、来源分级）
├── app/
│   ├── search/
│   │   ├── anysearch.py         # IF-001 AnySearch MCP 客户端 + Tavily 客户端
│   │   └── queries.py           # 查询生成器（读 yaml → SearchQuery 列表）
│   ├── pipeline/
│   │   ├── collector.py         # 采集器：归一化/分级/时效过滤/去重
│   │   ├── cluster.py           # 事件聚类器
│   │   └── backfill.py          # 空栏目补全（近7天补充搜索）
│   ├── agents/
│   │   ├── base.py              # LLMClient（OpenAI兼容）+ BaseAgent + JSON提取
│   │   └── pipeline.py          # AnalystAgent + ChiefEditorAgent（V1）
│   ├── schemas/
│   │   └── models.py            # 全部 Pydantic 数据模型（L1~L8）
│   └── report/
│       └── renderer.py          # IF-005 PDF 渲染器（Jinja2 + Playwright）
├── prompts/                     # 五角色 Agent 提示词设计稿（01研究员~05总编）
├── templates/                   # PDF 版式模板
│   ├── report.html              # 主模板
│   ├── css/style.css            # 样式（A4、页眉页脚、水印）
│   └── partials/                # 封面/目录/页眉/页底 片段
├── schemas/                     # 自动导出的 JSON Schema（8个模型）
├── data/
│   ├── raw/{date}/              # 采集的原始文章
│   ├── events/{date}/           # 聚类后的事件
│   └── reports/{date}/          # 日报 JSON / HTML / PDF
├── AI 日报工作流方案.md          # 方案设计文档
└── 接口定义总览.md               # IF-001~IF-005 接口定义
```

---

## 四、快速开始

```bash
# 1. 安装依赖（Python ≥ 3.10）
pip install httpx pydantic jinja2 playwright openai python-dotenv pyyaml
playwright install chromium        # PDF 渲染需要 Chromium

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 ANYSEARCH_API_KEY（必填）与 LLM 相关配置

# 3. 端到端冒烟（--test 需配合 --queries-per-batch 才是少量查询）
python run_daily.py --test --queries-per-batch 2

# 4. 全量生成当天日报
python run_daily.py --full --backfill
```

详细操作步骤、参数说明、常见问题见 [使用实操文档.md](./使用实操文档.md)。

---

## 五、环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `ANYSEARCH_API_KEY` | ✅ | AnySearch 搜索 API Key（`as_sk_` 开头） |
| `ARK_API_KEY` | ✅* | LLM API Key（OpenAI 兼容，如豆包/火山方舟） |
| `ARK_BASE_URL` | ✅* | LLM Base URL |
| `LLM_MODEL` | 可选 | 模型名，默认 `doubao-pro-128k-240515` |
| `TAVILY_API_KEY` | 可选 | Tavily 补充搜索，不填则自动跳过 |

\* 也可用 `OPENAI_API_KEY` / `OPENAI_BASE_URL` 代替 ARK 配置。

---

## 六、两个入口

| 入口 | 用途 | 典型命令 |
|------|------|---------|
| `main.py` | 只做**采集**，调试搜索策略 | `python main.py info` / `python main.py collect --test` |
| `run_daily.py` | **端到端**生成日报 | `python run_daily.py --test` / `--full` / `--from-file <json>` |

六大固定栏目：**今日头条 · 模型发布与技术进展 · 融资与资本动态 · 政策与监管 · 学术与研究突破 · 市场与产业动态**

---

## 七、技术栈

- **语言**：Python 3.10+（全异步 asyncio）
- **搜索**：AnySearch MCP Streamable HTTP（JSON-RPC over HTTP）、Tavily Search API
- **LLM**：任意 OpenAI 兼容接口（JSON 模式输出 + 自动重试解析）
- **数据校验**：Pydantic v2（可一键导出 JSON Schema）
- **渲染**：Jinja2 + Playwright Chromium（A4 打印样式）

## 八、相关文档

- [使用实操文档.md](./使用实操文档.md) —— 详细上手与运维指南
- [AI 日报工作流方案.md](./AI%20日报工作流方案.md) —— 整体方案设计
- [接口定义总览.md](./接口定义总览.md) —— IF-001 ~ IF-005 接口定义
