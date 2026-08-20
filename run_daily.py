#!/usr/bin/env python3
"""
AI 财经日报 · 端到端生成脚本
用法:
  python run_daily.py --test                    # 采集测试 + 分析6个 + PDF
  python run_daily.py --from-file <json>        # 从已有采集数据开始
  python run_daily.py --from-file <json> --max-events 8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from app.search.queries import load_strategy, generate_queries
from app.pipeline.collector import NewsCollector, RawNewsArticle
from app.pipeline.cluster import cluster_articles, build_article_map
from app.pipeline.backfill import backfill_empty_categories
from app.agents.base import LLMClient
from app.agents.pipeline import AnalystAgent, ChiefEditorAgent
from app.report.renderer import PDFRenderer


def load_api_key() -> str:
    import os
    key = os.environ.get("ANYSEARCH_API_KEY", "")
    if not key:
        print("❌ 未找到 ANYSEARCH_API_KEY")
        sys.exit(1)
    return key


async def collect_articles(test_mode: bool, max_per_batch: int = 0, tavily_n: int = 20, today: str = "") -> list[RawNewsArticle]:
    """步骤1：采集新闻。"""
    print("\n" + "=" * 60)
    print("  STEP 1 / 4  新闻采集")
    print("=" * 60, flush=True)

    api_key = load_api_key()
    strategy = load_strategy()

    if test_mode:
        # --queries-per-batch 未指定时默认每批 2 条（与 main.py collect --test 对齐），避免静默全量
        effective_per_batch = max_per_batch if max_per_batch > 0 else 2
        queries = generate_queries(strategy, max_per_batch=effective_per_batch)
        print(f"  测试模式: {len(queries)} 条查询（每批限 {effective_per_batch} 条）", flush=True)
    else:
        queries = generate_queries(strategy)
        print(f"  全量模式: {len(queries)} 条查询", flush=True)

    collector = NewsCollector(api_key=api_key)
    try:
        articles = await collector.collect(queries, batch_id="daily_run", tavily_top_n=tavily_n)
        path = collector.save_to_file(articles, f"raw_{'test' if test_mode else 'full'}_{int(time.time())}.json", date_str=today)
        print(f"\n  ✅ 采集完成: {len(articles)} 篇", flush=True)
        print(f"  💾 保存到: {path}", flush=True)
        return articles
    finally:
        await collector.close()


def load_from_file(path: str) -> list[RawNewsArticle]:
    print(f"\n  📂 从文件加载: {path}", flush=True)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    articles = [RawNewsArticle.model_validate(d) for d in data]
    print(f"  ✅ 加载: {len(articles)} 篇", flush=True)
    return articles




def _balanced_select_events(events, article_map, max_total=12):
    """均衡选择事件：每个分类至少选几个，其余按分数补。"""
    # 先按 category 分组（用 event_type_guess 和关键词粗略分）
    by_cat = {}
    for e in events:
        # 用分类关键词粗分
        title = e.canonical_title.lower()
        cat = "industry"
        if any(kw in title for kw in ["model", "gpt", "llm", "agent", "大模型", "模型", "开源", "推理"]):
            cat = "model_tech"
        elif any(kw in title for kw in ["funding", "融资", "估值", "收购", "并购", "投资", "raised", "series"]):
            cat = "funding"
        elif any(kw in title for kw in ["policy", "regulation", "行政令", "监管", "法案", "law", "act", "政策"]):
            cat = "policy"
        elif any(kw in title for kw in ["arxiv", "paper", "研究", "论文", "research", "breakthrough", "propose"]):
            cat = "research"

        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(e)

    # 每个分类先选 2 个（按文章数排序）
    selected = []
    per_cat_min = min(2, max_total // 6)
    for cat in ["top_news", "model_tech", "funding", "policy", "research", "industry"]:
        cat_events = sorted(
            by_cat.get(cat, []),
            key=lambda e: (e.article_count, len(e.source_domains)),
            reverse=True,
        )
        selected.extend(cat_events[:per_cat_min])

    # 剩下的按文章数补
    remaining = [e for e in events if e not in selected]
    remaining.sort(
        key=lambda e: (e.article_count, len(e.source_domains)),
        reverse=True,
    )
    for e in remaining:
        if len(selected) >= max_total:
            break
        selected.append(e)

    # 保持原顺序（按重要性）
    return selected[:max_total]


def do_cluster(articles):
    """步骤2：聚类。"""
    print("\n" + "=" * 60)
    print("  STEP 2 / 4  事件聚类")
    print("=" * 60, flush=True)

    events = cluster_articles(articles, title_threshold=0.6)
    multi = [e for e in events if e.article_count > 1]
    print(f"  ✅ {len(articles)} 篇 → {len(events)} 个事件（{len(multi)}个多源）", flush=True)
    return events


async def do_agent_analysis(events, article_map, max_events=6, concurrency=3):
    """步骤3：Agent 分析 + 总编。"""
    print("\n" + "=" * 60)
    print("  STEP 3 / 4  Agent 分析与编辑")
    print("=" * 60, flush=True)

    llm = LLMClient()
    analyst = AnalystAgent(llm=llm)
    analyzed = await analyst.analyze_batch_async(
        events, article_map,
        max_events=max_events,
        concurrency=concurrency,
    )

    if not analyzed:
        print("  ❌ 没有有效的分析结果", flush=True)
        sys.exit(1)

    chief = ChiefEditorAgent(llm=llm)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report = chief.finalize(analyzed, report_date=today, article_map=article_map)

    print(f"\n  ✅ 总编辑完成", flush=True)
    print(f"     总条目: {report.total_items}", flush=True)
    print(f"     总字数: {report.total_word_count}", flush=True)
    for s in report.sections:
        print(f"     {s.section_name}: {s.item_count} 条", flush=True)

    return report


async def do_pdf(report):
    """步骤4：PDF 渲染。"""
    print("\n" + "=" * 60)
    print("  STEP 4 / 4  PDF 渲染")
    print("=" * 60, flush=True)

    renderer = PDFRenderer()

    html_path = renderer.save_html(report)
    print(f"  📄 HTML: {html_path}", flush=True)

    pdf_path = await renderer.render_pdf(report)
    size_kb = pdf_path.stat().st_size / 1024
    print(f"  📕 PDF:  {pdf_path}", flush=True)
    print(f"     大小: {size_kb:.1f} KB", flush=True)
    return pdf_path


async def main():
    parser = argparse.ArgumentParser(description="AI 财经日报 · 端到端生成")
    parser.add_argument("--test", action="store_true", help="测试模式")
    parser.add_argument("--full", action="store_true", help="全量模式")
    parser.add_argument("--from-file", type=str, help="从已采集的JSON文件开始")
    parser.add_argument("--max-events", type=int, default=6, help="分析事件数上限 (默认6)")
    parser.add_argument("--concurrency", type=int, default=3, help="Agent并发数 (默认3)")
    parser.add_argument("--no-agent", action="store_true", help="跳过Agent")
    parser.add_argument("--backfill", action="store_true", help="空栏目自动补全近7天数据")
    parser.add_argument("--no-pdf", action="store_true", help="跳过PDF")
    parser.add_argument("--queries-per-batch", type=int, default=0, help="每批次最多查询数(0=全部)")
    parser.add_argument("--tavily-n", type=int, default=20, help="Tavily补充查询数")
    args = parser.parse_args()

    start_time = time.time()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("🚀 AI 财经日报生成器", flush=True)
    print(f"📅 日期: {today}", flush=True)

    # Step 1: 采集
    if args.from_file:
        articles = load_from_file(args.from_file)
    elif args.test or args.full:
        articles = await collect_articles(test_mode=args.test, max_per_batch=args.queries_per_batch, tavily_n=args.tavily_n, today=today)
    else:
        print("⚠️  请指定 --test / --full / --from-file", flush=True)
        sys.exit(1)

    # Step 1.5: 空栏目补全（可选）
    if args.backfill:
        articles = await backfill_empty_categories(articles, load_api_key())

    # Step 2: 聚类
    events = do_cluster(articles)
    article_map = build_article_map(articles)

    # 保存聚类结果
    events_path = Path(f"data/events/{today}/events_{int(time.time())}.json")
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(
            [json.loads(e.model_dump_json()) for e in events],
            f, ensure_ascii=False, indent=2, default=str,
        )

    if args.no_agent:
        print("\n⏭️  跳过 Agent", flush=True)
        return

    # Step 3: Agent
    # 均衡选择事件：每个分类至少选 2 个，其余按重要性补
    selected_events = _balanced_select_events(events, article_map, args.max_events)
    print(f"  🎯 均衡选择 {len(selected_events)} 个事件用于分析", flush=True)

    report = await do_agent_analysis(
        selected_events, article_map,
        max_events=None,
        concurrency=args.concurrency,
    )

    # 保存日报 JSON
    report_path = Path(f"data/reports/{today}/daily_{today}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))
    print(f"\n  💾 日报 JSON: {report_path}", flush=True)

    if args.no_pdf:
        print("\n⏭️  跳过 PDF", flush=True)
        return

    # Step 4: PDF
    pdf_path = await do_pdf(report)

    elapsed = time.time() - start_time
    print("\n" + "=" * 60, flush=True)
    print(f"  ✅ 全部完成！耗时 {elapsed:.1f} 秒", flush=True)
    print(f"  📕 {pdf_path}", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
