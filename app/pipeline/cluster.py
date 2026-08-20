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

    算法: 贪心聚类
    - 按文章顺序遍历，每个文章找第一个相似度超过阈值的组加入
    - 组内以最高可靠性文章的标题作为代表标题

    Args:
        articles: 归一化后的文章列表
        title_threshold: 标题相似度阈值 (0~1)，越低合并越激进

    Returns:
        NewsEvent 列表，按组内文章数降序排列
    """
    if not articles:
        return []

    # 预计算 bigram
    bigrams = [_title_bigrams(a.title) for a in articles]

    clusters: list[list[int]] = []  # 每个簇是文章索引列表
    cluster_bigrams: list[set[str]] = []  # 每个簇的合并 bigram 集合
    # 架构评审 #9: 公司感知聚类——共享同一公司时放宽相似度阈值，
    # 让"OpenAI 发布 GPT-6"与"OpenAI 推出 GPT-6 模型"这类近义标题合并
    companies = [set(_extract_companies(a.title)) for a in articles]
    cluster_companies: list[set[str]] = []

    for i, art in enumerate(articles):
        if not bigrams[i]:
            # 空标题，单独一组
            clusters.append([i])
            cluster_bigrams.append(bigrams[i])
            cluster_companies.append(set(companies[i]))
            continue

        best_sim = 0.0
        best_cluster = -1

        # 找最相似的簇
        for j, cb in enumerate(cluster_bigrams):
            if not cb:
                continue
            sim = _jaccard(bigrams[i], cb)
            thr = title_threshold
            if companies[i] and companies[i] & cluster_companies[j]:
                thr = max(0.35, title_threshold - 0.15)
            if sim > best_sim and sim >= thr:
                best_sim = sim
                best_cluster = j

        if best_cluster >= 0:
            # 加入最相似的簇
            clusters[best_cluster].append(i)
            # 更新簇的 bigram（合并）
            cluster_bigrams[best_cluster] = cluster_bigrams[best_cluster] | bigrams[i]
            cluster_companies[best_cluster] |= companies[i]
        else:
            # 新建簇
            clusters.append([i])
            cluster_bigrams.append(set(bigrams[i]))
            cluster_companies.append(set(companies[i]))

    # 转换成 NewsEvent
    events: list[NewsEvent] = []
    for cluster in clusters:
        cluster_articles = [articles[idx] for idx in cluster]

        # 选代表标题：可靠性最高 + 标题最长的
        rel_weight = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
        cluster_articles.sort(
            key=lambda a: (
                rel_weight.get(a.source_reliability, 0),
                len(a.title),
            ),
            reverse=True,
        )
        canonical = cluster_articles[0]

        # 收集所有涉及的公司
        all_companies: set[str] = set()
        all_domains: set[str] = set()
        all_times: list[datetime] = []

        for a in cluster_articles:
            all_companies.update(_extract_companies(a.title + " " + a.snippet))
            all_domains.add(a.source_domain)
            if a.published_at:
                all_times.append(a.published_at)

        # 猜测事件类型
        etype = _guess_event_type(canonical.title, canonical.snippet)

        # 生成事件ID
        seed = canonical.title[:50].lower()
        event_id = NewsEvent.make_id(seed)

        # 计算聚类置信度（组内平均相似度）
        if len(cluster_articles) > 1:
            # 用组内平均相似度近似
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

    # 按文章数（重要性）降序
    events.sort(key=lambda e: (e.article_count, len(e.source_domains)), reverse=True)
    return events


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
