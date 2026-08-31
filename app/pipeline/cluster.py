"""
事件聚类器
职责: 把 RawNewsArticle[] 聚合成 NewsEvent[]（多篇文章 → 一个事件）

策略:
  1. URL 去重（已在采集器完成）
  2. 标题相似度聚类（字符 bigram + Jaccard）
  3. 按公司/关键词辅助分组
  4. 每组生成一个代表性标题和事件ID
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.pipeline.collector import RawNewsArticle
from app.schemas.models import NewsEvent, EventType


# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════

def _title_bigrams(title: str) -> set[str]:
    """标题的字符 bigram 集合（用于相似度计算）。"""
    t = re.sub(r'[^\w\u4e00-\u9fff]', '', title.lower())
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i+2] for i in range(len(t)-1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union > 0 else 0.0


# 常见公司名提取关键词
COMPANY_KEYWORDS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepmind": "Google DeepMind",
    "google": "Google",
    "microsoft": "Microsoft",
    "meta": "Meta",
    "nvidia": "NVIDIA",
    "amazon": "Amazon",
    "apple": "Apple",
    "xai": "xAI",
    "mistral": "Mistral",
    "cohere": "Cohere",
    "perplexity": "Perplexity",
    "deepseek": "DeepSeek",
    "minimax": "MiniMax",
    "moonshot": "Moonshot AI",
    "zhipu": "Zhipu AI",
    "01.ai": "01.AI",
    "alibaba": "Alibaba",
    "tencent": "Tencent",
    "baidu": "Baidu",
    "bytedance": "ByteDance",
    "huawei": "Huawei",
    "cerebras": "Cerebras",
    "groq": "Groq",
    "tsmc": "TSMC",
    "samsung": "Samsung",
    "sk hynix": "SK Hynix",
    "amd": "AMD",
    "intel": "Intel",
}


def _extract_companies(text: str) -> list[str]:
    """从文本中提取提到的公司。"""
    text_lower = text.lower()
    found = []
    for kw, name in COMPANY_KEYWORDS.items():
        if kw in text_lower:
            found.append(name)
    return found


def _guess_event_type(title: str, snippet: str) -> EventType | None:
    """根据关键词猜测事件类型（粗略，Agent 会再精化）。"""
    text = (title + " " + snippet).lower()

    rules: list[tuple[list[str], EventType]] = [
        (["funding", "raised", "series", "valuation", "融资", "估值", "亿美元"], EventType.FUNDING_ROUND),
        (["acquire", "acquisition", "收购", "并购"], EventType.ACQUISITION),
        (["launch", "release", "unveil", "introduce", "发布", "推出", "上线"], EventType.MODEL_RELEASE),
        (["api", "endpoint"], EventType.API_LAUNCH),
        (["regulation", "policy", "law", "act", "监管", "政策", "法案"], EventType.REGULATION_UPDATE),
        (["chip", "gpu", "asic", "芯片", "算力"], EventType.CHIP_HARDWARE),
        (["partner", "合作", "联盟"], EventType.PARTNERSHIP),
        (["research", "paper", "arxiv", "研究", "论文"], EventType.RESEARCH_BREAKTHROUGH),
        (["lawsuit", "sue", "诉讼", "起诉"], EventType.LAWSUIT_LEGAL),
        (["revenue", "earnings", "收入", "财报"], EventType.MARKET_DATA),
        (["agent", "智能体"], EventType.MODEL_RELEASE),
    ]

    for keywords, etype in rules:
        for kw in keywords:
            if kw in text:
                return etype
    return None


# ═══════════════════════════════════════════════════════
# 聚类主函数
# ═══════════════════════════════════════════════════════

def cluster_articles(
    articles: list[RawNewsArticle],
    title_threshold: float = 0.65,
) -> list[NewsEvent]:
    """
    把文章聚合成事件。

    优化算法: 分桶聚类
    1. 按公司/域名预分桶
    2. 桶内使用贪心聚类
    3. 相似桶合并

    Args:
        articles: 归一化后的文章列表
        title_threshold: 标题相似度阈值 (0~1)

    Returns:
        NewsEvent 列表，按组内文章数降序排列
    """
    if not articles:
        return []

    # 优化：预分桶策略（按公司/域名把候选集缩小，O(n²) 只在桶内进行）
    buckets = _preprocess_buckets(articles)

    # 桶内贪心聚类（已含公司感知阈值），事件始终携带真实 article_id
    clustered_events: list[NewsEvent] = []
    for bucket_articles in buckets.values():
        arts = [item[1] for item in bucket_articles]
        if len(arts) == 1:
            clustered_events.append(_single_to_event(arts[0]))
        else:
            clustered_events.extend(_greedy_cluster_articles(arts, title_threshold))

    # 跨桶兜底合并：不同桶（公司主次不同 / 域名回退）但实为同一事件的，
    # 仅当规范标题高度相似时才合并，避免把同公司的不同新闻错误并成一条。
    final_events = _merge_similar_buckets(clustered_events, title_threshold)

    # 按重要性排序
    final_events.sort(key=lambda e: (e.article_count, len(e.source_domains)), reverse=True)
    return final_events


def _preprocess_buckets(articles: list[RawNewsArticle]) -> dict:
    """预处理分桶"""
    buckets = defaultdict(list)

    for i, article in enumerate(articles):
        # 提取分桶键：优先公司名，再域名
        bucket_key = _get_bucket_key(article)
        buckets[bucket_key].append((i, article))

    return buckets


def _get_bucket_key(article: RawNewsArticle) -> str:
    """获取分桶键"""
    # 1. 首先尝试公司名
    companies = _extract_companies(article.title + " " + article.snippet)
    if companies:
        return companies[0].lower()

    # 2. 使用域名
    return article.source_domain


def _greedy_cluster_articles(articles: list[RawNewsArticle],
                           title_threshold: float) -> list[NewsEvent]:
    """原始的贪心聚类算法"""
    # 预计算 bigram
    bigrams = [_title_bigrams(a.title) for a in articles]

    clusters: list[list[int]] = []
    cluster_bigrams: list[set[str]] = []
    companies = [set(_extract_companies(a.title)) for a in articles]
    cluster_companies: list[set[str]] = []

    for i, art in enumerate(articles):
        if not bigrams[i]:
            clusters.append([i])
            cluster_bigrams.append(bigrams[i])
            cluster_companies.append(set(companies[i]))
            continue

        best_sim = 0.0
        best_cluster = -1

        for j, cb in enumerate(cluster_bigrams):
            if not cb:
                continue
            sim = _jaccard(bigrams[i], cb)
            thr = title_threshold
            if companies[i] and companies[i] & cluster_companies[j]:
                # 共享公司时放宽阈值（实测同义改写标题 sim≈0.42，无关同公司新闻 sim<0.3）
                thr = max(0.30, title_threshold - 0.25)
            if sim > best_sim and sim >= thr:
                best_sim = sim
                best_cluster = j

        if best_cluster >= 0:
            clusters[best_cluster].append(i)
            cluster_bigrams[best_cluster] = cluster_bigrams[best_cluster] | bigrams[i]
            cluster_companies[best_cluster] |= companies[i]
        else:
            clusters.append([i])
            cluster_bigrams.append(set(bigrams[i]))
            cluster_companies.append(set(companies[i]))

    # 转换为 NewsEvent
    events = []
    for cluster in clusters:
        cluster_articles = [articles[idx] for idx in cluster]

        # 选代表标题
        rel_weight = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
        cluster_articles.sort(
            key=lambda a: (
                rel_weight.get(a.source_reliability, 0),
                len(a.title),
            ),
            reverse=True,
        )
        canonical = cluster_articles[0]

        # 收集数据
        all_companies = set()
        all_domains = set()
        all_times = []

        for a in cluster_articles:
            all_companies.update(_extract_companies(a.title + " " + a.snippet))
            all_domains.add(a.source_domain)
            if a.published_at:
                all_times.append(a.published_at)

        # 生成事件
        etype = _guess_event_type(canonical.title, canonical.snippet)
        seed = canonical.title[:50].lower()
        event_id = NewsEvent.make_id(seed)

        # 计算聚类置信度
        if len(cluster_articles) > 1:
            sims = []
            for i in range(min(5, len(cluster_articles))):
                for j in range(i + 1, min(5, len(cluster_articles))):
                    a_bi = _title_bigrams(cluster_articles[i].title)
                    b_bi = _title_bigrams(cluster_articles[j].title)
                    sims.append(_jaccard(a_bi, b_bi))
            cluster_score = sum(sims) / len(sims) if sims else 1.0
        else:
            cluster_score = 1.0

        event = NewsEvent(
            event_id=event_id,
            canonical_title=canonical.title,
            article_ids=[a.article_id for a in cluster_articles],
            article_count=len(cluster_articles),
            event_type_guess=etype,
            earliest_published_at=min(all_times) if all_times else None,
            latest_published_at=max(all_times) if all_times else None,
            source_domains=sorted(all_domains),
            companies_mentioned=sorted(all_companies),
            cluster_score=round(cluster_score, 3),
        )
        events.append(event)

    return events


def _single_to_event(article: RawNewsArticle) -> NewsEvent:
    """单篇文章转换为事件"""
    companies = _extract_companies(article.title + " " + article.snippet)

    event_id = NewsEvent.make_id(article.title[:50].lower())

    return NewsEvent(
        event_id=event_id,
        canonical_title=article.title,
        article_ids=[article.article_id],
        article_count=1,
        event_type_guess=None,
        earliest_published_at=article.published_at,
        latest_published_at=article.published_at,
        source_domains=[article.source_domain],
        companies_mentioned=sorted(companies),
        cluster_score=1.0,
    )


def _merge_similar_buckets(
    events: list[NewsEvent],
    title_threshold: float,
) -> list[NewsEvent]:
    """跨桶兜底合并：把规范标题高度相似的事件并为一个。

    分桶后，同一事件可能因"公司主次提取不同"或"域名回退"落到不同桶。
    这里在全局范围内做一次保守的贪心合并——只有规范标题 bigram
    Jaccard 相似度达到 ``title_threshold``（不做公司折扣，桶内已做过）
    才合并，避免把同公司的不同新闻错误并成一条。
    """
    if len(events) <= 1:
        return events

    # 大事件优先，保证合并后的规范标题来自文章数最多的簇
    ordered = sorted(
        events,
        key=lambda e: (e.article_count, len(e.source_domains)),
        reverse=True,
    )
    groups: list[list[NewsEvent]] = []
    group_bigrams: list[set[str]] = []

    for event in ordered:
        ev_bi = _title_bigrams(event.canonical_title)
        best_idx = -1
        best_sim = 0.0
        for idx, g_bi in enumerate(group_bigrams):
            sim = _jaccard(ev_bi, g_bi)
            if sim >= title_threshold and sim > best_sim:
                best_sim = sim
                best_idx = idx
        if best_idx >= 0:
            groups[best_idx].append(event)
            group_bigrams[best_idx] = group_bigrams[best_idx] | ev_bi
        else:
            groups.append([event])
            group_bigrams.append(set(ev_bi))

    merged_events = []
    for group in groups:
        if len(group) == 1:
            merged_events.append(group[0])
        else:
            merged_events.append(_merge_similar_events(group))
    return merged_events


def _merge_similar_events(events: list[NewsEvent]) -> NewsEvent:
    """合并相似事件"""
    # 使用标题相似度作为合并标准
    merged = events[0]

    for other in events[1:]:
        # 合并文章ID
        merged.article_ids.extend(other.article_ids)
        merged.article_count += other.article_count

        # 合并来源域名
        merged.source_domains = list(set(merged.source_domains + other.source_domains))

        # 合并公司
        merged.companies_mentioned = list(set(merged.companies_mentioned + other.companies_mentioned))

        # 更新时间
        if other.earliest_published_at:
            if not merged.earliest_published_at or other.earliest_published_at < merged.earliest_published_at:
                merged.earliest_published_at = other.earliest_published_at
        if other.latest_published_at:
            if not merged.latest_published_at or other.latest_published_at > merged.latest_published_at:
                merged.latest_published_at = other.latest_published_at

    # 重新计算聚类置信度
    if len(events) > 1:
        # 简单平均
        total_score = sum(e.cluster_score for e in events)
        merged.cluster_score = round(total_score / len(events), 3)

    return merged


# 辅助：从聚类结果+原文重建完整文章映射
def build_article_map(articles: list[RawNewsArticle]) -> dict[str, RawNewsArticle]:
    """建立 article_id → article 的映射。"""
    return {a.article_id: a for a in articles}


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m app.pipeline.cluster <raw_articles.json>")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = json.load(f)

    articles = [RawNewsArticle.model_validate(d) for d in data]
    events = cluster_articles(articles)

    print(f"输入: {len(articles)} 篇文章")
    print(f"输出: {len(events)} 个事件")
    print()

    for i, e in enumerate(events[:10]):
        print(f"[{i+1}] ({e.article_count}篇/{len(e.source_domains)}域) {e.canonical_title[:70]}")
        print(f"     公司: {e.companies_mentioned[:5]}")
        print(f"     类型: {e.event_type_guess}")
        print(f"     置信: {e.cluster_score}")
