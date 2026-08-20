"""
空栏目补全器
职责: 检查各分类的事件数量，不足时用近7天关键词补充搜索

策略:
- 每个栏目定义一组"补全关键词"
- 事件数 < min_threshold 的栏目触发补全
- 补全搜索使用 time_window=7天
- 补全结果和原有结果合并去重
"""

from __future__ import annotations

from typing import Any

from app.search.anysearch import AnySearchClient, SearchQuery
from app.pipeline.collector import (
    NewsCollector,
    RawNewsArticle,
    dedup_by_url,
    dedup_by_title,
)


# 每个栏目的补全搜索词（高质量、广谱的关键词）
BACKFILL_QUERIES: dict[str, list[str]] = {
    "funding": [
        "AI startup funding round this week",
        "AI company valuation 2026",
        "人工智能 融资 本周",
        "AI venture capital investment",
        "AI 并购 收购 最新",
    ],
    "industry": [
        "AI chip market update this week",
        "AI data center construction 2026",
        "AI 算力 产业动态 本周",
        "AI industry partnership announcement",
        "人工智能 应用落地 最新",
        "AI 机器人 产业 本周",
    ],
    "model_tech": [
        "new AI model release this week",
        "AI agent framework new",
        "大模型 发布 本周",
        "AI coding agent update",
    ],
    "policy": [
        "AI regulation policy update this week",
        "AI 监管 政策 本周",
        "EU AI Act latest",
        "China AI regulation new",
    ],
    "research": [
        "arXiv new AI paper this week",
        "AI research breakthrough 2026",
        "AI 论文 最新 本周",
        "NeurIPS ICML AI paper",
    ],
}

# 每个栏目最少应有多少条事件
MIN_ITEMS_PER_CATEGORY = 5

# 补全时取多少条结果
BACKFILL_MAX_RESULTS = 8


async def backfill_empty_categories(
    articles: list[RawNewsArticle],
    api_key: str,
    min_items: int = MIN_ITEMS_PER_CATEGORY,
    time_window_days: int = 7,
) -> list[RawNewsArticle]:
    """
    检查每个分类的文章数量，不足的自动补充搜索。

    Args:
        articles: 已有文章列表
        api_key: AnySearch API key
        min_items: 每个分类最少条数
        time_window_days: 补全的时间窗口(天)

    Returns:
        合并去重后的文章列表
    """
    # 统计现有各分类的文章数
    cat_counts: dict[str, int] = {}
    for a in articles:
        cat = a.category or "unknown"
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print(f"\n  📊 各分类现有文章数:", flush=True)
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        status = "✅" if cnt >= min_items else "⚠️"
        print(f"    {status} {cat:15s} {cnt:3d} 条", flush=True)

    # 找出需要补全的分类
    need_backfill = []
    for cat, queries in BACKFILL_QUERIES.items():
        current = cat_counts.get(cat, 0)
        if current < min_items:
            need_backfill.append((cat, queries))
            print(f"\n  🔄 补全 {cat}（{current}/{min_items}），使用 {len(queries)} 条查询", flush=True)

    if not need_backfill:
        print(f"\n  ✅ 所有分类文章数充足，无需补全", flush=True)
        return articles

    # 生成补全查询
    backfill_queries: list[SearchQuery] = []
    for cat, queries in need_backfill:
        for q in queries:
            backfill_queries.append(SearchQuery(
                query=q,
                max_results=BACKFILL_MAX_RESULTS,
                category=cat,
                batch_id=f"backfill_{cat}",
            ))

    # 执行补全搜索
    print(f"  🚀 补全搜索: {len(backfill_queries)} 条查询...", flush=True)
    client = AnySearchClient(api_key=api_key)
    try:
        batch_resp = await client.search_batch(backfill_queries, batch_id="backfill")
        print(f"     成功: {batch_resp.success_queries}/{batch_resp.total_queries}", flush=True)
        print(f"     新结果: {batch_resp.unique_results} 篇（去重前）", flush=True)

        # 归一化
        from app.pipeline.collector import normalize_result
        query_map = {q.query: q for q in backfill_queries}
        new_articles = []
        for resp in batch_resp.responses:
            q = query_map.get(resp.query)
            for item in resp.results:
                art = normalize_result(item, query=q)
                new_articles.append(art)

        print(f"     归一化: {len(new_articles)} 篇", flush=True)

    finally:
        await client.close()

    # 时效性过滤（补全用7天窗口，但优先近期的）
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    new_articles_filtered = [
        a for a in new_articles
        if not a.published_at or a.published_at >= cutoff
    ]
    if len(new_articles_filtered) < len(new_articles):
        print(f"    ⏰ 7天内: {len(new_articles_filtered)}/{len(new_articles)} 篇", flush=True)
        new_articles = new_articles_filtered

    # 合并 + 全局去重
    all_articles = articles + new_articles
    all_articles = dedup_by_url(all_articles)
    all_articles = dedup_by_title(all_articles, similarity_threshold=0.85)

    added = len(all_articles) - len(articles)
    print(f"\n  ✅ 补全完成，新增 {added} 篇", flush=True)

    # 重新统计
    new_counts: dict[str, int] = {}
    for a in all_articles:
        cat = a.category or "unknown"
        new_counts[cat] = new_counts.get(cat, 0) + 1
    print(f"  📊 补全后各分类:", flush=True)
    for cat, cnt in sorted(new_counts.items(), key=lambda x: -x[1]):
        print(f"    {cat:15s} {cnt:3d} 条", flush=True)

    return all_articles
