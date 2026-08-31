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
import hashlib
from datetime import datetime, timezone
from typing import Any

from app.agents.base import LLMClient
from app.utils.timeutil import report_day_start, report_now, report_today
from app.pipeline.collector import RawNewsArticle
from app.pipeline.cluster import build_article_map
from app.schemas.models import (
    Category,
    DailyReport,
    NewsEvent,
    ReportItem,
    ReportSection,
    ReportKeyData,
    ReportSource,
)


# ═══════════════════════════════════════════════════════
# JSON 解析工具（第三轮 P1: 收敛到 app.agents.base 唯一实现）
# ═══════════════════════════════════════════════════════

from app.agents.base import extract_json as _extract_json  # noqa: E402


# 分析结果缓存版本：prompt/输出结构变化时 +1，使旧缓存自动失效。
# 第三轮 T3: v4 使含内联水印噪声的旧分析缓存自动失效
ANALYST_CACHE_VERSION = "v4"


def _event_fingerprint(event: NewsEvent, fulltexts: list[dict] | None = None) -> str:
    """事件内容指纹：规范标题 + 文章ID（内容派生哈希）+ 是否含全文。

    同一事件跨天/重跑时指纹稳定，可直接复用分析结果、省去重复 LLM 调用；
    文章集合或是否提供原文全文发生变化时指纹随之变化，强制重新分析。
    """
    basis = [ANALYST_CACHE_VERSION, event.canonical_title]
    basis.extend(sorted(event.article_ids))
    if fulltexts:
        # 提供全文的分析结论与仅摘要时不同，按全文 URL 区分
        basis.append("ft:" + ",".join(sorted(ft.get("url", "") for ft in fulltexts)))
    digest = hashlib.sha1("|".join(basis).encode("utf-8")).hexdigest()[:16]
    return f"evt_{digest}"


# ═══════════════════════════════════════════════════════
# 上下文构造
# ═══════════════════════════════════════════════════════

def _build_event_context(
    event: NewsEvent,
    article_map: dict[str, RawNewsArticle],
    fulltexts: list[dict] | None = None,
) -> str:
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

    # 架构评审 #7: 原文全文（截取）优先于摘要
    if fulltexts:
        lines.append("### 原文全文（截取，可信度高于摘要）：")
        for ft in fulltexts[:2]:
            lines.append(f"--- [{ft['domain']}] {ft['url']} ---")
            lines.append(ft["fulltext"][:3000])
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
- 【关键数据】只列真正重要的3-5个，宁缺毋滥；数值必须能在提供的原文/摘要中字面找到，找不到就不要列
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
    def __init__(self, llm=None, use_cache: bool = True) -> None:
        self.llm = llm or LLMClient()
        self.use_cache = use_cache

    def analyze_event(
        self,
        event: NewsEvent,
        article_map: dict[str, RawNewsArticle],
        fulltexts: list[dict] | None = None,
    ) -> dict | None:
        context = _build_event_context(event, article_map, fulltexts)
        user_prompt = f"请分析以下AI新闻事件，输出JSON。\n\n{context}"

        # 事件指纹缓存：同一事件重跑/跨天复现时复用结果，省 LLM 调用（#22）
        fp = _event_fingerprint(event, fulltexts)
        if self.use_cache:
            try:
                from app.utils.cache import get_cached_event_analysis
                cached = get_cached_event_analysis(fp)
                if cached and cached.get("is_valid", True):
                    print(f"    💾 命中分析缓存 [{event.canonical_title[:40]}]", flush=True)
                    return cached
            except Exception as e:
                print(f"    ⚠️  分析缓存读取失败: {e}", flush=True)

        try:
            resp = self.llm.chat_text(
                system_prompt=ANALYST_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
            )
            data = _extract_json(resp)
            if not data.get("is_valid", True):
                return None
            if self.use_cache:
                try:
                    from app.utils.cache import cache_event_analysis
                    cache_event_analysis(fp, data)
                except Exception:
                    pass
            return data
        except Exception as e:
            print(f"  ⚠️  分析失败 [{event.canonical_title[:40]}]: {e}", flush=True)
            return None

    async def analyze_event_async(
        self,
        event: NewsEvent,
        article_map: dict[str, RawNewsArticle],
        semaphore: asyncio.Semaphore,
        fulltexts_map: dict | None = None,
    ) -> tuple | None:
        async with semaphore:
            loop = asyncio.get_running_loop()  # 第三轮 T20: 弃用 API 替换
            fts = (fulltexts_map or {}).get(event.event_id)
            result = await loop.run_in_executor(
                None, self.analyze_event, event, article_map, fts
            )
            return (event, result) if result else None

    async def analyze_batch_async(
        self,
        events: list[NewsEvent],
        article_map: dict[str, RawNewsArticle],
        max_events: int | None = None,
        concurrency: int = 3,
        fulltexts_map: dict | None = None,
    ) -> list[tuple]:
        target = events[:max_events] if max_events else events
        n_ft = sum(1 for e in target if (fulltexts_map or {}).get(e.event_id))
        print(f"\n  🧪 Analyst Agent — {len(target)} 个事件（并发{concurrency}，{n_ft} 个含原文全文）", flush=True)

        semaphore = asyncio.Semaphore(concurrency)
        tasks = [
            self.analyze_event_async(e, article_map, semaphore, fulltexts_map)
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

OFFICIAL_SOURCE_KEYWORDS = [
    "openai.com", "anthropic.com", "nvidia.com", "gov", "gov.cn",
    "arxiv.org", "whitehouse",
]


def _analysis_to_item(event, analysis, rank, category_id, article_map=None) -> ReportItem:
    # 第二轮 R7: 来源名-URL 对齐修复。
    # 来源名直接取自文章的 source_name 字段（与 URL 同篇文章，天然对齐），
    # 不再用 LLM 的 source_names 按下标配对——LLM 列表顺序与文章顺序不保证一致。
    sources = []
    seen_domains: set[str] = set()

    # 优先从 article_map 取真实文章 URL（按域名去重，保持文章的可靠性排序）
    if article_map:
        for aid in event.article_ids:
            art = article_map.get(aid)
            if art is None:
                continue
            d = art.source_domain
            if d in seen_domains:
                continue
            seen_domains.add(d)
            sources.append(ReportSource(
                name=art.source_name or d,
                url=str(art.url),
                is_official=any(kw in d for kw in OFFICIAL_SOURCE_KEYWORDS),
            ))
            if len(sources) >= 5:
                break

    # 回退：无 article_map 时才用域名级 URL
    for d in event.source_domains[:5]:
        if len(sources) >= 5 or d in seen_domains:
            continue
        seen_domains.add(d)
        try:
            sources.append(ReportSource(
                name=d,
                url=f"https://{d}",
                is_official=any(kw in d for kw in OFFICIAL_SOURCE_KEYWORDS),
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
    details = analysis.get("details", "") or analysis.get("summary", "")
    an = analysis.get("analysis")
    text_len = len(title) + len(details) + len(an or "")

    cat = category_id if category_id in [c.value for c in Category] else "industry"
    return ReportItem(
        item_id=f"item_{rank:03d}",
        event_id=event.event_id,
        rank=rank,
        category=Category(cat),
        title=title,
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

    def __init__(self, llm=None) -> None:
        self.llm = llm or LLMClient()

    def finalize(
        self,
        analyzed_results: list[tuple],
        report_date: str | None = None,
        article_map: dict[str, RawNewsArticle] | None = None,
    ) -> DailyReport:
        if not report_date:
            report_date = report_today()

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

        # 选今日头条（>=80分，取前7，不足3条时放宽到70分）
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
            ("us_stocks", "美股盘前资讯"),
        ]

        sections = []

        # 今日头条（记录入选事件，后续栏目去重用）
        top_event_ids = {e.event_id for _, e, _ in top_news}
        top_items = [
            _analysis_to_item(e, a, rank, "top_news", article_map)
            for rank, (_, e, a) in enumerate(top_news, 1)
        ]
        sections.append(ReportSection(
            section_id=Category.TOP_NEWS,
            section_name="今日头条",
            item_count=len(top_items),
            items=top_items,
        ))

        # 其他栏目（剔除已入选今日头条的事件，避免同一条新闻出现两次）
        for sec_id, sec_name in section_defs[1:]:
            cat_items = [
                (ev, an) for ev, an in by_category.get(sec_id, [])
                if ev.event_id not in top_event_ids
            ]
            items_data = cat_items[:8]
            report_items = [
                _analysis_to_item(event, analysis, rank, sec_id, article_map)
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
            time_window_start=report_day_start(report_date),
            time_window_end=report_now(),
            total_items=total_items,
            total_word_count=total_words,
            editor_summary=editor_summary,
            sections=sections,
            generated_at=datetime.now(timezone.utc),
        )

    def _write_summary(self, top_news: list[tuple]) -> str | None:
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
