"""
查询生成器
接口编号: IF-002 的实现
职责: 读取 search_strategy.yaml，生成实际的 SearchQuery 列表
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from app.search.anysearch import SearchQuery


def load_strategy(config_path: str | Path = "config/search_strategy.yaml") -> dict:
    """加载搜索策略配置。"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _add_time_qualifier(query: str, category: str | None = None) -> str:
    """给查询词注入时间限定，提升时效性。时间词全部按当前日期动态生成。"""
    now = datetime.now()
    year = now.strftime("%Y")
    last_year = str(int(year) - 1)
    month_en = now.strftime("%B %Y")
    month_name_lower = now.strftime("%B").lower()
    month_short = now.strftime("%Y年%m月")
    today = now.strftime("%Y-%m-%d")

    q_lower = query.lower()

    # 中文查询加中文时间限定
    has_chinese = any('一' <= c <= '鿿' for c in query)
    if has_chinese:
        # 避免重复添加
        if any(kw in query for kw in ['最新', '今日', '本周', year, last_year]):
            return query
        if category in ('funding', 'industry'):
            return f"{query} {month_short} 最新"
        return f"{query} 最新"

    # 英文查询加英文时间限定
    if any(kw in q_lower for kw in ['today', 'latest', 'new', 'this week', year, last_year, month_name_lower]):
        return query

    # 按分类加不同的时间限定
    if category in ('funding',):
        return f"{query} {month_en} latest"
    elif category in ('policy',):
        # 查询词已含 update 时只追加年份，避免 "update 2026 update" 重复
        return f"{query} {year}" if "update" in q_lower else f"{query} {year} update"
    elif category in ('research',):
        return f"{query} {year}"
    else:
        return f"{query} latest news {today}"


def generate_queries(
    strategy: dict,
    max_per_batch: int | None = None,
    enabled_only: bool = True,
) -> list[SearchQuery]:
    """
    根据策略配置生成全部搜索查询。

    Args:
        strategy: 从 load_strategy() 得到的配置字典
        max_per_batch: 每个批次最多取多少条查询（用于测试/抽样）
        enabled_only: 是否只生成启用的批次

    Returns:
        SearchQuery 列表（已打标 category / batch_id）
    """
    defaults = strategy["search_strategy"]["defaults"]
    batches = strategy["search_strategy"]["batches"]
    all_queries: list[SearchQuery] = []

    for batch in batches:
        if enabled_only and not batch.get("enabled", True):
            continue

        batch_id = batch["batch_id"]
        max_results = batch.get("max_results", defaults["max_results_per_query"])
        depth = batch.get("depth", defaults["depth"])
        language = batch.get("language", defaults["language"])

        batch_queries: list[SearchQuery] = []

        if batch.get("strategy") == "cartesian":
            # 公司 × 事件类型 笛卡尔积
            companies = batch.get("companies", [])
            event_types = batch.get("event_types", [])
            for company in companies:
                name = company["name"]
                aliases = company.get("aliases", [name])
                primary_name = aliases[0] if aliases else name

                for evt in event_types:
                    q_text = f"{primary_name} {evt['keyword']}"
                    q_text = _add_time_qualifier(q_text, evt.get("category", batch_id))
                    batch_queries.append(SearchQuery(
                        query=q_text,
                        max_results=max_results,
                        category=evt.get("category", batch_id),
                        batch_id=batch_id,
                    ))

        elif batch.get("strategy") == "list":
            # 直接使用查询列表
            for q in batch.get("queries", []):
                q_text = _add_time_qualifier(q["query"], q.get("category", batch_id))
                batch_queries.append(SearchQuery(
                    query=q_text,
                    max_results=max_results,
                    category=q.get("category", batch_id),
                    batch_id=batch_id,
                ))

        # 截断（测试用）
        if max_per_batch and len(batch_queries) > max_per_batch:
            batch_queries = batch_queries[:max_per_batch]

        all_queries.extend(batch_queries)

    return all_queries


def get_batch_summary(queries: list[SearchQuery]) -> dict[str, int]:
    """统计各批次查询数量。"""
    summary: dict[str, int] = {}
    for q in queries:
        bid = q.batch_id or "unknown"
        summary[bid] = summary.get(bid, 0) + 1
    return summary


if __name__ == "__main__":
    strategy = load_strategy()
    queries = generate_queries(strategy)
    print(f"总查询数: {len(queries)}")
    print("各批次:")
    for bid, count in get_batch_summary(queries).items():
        print(f"  {bid}: {count}")
