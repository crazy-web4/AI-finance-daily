"""
Agent 流水线（V1）
=================================================
Analyst Agent（分析+分类+编辑一体化） → ChiefEditor（排序+选头条+导读）
策略：Python 做确定性工作（分类排序），LLM 做理解性工作（写内容）
"""

from __future__ import annotations

import json
import re
import asyncio
from datetime import datetime, timezone
from typing import Any

from app.agents.base import LLMClient
from app.pipeline.collector import RawNewsArticle
from app.pipeline.cluster import build_article_map
from app.schemas.models import (
    Category,
    DailyReport,
    ReportItem,
    ReportSection,
    ReportKeyData,
    ReportSource,
)


# ═══════════════════════════════════════════════════════
# JSON 解析工具
# ═══════════════════════════════════════════════════════

def _extract_json(text: str) -> dict[str, Any]:
    """从LLM输出中提取JSON，支持多种格式和自动修复。"""
    text = text.strip()
    m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1).strip()
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        text = text[start:end+1]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    fixed = re.sub(r',(\s*[}\]])', r'\1', text)
    try:
        return json.loads(fixed)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    raise ValueError(f"无法解析 JSON: {text[:500]}")


# ═══════════════════════════════════════════════════════
# 上下文构造
# ═══════════════════════════════════════════════════════

def _build_event_context(event, article_map) -> str:
    lines = []
    lines.append(f"## 事件：{event.canonical_title}")
    lines.append(f"涉及公司：{', '.join(event.companies_mentioned) if event.companies_mentioned else '未知'}")
    lines.append(f"来源：{event.article_count} 篇 / {len(event.source_domains)} 个域名")
    lines.append(f"类型：{event.event_type_guess}")
    lines.append("")
    lines.append("### 相关文章：")
    for i, aid in enumerate(event.article_ids[:6]):
        art = article_map.get(aid)
        if not art:
            continue
        lines.append(f"--- {i+1}. [{art.source_domain}] ---")
        lines.append(f"标题: {art.title}")
        lines.append(f"URL: {art.url}")
        lines.append(f"摘要: {art.snippet[:400]}")
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# Analyst Agent
# ═══════════════════════════════════════════════════════

ANALYST_PROMPT = """你是一名AI行业财经日报的资深分析师兼编辑。

任务：阅读一组描述同一事件的多篇新闻，完成分析并写成日报条目。

必须输出严格JSON，格式如下：
{
  "is_valid": true,
  "category": "model_tech",
  "importance_score": 85,
  "title": "事件标题（25-40字，中文）",
  "details": "摘要正文，100-800字弹性，信息量决定长度",
  "key_data": [
    {"label": "指标名", "value": "数值"}
  ],
  "published_at": "2026-08-19T12:00:00Z",
  "source_names": ["Reuters", "Bloomberg", "官方博客"],
  "topics": ["tag1", "tag2"]
}

【特别重要】summary 字段要求（这是最终展示给读者的内容）：
- 90分以上：600-800字，背景+核心事实+关键数据+多方反应+行业影响+未来展望
- 80-89分：400-600字，核心事实+详细数据+影响分析+相关背景
- 70-79分：250-350字，主要事实+关键数据+简要影响
- 70分以下：150-200字，核心事实
- 信息密度第一，直接给干货，不要铺垫寒暄
- 关键数据自然融入正文
- 可以分2-3小段，每段一个主题
- 要有细节、有数据、有判断，不要空泛

六大栏目（category 选一个）:
- model_tech: 模型发布与技术进展
- funding: 融资与资本动态
- policy: 政策与监管
- research: 学术与研究突破
- industry: 市场与产业动态

重要性评分（0-100）:
- 90+ 改变行业格局
- 80-89 重大事件
- 70-79 重要事件
- 60-69 一般
- <60 不重要

写作质量要求（非常重要）:
- 【信息密度】每句话都要有信息量，不要空话套话
- 【精炼】用最少的字传达最多的信息，去掉修饰性、铺垫性文字
- 【数据优先】能用数字表达的就用数字，自然融入摘要中
- 【客观】不要"重磅""震惊"等情绪化词汇
- 【摘要分级】根据重要性分数决定摘要详略（见上面summary要求）
- 【关键数据】只列真正重要的3-5个，宁缺毋滥
- 【来源】填上3-5个来源媒体名称

要求:
- 全中文输出
- 关键数据可以是空数组
- 没有行业判断时 analysis 为 null
- 不要任何额外文字，只输出JSON
- published_at 字段填事件发布时间（ISO格式），不知道就填null
- source_names 数组填3-5个来源媒体名称
"""


class AnalystAgent:
    def __init__(self, llm=None):
        self.llm = llm or LLMClient()

    def analyze_event(self, event, article_map):
        context = _build_event_context(event, article_map)
        user_prompt = f"请分析以下AI新闻事件，输出JSON。\n\n{context}"
        try:
            resp = self.llm.chat_text(
                system_prompt=ANALYST_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
            )
            data = _extract_json(resp)
            if not data.get("is_valid", True):
                return None
            return data
        except Exception as e:
            print(f"  ⚠️  分析失败 [{event.canonical_title[:40]}]: {e}", flush=True)
            return None

    async def analyze_event_async(self, event, article_map, semaphore):
        async with semaphore:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self.analyze_event, event, article_map
            )
            return (event, result) if result else None

    async def analyze_batch_async(self, events, article_map, max_events=None, concurrency=3):
        target = events[:max_events] if max_events else events
        print(f"\n  🧪 Analyst Agent — {len(target)} 个事件（并发{concurrency}）", flush=True)

        semaphore = asyncio.Semaphore(concurrency)
        tasks = [
            self.analyze_event_async(e, article_map, semaphore)
            for e in target
        ]

        results = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            done += 1
            if result:
                event, analysis = result
                results.append(result)
                cat = analysis.get("category", "?")
                score = analysis.get("importance_score", "?")
                title = analysis.get("title", event.canonical_title)[:45]
                print(f"    [{done}/{len(target)}] ✅ {cat}/{score}分 - {title}", flush=True)
            else:
                print(f"    [{done}/{len(target)}] ❌ 无效", flush=True)

        results.sort(key=lambda x: x[1].get("importance_score", 0), reverse=True)
        print(f"  ✅ 完成: {len(results)}/{len(target)} 有效", flush=True)
        return results


# ═══════════════════════════════════════════════════════
# 辅助：分析结果 → ReportItem
# ═══════════════════════════════════════════════════════

def _analysis_to_item(event, analysis, rank, category_id) -> ReportItem:
    sources = []
    # 优先用分析出的来源名称，其次用域名
    src_names = analysis.get("source_names", []) or []
    for i, d in enumerate(event.source_domains[:5]):
        try:
            name = src_names[i] if i < len(src_names) else d
            # 判断是否官方来源
            is_official = any(kw in d for kw in ["openai.com", "anthropic.com", "nvidia.com", "gov", "gov.cn", "arxiv.org", "whitehouse"])
            sources.append(ReportSource(
                name=name,
                url=f"https://{d}",
                is_official=is_official,
            ))
        except Exception:
            pass

    key_data = []
    for kd in analysis.get("key_data", []) or []:
        if isinstance(kd, dict):
            key_data.append(ReportKeyData(
                label=str(kd.get("label", "")),
                value=str(kd.get("value", "")),
            ))

    title = analysis.get("title", event.canonical_title)
    lead = analysis.get("lead", "")
    details = analysis.get("details", "") or analysis.get("summary", "")
    an = analysis.get("analysis")
    text_len = len(title) + len(lead) + len(details) + len(an or "")

    cat = category_id if category_id in [c.value for c in Category] else "industry"
    return ReportItem(
        item_id=f"item_{rank:03d}",
        event_id=event.event_id,
        rank=rank,
        category=Category(cat),
        title=title,
        lead=lead,
        key_data=key_data,
        details=details,
        analysis=an,
        sources=sources,
        word_count=text_len,
    )


# ═══════════════════════════════════════════════════════
# Chief Editor Agent
# ═══════════════════════════════════════════════════════

class ChiefEditorAgent:
    """总编辑：Python做分类排序（确定性），LLM只写导读。"""

    def __init__(self, llm=None):
        self.llm = llm or LLMClient()

    def finalize(self, analyzed_results, report_date=None):
        if not report_date:
            report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 按分类分组
        by_category = {}
        for event, analysis in analyzed_results:
            cat = analysis.get("category", "industry")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append((event, analysis))

        # 每类按重要性降序
        for cat in by_category:
            by_category[cat].sort(
                key=lambda x: x[1].get("importance_score", 0),
                reverse=True,
            )

        # 选今日头条（>=80分，取前7，最少3条才放宽到75分）
        all_sorted = []
        for cat, items in by_category.items():
            for event, analysis in items:
                all_sorted.append((cat, event, analysis))
        all_sorted.sort(key=lambda x: x[2].get("importance_score", 0), reverse=True)

        top_news = [(c, e, a) for c, e, a in all_sorted if a.get("importance_score", 0) >= 80][:7]
        if len(top_news) < 3:
            top_news = [(c, e, a) for c, e, a in all_sorted if a.get("importance_score", 0) >= 70][:7]

        # 写导读
        editor_summary = self._write_summary(top_news)

        # 组装栏目
        section_defs = [
            ("top_news", "今日头条"),
            ("model_tech", "模型发布与技术进展"),
            ("funding", "融资与资本动态"),
            ("policy", "政策与监管"),
            ("research", "学术与研究突破"),
            ("industry", "市场与产业动态"),
        ]

        sections = []

        # 今日头条
        top_items = [
            _analysis_to_item(e, a, rank, "top_news")
            for rank, (_, e, a) in enumerate(top_news, 1)
        ]
        sections.append(ReportSection(
            section_id=Category.TOP_NEWS,
            section_name="今日头条",
            item_count=len(top_items),
            items=top_items,
        ))

        # 其他栏目
        for sec_id, sec_name in section_defs[1:]:
            items_data = by_category.get(sec_id, [])[:8]
            report_items = [
                _analysis_to_item(event, analysis, rank, sec_id)
                for rank, (event, analysis) in enumerate(items_data, 1)
            ]
            sections.append(ReportSection(
                section_id=Category(sec_id),
                section_name=sec_name,
                item_count=len(report_items),
                items=report_items,
            ))

        total_items = sum(s.item_count for s in sections)
        total_words = sum(it.word_count for s in sections for it in s.items)

        return DailyReport(
            report_id=f"daily_{report_date.replace('-', '')}",
            report_date=report_date,
            time_window_start=datetime.fromisoformat(f"{report_date}T00:00:00+00:00"),
            time_window_end=datetime.now(timezone.utc),
            total_items=total_items,
            total_word_count=total_words,
            editor_summary=editor_summary,
            sections=sections,
            generated_at=datetime.now(timezone.utc),
        )

    def _write_summary(self, top_news):
        """用LLM写今日导读。"""
        if len(top_news) < 3:
            return None
        try:
            titles = [a.get("title", "") for _, _, a in top_news[:5]]
            prompt = f"""请为今天的AI日报写一段100-200字的「今日导读」。

今日要闻：
{chr(10).join(f'{i+1}. {t}' for i, t in enumerate(titles))}

要求：
- 100-200字，中文
- 概括性描述，不要逐条罗列
- 突出最重要的2-3个主题
- 直接输出导读文字，不要任何前缀或解释"""

            result = self.llm.chat_text(
                system_prompt="你是AI财经日报总编辑，擅长写精炼的导读。",
                user_prompt=prompt,
                temperature=0.5,
            ).strip()
            if len(result) > 300:
                result = result[:300]
            return result
        except Exception as e:
            print(f"  ⚠️  导读生成失败: {e}", flush=True)
            return None
