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
from app.pipeline.history import filter_seen_events, load_recent_event_titles
from app.utils.timeutil import report_today
from app.agents.base import LLMClient
from app.agents.pipeline import AnalystAgent, ChiefEditorAgent
from app.agents.factcheck import FactCheckerAgent, ground_key_data
from app.report.renderer import PDFRenderer
from app.utils.runlog import RunReport
from app.search.anysearch import AnySearchClient


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
    # 架构评审 #13: 时效窗口与过滤阈值改由 yaml 配置驱动
    ss = strategy["search_strategy"]
    time_window = ss["defaults"].get("time_window_hours", 24)
    filtering = ss.get("filtering", {})
    # max_age_hours 优先用 filtering 配置，缺省回退到 time_window_hours
    max_age = filtering.get("max_age_hours", time_window)

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
        articles = await collector.collect(
            queries, batch_id="daily_run", tavily_top_n=tavily_n,
            max_age_hours=max_age,
            url_dedup=filtering.get("url_dedup", True),
            title_dedup=filtering.get("title_dedup", True),
            title_similarity_threshold=filtering.get("title_similarity_threshold", 0.85),
            min_content_length=filtering.get("min_content_length", 0),
        )
        path = collector.save_to_file(articles, f"raw_{'test' if test_mode else 'full'}_{int(time.time())}.json", date_str=today)
        print(f"\n  ✅ 采集完成: {len(articles)} 篇", flush=True)
        print(f"  💾 保存到: {path}", flush=True)
        return articles, dict(collector.last_stats)
    finally:
        await collector.close()


def load_from_file(path: str) -> list[RawNewsArticle]:
    print(f"\n  📂 从文件加载: {path}", flush=True)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    articles = [RawNewsArticle.model_validate(d) for d in data]
    print(f"  ✅ 加载: {len(articles)} 篇", flush=True)
    return articles




async def do_extract_fulltexts(
    selected_events, article_map, api_key,
    max_articles: int = 2, max_chars: int = 3000, concurrency: int = 4,
) -> dict:
    """架构评审 #7: 为入选事件提取 Top 文章原文（best-effort）。"""
    client = AnySearchClient(api_key=api_key)
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, list] = {}

    async def fetch(url: str) -> str:
        async with sem:
            try:
                md = await client.extract(url)
                return (md or "").strip()[:max_chars]
            except Exception as e:
                print(f"  ⚠️ 全文提取失败 {url}: {e}", flush=True)
                return ""

    try:
        for e in selected_events:
            metas = [article_map[a] for a in e.article_ids[:max_articles] if a in article_map]
            if not metas:
                continue
            results = await asyncio.gather(*[fetch(str(m.url)) for m in metas])
            texts = [
                {"domain": m.source_domain, "url": str(m.url), "fulltext": r}
                for m, r in zip(metas, results) if r
            ]
            if texts:
                out[e.event_id] = texts
    finally:
        await client.close()
    return out


def _balanced_select_events(events, article_map, max_total=18):
    """均衡选择事件（架构评审 #10 重写）。

    - 分类口径: 用事件关联文章的 category 多数投票（来自查询打标），
      不再用标题关键词猜测，避免与 LLM 分类口径冲突；
    - 每个分类保底 2 个（预算 >=12 时），其余按热度（文章数、来源数）补足；
    - 用 event_id 集合去重，避免 O(n²) 的模型相等性比较。
    """
    from collections import Counter

    def ev_cat(e) -> str:
        cats = Counter()
        for aid in e.article_ids:
            art = article_map.get(aid)
            if art and art.category:
                cats[art.category] += 1
        return cats.most_common(1)[0][0] if cats else "industry"

    by_cat: dict[str, list] = {}
    for e in events:
        by_cat.setdefault(ev_cat(e), []).append(e)

    heat = lambda e: (e.article_count, len(e.source_domains))
    selected: list = []
    sel_ids: set[str] = set()
    per_cat_min = 2 if max_total >= 12 else 1

    for cat in ["model_tech", "funding", "policy", "research", "industry"]:
        for e in sorted(by_cat.get(cat, []), key=heat, reverse=True)[:per_cat_min]:
            if len(selected) >= max_total:
                break
            selected.append(e)
            sel_ids.add(e.event_id)

    remaining = sorted(
        (e for e in events if e.event_id not in sel_ids),
        key=heat,
        reverse=True,
    )
    for e in remaining:
        if len(selected) >= max_total:
            break
        selected.append(e)

    return selected


def do_cluster(articles):
    """步骤2：聚类。"""
    print("\n" + "=" * 60)
    print("  STEP 2 / 4  事件聚类")
    print("=" * 60, flush=True)

    events = cluster_articles(articles, title_threshold=0.6)
    multi = [e for e in events if e.article_count > 1]
    print(f"  ✅ {len(articles)} 篇 → {len(events)} 个事件（{len(multi)}个多源）", flush=True)
    return events


async def do_agent_analysis(events, article_map, max_events=6, concurrency=3, fulltexts_map=None):
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
        fulltexts_map=fulltexts_map,
    )

    if not analyzed:
        print("  ❌ 没有有效的分析结果", flush=True)
        sys.exit(1)

    # 事实核查（架构评审 #6）
    checker = FactCheckerAgent(llm=llm)
    quality_flags: list[str] = []
    for event, analysis in analyzed:
        texts: list[str] = []
        for ft in (fulltexts_map or {}).get(event.event_id, []):
            texts.append(ft["fulltext"])
        for aid in event.article_ids[:6]:
            art = article_map.get(aid)
            if art:
                texts.append(art.snippet)
        source_text = "\n".join(texts)

        # 6a. 确定性溯源: key_data 数值必须字面出现在来源文本中
        kd = analysis.get("key_data") or []
        if kd:
            grounded, dropped = ground_key_data(kd, source_text)
            if dropped:
                analysis["key_data"] = grounded
                quality_flags.append(
                    f"key_data 无来源剔除 [{analysis.get('title', '')[:25]}]: {dropped}"
                )

        # 6b. LLM 复核: 高分条目(>=85)二次交叉核对
        if analysis.get("importance_score", 0) >= 85 and source_text:
            vr = checker.verify(analysis, source_text)
            if vr:
                if vr.corrected_details:
                    analysis["details"] = vr.corrected_details
                    quality_flags.append(f"复核修订 details [{analysis.get('title', '')[:25]}]")
                for c in vr.unsupported_claims:
                    quality_flags.append(f"无依据表述 [{analysis.get('title', '')[:25]}]: {c}")

    if quality_flags:
        print(f"\n  🛡️ 事实核查: {len(quality_flags)} 条标记", flush=True)
        for fl in quality_flags[:8]:
            print(f"     - {fl}", flush=True)

    chief = ChiefEditorAgent(llm=llm)
    today = report_today()
    report = chief.finalize(analyzed, report_date=today, article_map=article_map)
    report.quality_flags = quality_flags

    print(f"\n  ✅ 总编辑完成", flush=True)
    print(f"     总条目: {report.total_items}", flush=True)
    print(f"     总字数: {report.total_word_count}", flush=True)
    for s in report.sections:
        print(f"     {s.section_name}: {s.item_count} 条", flush=True)

    return report, dict(llm.stats)


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
    parser.add_argument("--max-events", type=int, default=None, help="分析事件数上限 (默认: --test 6 / 否则 18)")
    parser.add_argument("--concurrency", type=int, default=3, help="Agent并发数 (默认3)")
    parser.add_argument("--no-agent", action="store_true", help="跳过Agent")
    parser.add_argument("--no-extract", action="store_true", help="跳过原文全文提取(省额度)")
    parser.add_argument("--backfill", action="store_true", help="空栏目自动补全近7天数据")
    parser.add_argument("--no-pdf", action="store_true", help="跳过PDF")
    parser.add_argument("--queries-per-batch", type=int, default=0, help="每批次最多查询数(0=全部)")
    parser.add_argument("--tavily-n", type=int, default=20, help="Tavily补充查询数")
    args = parser.parse_args()

    start_time = time.time()
    today = report_today()
    rr = RunReport(mode="test" if args.test else ("full" if args.full else "from_file"))

    print("🚀 AI 财经日报生成器", flush=True)
    print(f"📅 日期: {today}", flush=True)

    ok = True
    try:
        # Step 1: 采集
        if args.from_file:
            articles = load_from_file(args.from_file)
            query_stats = {"engine": "from_file", "articles_loaded": len(articles)}
        elif args.test or args.full:
            articles, query_stats = await collect_articles(
                test_mode=args.test, max_per_batch=args.queries_per_batch,
                tavily_n=args.tavily_n, today=today,
            )
        else:
            print("⚠️  请指定 --test / --full / --from-file", flush=True)
            sys.exit(1)
        rr.set("query_stats", query_stats)

        # Step 1.5: 空栏目补全（可选）
        if args.backfill:
            articles = await backfill_empty_categories(articles, load_api_key())
        rr.stage("collect")
        rr.set("articles", len(articles))

        # 护栏（架构评审 #15）: 文章数过少视为搜索异常，终止而非产出空报
        if len(articles) < 5:
            rr.flag(f"文章数过少({len(articles)})，疑似搜索异常")
            print(f"  ❌ 文章数过少（{len(articles)} 篇），疑似搜索异常，终止本次运行", flush=True)
            sys.exit(1)

        # Step 2: 聚类
        events = do_cluster(articles)
        article_map = build_article_map(articles)

        # Step 2.5: 跨天去重（事件记忆：近3天已报道事件不再入选）
        recent_titles = load_recent_event_titles(days=3, exclude_date=today)
        if recent_titles:
            events, seen = filter_seen_events(events, recent_titles)
            if seen:
                print(f"  🧠 跨天去重: 过滤 {len(seen)} 个近3天已报道事件", flush=True)
                for e, (d, past_title, sim) in seen[:5]:
                    print(f"     - [{d}] {e.canonical_title[:38]} (相似度 {sim:.2f})", flush=True)
        else:
            print("  🧠 跨天去重: 无历史事件索引，跳过", flush=True)
        rr.stage("cluster")
        rr.set("events", len(events))

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

        # Step 2.8: 全文提取（架构评审 #7，best-effort）
        fulltexts_map: dict = {}
        effective_max_events = args.max_events or (6 if args.test else 18)
        selected_events = _balanced_select_events(events, article_map, effective_max_events)
        print(f"  🎯 均衡选择 {len(selected_events)} 个事件用于分析", flush=True)
        if not args.no_extract:
            print("  📖 全文提取: 入选事件 Top 文章原文...", flush=True)
            fulltexts_map = await do_extract_fulltexts(
                selected_events, article_map, load_api_key()
            )
            print(f"     成功提取 {len(fulltexts_map)}/{len(selected_events)} 个事件的原文", flush=True)
        rr.stage("extract")
        rr.set("fulltext_events", len(fulltexts_map))

        # Step 3: Agent 分析 + 事实核查 + 总编
        report, llm_stats = await do_agent_analysis(
            selected_events, article_map,
            max_events=None,
            concurrency=args.concurrency,
            fulltexts_map=fulltexts_map,
        )
        rr.stage("analyze")
        rr.set("llm_stats", llm_stats)
        rr.set("quality_flags", report.quality_flags)

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
        rr.stage("pdf")

        elapsed = time.time() - start_time
        print("\n" + "=" * 60, flush=True)
        print(f"  ✅ 全部完成！耗时 {elapsed:.1f} 秒", flush=True)
        print(f"  📕 {pdf_path}", flush=True)
        print("=" * 60, flush=True)
    except SystemExit:
        ok = False
        raise
    except Exception as e:
        ok = False
        rr.flag(f"运行异常: {type(e).__name__}: {e}")
        raise
    finally:
        # 架构评审 #16: 运行报告落盘（成功/失败都写）
        try:
            rf = rr.finish(f"data/reports/{today}", ok=ok)
            print(f"\n  📊 运行报告: {rf}", flush=True)
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
