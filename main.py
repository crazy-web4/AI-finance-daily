#!/usr/bin/env python3
"""
AI 财经日报 - 主入口
用法:
  python main.py collect --test          # 测试模式：少量查询
  python main.py collect --batch industry_trends  # 只跑某个批次
  python main.py collect --all           # 全量采集（约500条查询，较久）
  python main.py info                    # 查看策略信息
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 确保能导入 app 包
sys.path.insert(0, str(Path(__file__).parent))

from app.search.queries import load_strategy, generate_queries, get_batch_summary
from app.pipeline.collector import NewsCollector


def load_api_key() -> str:
    """从 .env 加载 API key。"""
    load_dotenv()
    key = os.environ.get("ANYSEARCH_API_KEY", "")
    if not key:
        print("❌ 未找到 ANYSEARCH_API_KEY，请在 .env 中配置。")
        sys.exit(1)
    return key


def cmd_info(args: argparse.Namespace) -> None:
    """查看搜索策略信息。"""
    strategy = load_strategy()
    queries = generate_queries(strategy)
    summary = get_batch_summary(queries)

    print("=" * 50)
    print("  AI 财经日报 · 搜索策略")
    print("=" * 50)
    print(f"  策略版本: {strategy['search_strategy']['version']}")
    print(f"  总查询数: {len(queries)}")
    print()
    print("  各批次:")
    for bid, cnt in summary.items():
        defaults = strategy["search_strategy"]["defaults"]
        max_r = defaults["max_results_per_query"]
        est = cnt * max_r
        print(f"    {bid:20s}  {cnt:4d} 条查询  ≈ {est} 篇结果")
    print()
    print(f"  预估总结果（上限）: {len(queries) * defaults['max_results_per_query']} 篇")
    print("=" * 50)


async def cmd_collect_async(args: argparse.Namespace) -> None:
    """执行采集。"""
    api_key = load_api_key()
    strategy = load_strategy()

    if args.test:
        print("🧪 测试模式：每批次取 2 条查询")
        queries = generate_queries(strategy, max_per_batch=2)
    elif args.batch:
        print(f"🎯 指定批次：{args.batch}")
        # 过滤只保留指定批次
        all_queries = generate_queries(strategy)
        queries = [q for q in all_queries if q.batch_id == args.batch]
        if not queries:
            print(f"❌ 未找到批次 '{args.batch}'")
            print(f"   可用批次: {', '.join(get_batch_summary(all_queries).keys())}")
            sys.exit(1)
    elif args.all:
        print("🔥 全量模式：执行全部查询（约 500 条，需几分钟）")
        queries = generate_queries(strategy)
    else:
        print("⚠️  请指定采集模式：--test / --batch <name> / --all")
        sys.exit(1)

    summary = get_batch_summary(queries)
    print(f"  共 {len(queries)} 条查询")
    for bid, cnt in summary.items():
        print(f"    {bid}: {cnt} 条")

    print("\n🚀 开始采集...")
    collector = NewsCollector(api_key=api_key)
    try:
        articles = await collector.collect(queries, batch_id="cli_run")
        print(f"\n✅ 采集完成: {len(articles)} 篇（去重后）")

        # 统计
        langs = {}
        rels = {}
        cats = {}
        for a in articles:
            langs[a.language] = langs.get(a.language, 0) + 1
            rels[a.source_reliability] = rels.get(a.source_reliability, 0) + 1
            c = a.category or "unknown"
            cats[c] = cats.get(c, 0) + 1

        print(f"\n  📊 统计:")
        print(f"    语言: {langs}")
        print(f"    来源等级: {rels}")
        print(f"    分类: {cats}")

        # 保存
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        mode = "test" if args.test else (args.batch or "full")
        fname = f"raw_{mode}_{ts}.json"
        path = collector.save_to_file(articles, fname)
        print(f"\n  💾 已保存: {path}")

    finally:
        await collector.close()


def cmd_collect(args: argparse.Namespace) -> None:
    asyncio.run(cmd_collect_async(args))


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 财经日报")
    sub = parser.add_subparsers(dest="command", required=True)

    # info
    p_info = sub.add_parser("info", help="查看搜索策略信息")
    p_info.set_defaults(func=cmd_info)

    # collect
    p_collect = sub.add_parser("collect", help="执行新闻采集")
    p_collect.add_argument("--test", action="store_true", help="测试模式（少量查询）")
    p_collect.add_argument("--batch", type=str, help="只运行指定批次")
    p_collect.add_argument("--all", action="store_true", help="全量采集")
    p_collect.set_defaults(func=cmd_collect)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
