"""
新闻采集器
职责: 调用 AnySearch 搜索 → 归一化 → URL去重 → 标题去重 → 输出候选池

数据流:
  SearchQuery[] → AnySearchClient → SearchResultItem[]
    → normalize → RawNewsArticle[]
    → url_dedup → title_dedup
    → 候选池 (JSON 输出到 data/raw/)
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, Field, HttpUrl

from app.search.anysearch import (
    AnySearchClient,
    SearchQuery,
    SearchResultItem,
    TavilyClient,
)
# 架构评审 #12: 模型单一事实源在 schemas；此处 re-export 保持下游导入路径不变
from app.schemas.models import (  # noqa: E402
    RawNewsArticle,
    SourceReliability,
    normalize_url as _normalize_url,
)



# 来源分级（按域名后缀匹配）
TIER1_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "meta.ai",
    "nvidia.com", "arxiv.org",
}
TIER1_SUFFIXES = {".gov", ".gov.cn", ".gov.uk", ".gov.au", ".europa.eu"}

TIER2_DOMAINS = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com",
    "nature.com", "science.org", "technologyreview.com",
    "cac.gov.cn", "sec.gov", "ftchinese.com",
}

TIER3_DOMAINS = {
    "techcrunch.com", "theverge.com", "wired.com",
    "arstechnica.com", "venturebeat.com", "zdnet.com",
    "engadget.com", "cnet.com",
    "36kr.com", "geekpark.net", "leiphone.com",
    "jiqizhixin.com", "syncedreview.com",
}




# ═══════════════════════════════════════════════════════
# 来源可靠性分级
# ═══════════════════════════════════════════════════════

def _rate_reliability(domain: str) -> str:
    d = domain.lower().replace("www.", "")

    if d in TIER1_DOMAINS:
        return "high"
    for suffix in TIER1_SUFFIXES:
        if d.endswith(suffix):
            return "high"

    if d in TIER2_DOMAINS:
        return "medium"

    if d in TIER3_DOMAINS:
        return "low"

    return "unknown"


# ═══════════════════════════════════════════════════════
# 语言检测（简易版）
# ═══════════════════════════════════════════════════════

def _detect_language(text: str) -> str:
    """简易中/英文检测：看中文字符占比。"""
    if not text:
        return "unknown"
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    ratio = cn_chars / max(len(text), 1)
    if ratio > 0.2:
        return "zh"
    return "en"


# ═══════════════════════════════════════════════════════
# 归一化
# ═══════════════════════════════════════════════════════

def normalize_result(item: SearchResultItem, query: SearchQuery | None = None) -> RawNewsArticle:
    """把搜索结果归一化为 RawNewsArticle。"""
    domain = item.source_domain.lower().replace("www.", "")
    lang = _detect_language(item.title + " " + item.snippet)

    return RawNewsArticle(
        article_id=RawNewsArticle.make_id(str(item.url)),
        title=item.title.strip(),
        url=item.url,
        source_domain=domain,
        source_name=item.source_name,
        snippet=item.snippet.strip(),
        content=item.content or item.snippet.strip(),
        published_at=item.published_at,
        fetched_at=item.fetched_at,
        language=lang,
        category=query.category if query else None,
        search_query=query.query if query else item.query_origin,
        search_batch=query.batch_id if query else None,
        source_reliability=_rate_reliability(domain),
    )


# ═══════════════════════════════════════════════════════
# 去重
# ═══════════════════════════════════════════════════════

def dedup_by_url(articles: list[RawNewsArticle]) -> list[RawNewsArticle]:
    """
    按 URL 去重。
    同一 URL 出现多次时，合并：保留 snippet 更长的那篇，result_count 累加。
    """
    seen: dict[str, RawNewsArticle] = {}

    for art in articles:
        aid = art.article_id
        if aid not in seen:
            seen[aid] = art
        else:
            existing = seen[aid]
            # 保留内容更丰富的版本
            if len(art.snippet) > len(existing.snippet):
                existing.snippet = art.snippet
                existing.content = art.content or existing.content
            # 累计出现次数
            existing.result_count += 1
            # 如果 category 不同，保留第一个（也可以合并）
            if not existing.search_query and art.search_query:
                existing.search_query = art.search_query

    return list(seen.values())


def _normalize_title(title: str) -> str:
    """标题归一化：去标点、转小写、去空格，用于去重比较。"""
    t = title.lower()
    t = re.sub(r'[^\w\u4e00-\u9fff]', '', t)
    return t


def dedup_by_title(
    articles: list[RawNewsArticle],
    similarity_threshold: float = 0.9,
) -> list[RawNewsArticle]:
    """
    按标题相似度去重（基于字符 n-gram Jaccard 相似度）。
    相似的标题只保留 source_reliability 更高的那篇。
    """
    if len(articles) <= 1:
        return articles

    # 预计算归一化标题的字符 bigram 集合
    ngrams_list = []
    for art in articles:
        nt = _normalize_title(art.title)
        if len(nt) < 2:
            ngrams = {nt}
        else:
            ngrams = {nt[i:i+2] for i in range(len(nt)-1)}
        ngrams_list.append(ngrams)

    # 可靠性排序的权重
    rel_weight = {"high": 3, "medium": 2, "low": 1, "unknown": 0}

    keep = [True] * len(articles)

    for i in range(len(articles)):
        if not keep[i]:
            continue
        ni = ngrams_list[i]
        if not ni:
            continue

        for j in range(i + 1, len(articles)):
            if not keep[j]:
                continue
            nj = ngrams_list[j]
            if not nj:
                continue

            # Jaccard 相似度
            inter = len(ni & nj)
            union = len(ni | nj)
            sim = inter / union if union > 0 else 0

            if sim >= similarity_threshold:
                # 保留可靠性更高 / 内容更长的
                wi = rel_weight.get(articles[i].source_reliability, 0)
                wj = rel_weight.get(articles[j].source_reliability, 0)
                if wi > wj:
                    keep[j] = False
                elif wj > wi:
                    keep[i] = False
                    break
                else:
                    # 可靠性相同，保留内容更长的
                    if len(articles[i].snippet) >= len(articles[j].snippet):
                        keep[j] = False
                    else:
                        keep[i] = False
                        break

    return [articles[i] for i in range(len(articles)) if keep[i]]


# ═══════════════════════════════════════════════════════
# 采集器主类
# ═══════════════════════════════════════════════════════

class NewsCollector:
    """
    新闻采集器。

    用法:
        collector = NewsCollector(api_key="...")
        articles = await collector.collect(queries, batch_id="test")
        await collector.save_to_file(articles, "data/raw/test.json")
    """

    def __init__(
        self,
        api_key: str | None = None,
        tavily_api_key: str | None = None,
        output_dir: str = "data/raw",
        use_tavily: bool = True,
    ) -> None:
        import os
        self.client = AnySearchClient(api_key=api_key)
        self.use_tavily = use_tavily
        if use_tavily:
            tav_key = tavily_api_key or os.environ.get("TAVILY_API_KEY", "")
            self.tavily = TavilyClient(api_key=tav_key) if tav_key else None
        else:
            self.tavily = None
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.last_stats: dict = {}

    async def collect(
        self,
        queries: list[SearchQuery],
        batch_id: str | None = None,
        url_dedup: bool = True,
        title_dedup: bool = True,
        tavily_top_n: int = 5,
        max_age_hours: int = 24,
        title_similarity_threshold: float = 0.85,
        min_content_length: int = 0,
    ) -> list[RawNewsArticle]:
        """
        执行一次完整采集：搜索 → 归一化 → 去重。
        双引擎：AnySearch + Tavily（可选）
        """
        import asyncio

        # 1. AnySearch 批量搜索
        batch_resp = await self.client.search_batch(queries, batch_id=batch_id)

        # 架构评审 #15/#16: 搜索层告警与统计
        self.last_stats = {
            "engine": "anysearch",
            "total_queries": batch_resp.total_queries,
            "success_queries": batch_resp.success_queries,
            "failed_queries": batch_resp.failed_queries,
            "unique_results": batch_resp.unique_results,
        }
        if batch_resp.total_queries > 0 and batch_resp.success_queries == 0:
            raise RuntimeError(
                f"AnySearch 全部 {batch_resp.total_queries} 条查询失败（疑似 key 失效/网络故障），终止采集"
            )
        if batch_resp.failed_queries:
            print(
                f"  ⚠️ AnySearch 失败 {batch_resp.failed_queries}/{batch_resp.total_queries} 条查询",
                flush=True,
            )

        # 2. 归一化 AnySearch 结果
        articles: list[RawNewsArticle] = []
        query_map = {q.query: q for q in queries}

        for resp in batch_resp.responses:
            q = query_map.get(resp.query)
            for item in resp.results:
                art = normalize_result(item, query=q)
                articles.append(art)

        # 3. Tavily 补充搜索（按分类均衡选取 + 时间限定）
        if self.tavily:
            sem = asyncio.Semaphore(5)

            async def tavily_search(q, time_range="day"):
                async with sem:
                    items = await self.tavily.search(
                        q.query,
                        max_results=min(q.max_results, 7),
                        search_depth="advanced",
                        time_range=time_range,
                    )
                    return (q, items)

            # 按分类分组，每个分类选代表性查询，保证覆盖均衡
            by_cat: dict[str, list[SearchQuery]] = {}
            for q in queries:
                cat = q.category or "unknown"
                if cat not in by_cat:
                    by_cat[cat] = []
                by_cat[cat].append(q)

            # 每个分类取 ceil(tavily_top_n / categories) 条
            import math
            cats = list(by_cat.keys())
            per_cat = max(1, math.ceil(tavily_top_n / max(len(cats), 1)))

            supplement_queries: list[SearchQuery] = []
            for cat in cats:
                cat_queries = by_cat[cat][:per_cat]
                supplement_queries.extend(cat_queries)
            # 取前 tavily_top_n 条
            supplement_queries = supplement_queries[:tavily_top_n]

            print(f"  🔍 Tavily 补充搜索（{len(supplement_queries)} 条，覆盖 {len(cats)} 个分类）", flush=True)
            tasks = [tavily_search(q) for q in supplement_queries]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            tavily_count = 0
            for r in results:
                if isinstance(r, Exception):
                    continue
                q, items = r
                for item in items:
                    art = normalize_result(item, query=q)
                    articles.append(art)
                    tavily_count += 1

            print(f"     Tavily 新增: {tavily_count} 篇", flush=True)

        # 3. 时效性过滤（架构评审 #2：确定性规则）
        #    - 有发布时间且早于 cutoff 的 → 丢弃（明确旧闻）
        #    - 近期 / 无发布时间的 → 保留
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        dated_recent = [a for a in articles if a.published_at and a.published_at >= cutoff]
        dated_older = [a for a in articles if a.published_at and a.published_at < cutoff]
        undated = [a for a in articles if not a.published_at]
        articles = dated_recent + undated
        print(
            f"  ⏰ 时效过滤: 近期 {len(dated_recent)} / 无时间 {len(undated)} / 丢弃旧闻 {len(dated_older)}",
            flush=True,
        )

        # 3.5 内容长度过滤（架构评审 #13：filtering.min_content_length 接线）
        if min_content_length > 0:
            before = len(articles)
            articles = [a for a in articles if len(a.snippet) >= min_content_length]
            print(
                f"  📏 内容长度过滤(≥{min_content_length}): 保留 {len(articles)} / 丢弃 {before - len(articles)}",
                flush=True,
            )

        # 4. 去重（架构评审 #13：url_dedup / title_dedup 独立开关）
        if url_dedup:
            articles = dedup_by_url(articles)
        if title_dedup:
            articles = dedup_by_title(articles, similarity_threshold=title_similarity_threshold)

        # 4. 按来源可靠性 + 出现次数 排序
        rel_weight = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
        articles.sort(
            key=lambda a: (
                rel_weight.get(a.source_reliability, 0),
                a.result_count,
                len(a.snippet),
            ),
            reverse=True,
        )

        return articles

    def save_to_file(
        self,
        articles: list[RawNewsArticle],
        filename: str | None = None,
        date_str: str | None = None,
    ) -> Path:
        """保存为 JSON 文件（按日期归档）。"""
        if not filename:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"raw_articles_{ts}.json"

        # 按日期建子目录
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_dir = self.output_dir / date_str
        out_dir.mkdir(parents=True, exist_ok=True)

        path = out_dir / filename
        data = [json.loads(a.model_dump_json()) for a in articles]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        return path

    async def close(self) -> None:
        await self.client.close()
        if self.tavily:
            await self.tavily.close()
