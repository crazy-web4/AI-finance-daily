#!/usr/bin/env python3
"""
AI 财经日报 - 主入口
=================================================
采集:
  python main.py collect --test / --batch <name> / --all
  python main.py info

产品化命令（第 10 批）:
  python main.py today | latest              # 打开今天/最近日报
  python main.py doctor [--strict]           # 一行健康检查
  python main.py web [--port 8910]           # 本地 Web 看板（含 RSS）
  python main.py export --date <d> --all     # 多格式导出 md/公众号/邮件/notion
  python main.py cards  --date <d> [--style dark] [--only top]
  python main.py feed  [--port 8911]         # RSS/Atom feed
  python main.py index build|rebuild         # SQLite 情报库
  python main.py query "OpenAI" [--days 30] [--category funding]
  python main.py stats [--since 2026-08-01]
  python main.py trend funding|headlines|topics [--weeks 4]
  python main.py weekly [--week-of 2026-08-31]
  python main.py watch [--dry-run]           # 异常告警
  python main.py subscribe --add "OpenAI" --categories funding | --list
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from app.search.queries import load_strategy, generate_queries, get_batch_summary
from app.pipeline.collector import NewsCollector
from app.storage.db import DEFAULT_DB_PATH
from app.storage.report_store import ReportStore


# ── info / collect（原有） ─────────────────────────────

def load_api_key() -> str:
    key = os.environ.get("ANYSEARCH_API_KEY", "")
    if not key:
        print("❌ 未找到 ANYSEARCH_API_KEY，请在 .env 中配置。")
        sys.exit(1)
    return key


def cmd_info(args) -> None:
    strategy = load_strategy()
    queries = generate_queries(strategy)
    summary = get_batch_summary(queries)
    print("=" * 50)
    print("  AI 财经日报 · 搜索策略")
    print("=" * 50)
    print(f"  策略版本: {strategy['search_strategy']['version']}")
    print(f"  总查询数: {len(queries)}")
    print()
    for bid, cnt in summary.items():
        max_r = strategy["search_strategy"]["defaults"]["max_results_per_query"]
        print(f"    {bid:20s}  {cnt:4d} 条查询  ≈ {cnt * max_r} 篇结果")
    print("=" * 50)


async def cmd_collect_async(args) -> None:
    api_key = load_api_key()
    strategy = load_strategy()
    if args.test:
        queries = generate_queries(strategy, max_per_batch=2)
        mode = "test"
    elif args.batch:
        all_q = generate_queries(strategy)
        queries = [q for q in all_q if q.batch_id == args.batch]
        if not queries:
            print(f"❌ 未找到批次 '{args.batch}'")
            sys.exit(1)
        mode = args.batch
    elif args.all:
        queries = generate_queries(strategy)
        mode = "full"
    else:
        print("⚠️  请指定 --test / --batch <name> / --all")
        sys.exit(1)

    ss = strategy["search_strategy"]
    filtering = ss.get("filtering", {})
    collector = NewsCollector(api_key=api_key)
    try:
        articles = await collector.collect(
            queries, batch_id="cli_run",
            max_age_hours=ss["defaults"].get("time_window_hours", 24),
            url_dedup=filtering.get("url_dedup", True),
            title_dedup=filtering.get("title_dedup", True),
            title_similarity_threshold=filtering.get("title_similarity_threshold", 0.85),
            min_content_length=filtering.get("min_content_length", 0),
        )
        print(f"\n✅ 采集完成: {len(articles)} 篇")
        from app.utils.timeutil import report_now
        ts = report_now().strftime("%Y%m%d_%H%M%S")
        path = collector.save_to_file(articles, f"raw_{mode}_{ts}.json")
        print(f"💾 已保存: {path}")
    finally:
        await collector.close()


def cmd_collect(args) -> None:
    asyncio.run(cmd_collect_async(args))


# ── 产品化命令 ─────────────────────────────────────────

def _store() -> ReportStore:
    return ReportStore("data/reports")


def _ensure_db() -> str:
    """确保情报库存在且已索引（query/trend/watch 前调用）。"""
    from app.storage.indexer import build_index
    if not Path(DEFAULT_DB_PATH).exists():
        print(f"ℹ️  情报库不存在，先构建索引 {DEFAULT_DB_PATH} ...")
        res = build_index(DEFAULT_DB_PATH, "data/reports")
        print(f"   已索引 {len(res['indexed'])} 期 / {res['total_items']} 条目")
    return DEFAULT_DB_PATH


def _resolve_date(date_arg: str | None):
    store = _store()
    if date_arg:
        art = store.find_on_date(date_arg)
        if art is None:
            print(f"❌ 找不到 {date_arg} 的日报")
            sys.exit(1)
        return store, date_arg
    art = store.latest_or_today()
    if art is None:
        print("❌ 暂无任何日报")
        sys.exit(1)
    return store, art.date


def cmd_today(args) -> None:
    from app.cli.shortcuts import cmd_today as _run
    sys.exit(_run(args, _store()))


def cmd_latest(args) -> None:
    from app.cli.shortcuts import cmd_latest as _run
    sys.exit(_run(args, _store()))


def cmd_doctor(args) -> None:
    from app.utils.doctor import run_checks, format_report, ERROR, WARN
    results = run_checks(base_dir=".")
    print(format_report(results))
    has_err = any(r.level == ERROR for r in results)
    has_warn = any(r.level == WARN for r in results)
    sys.exit(1 if (has_err or (args.strict and has_warn)) else 0)


def cmd_web(args) -> None:
    from app.web.server import serve
    serve(port=args.port, host=args.host)


def cmd_export(args) -> None:
    from app.exporter import run_all_exporters, ALL_EXPORTERS
    store, date = _resolve_date(args.date)
    report = store.load_report(date)
    if report is None:
        print(f"❌ 无法解析 {date} 的日报 JSON")
        sys.exit(1)
    out_dir = Path(args.out) / date if args.out else Path("data/reports") / date
    enabled = ALL_EXPORTERS if (args.format == "all" or args.all) else (args.format,)
    for fmt in enabled:
        if fmt not in ALL_EXPORTERS:
            print(f"❌ 未知格式: {fmt}（可选 {', '.join(ALL_EXPORTERS)}, all）")
            sys.exit(1)
    res = run_all_exporters(report, out_dir, enabled=enabled)
    for fmt, r in res.items():
        if r["ok"]:
            print(f"  ✅ {fmt:9s} {r['path']}")
        else:
            print(f"  ❌ {fmt:9s} {r['error']}")


def cmd_cards(args) -> None:
    from app.exporter.cards import generate_cards
    store, date = _resolve_date(args.date)
    report = store.load_report(date)
    out_dir = Path(args.out) / date / "cards" if args.out else Path("data/reports") / date / "cards"
    paths = generate_cards(report, out_dir, style=args.style, only=args.only)
    print(f"✅ 生成 {len(paths)} 张卡片 → {out_dir}")
    for p in paths[:5]:
        print(f"   {p}")
    if len(paths) > 5:
        print(f"   ... 其余 {len(paths) - 5} 张")


def cmd_feed(args) -> None:
    from app.web.feed import build_rss
    if args.port:
        from app.web.server import serve
        print(f"📡 Feed 地址: http://127.0.0.1:{args.port}/feed.xml （Atom: /atom.xml）")
        serve(port=args.port, host="127.0.0.1")
    else:
        out = Path("data/feed.xml")
        out.parent.mkdir(exist_ok=True)
        out.write_text(build_rss(_store()), encoding="utf-8")
        print(f"✅ RSS feed 已生成: {out}")
        print("   订阅器添加该文件路径，或用 `python main.py feed --port 8911` 起 HTTP 服务")


def cmd_index(args) -> None:
    from app.storage.indexer import build_index
    res = build_index(DEFAULT_DB_PATH, "data/reports", rebuild=(args.action == "rebuild"),
                      on_progress=lambda d, n: print(f"   索引 {d}: {n} 条"))
    print(f"✅ 完成: 新索引 {len(res['indexed'])} 期 / {res['total_items']} 条，"
          f"跳过 {len(res['skipped'])} 期，失败 {len(res['failed'])} 期")
    for f in res["failed"]:
        print(f"   ❌ {f['date']}: {f['error']}")
    print(f"   库路径: {res['db_path']}")


def cmd_query(args) -> None:
    from app.storage.query import search, format_results
    db = _ensure_db()
    rows = search(db, keyword=args.keyword, days=args.days, category=args.category,
                  importance_min=args.importance_min, limit=args.limit)
    print(format_results(rows, args.keyword))


def cmd_stats(args) -> None:
    from app.storage.query import stats, format_stats
    db = _ensure_db()
    print(format_stats(stats(db, since=args.since)))


def cmd_trend(args) -> None:
    from app.storage.db import connect
    from app.storage.trend import (funding_hotspots, headline_diff, topic_heat,
                                   format_funding, format_headline_diff, format_topics)
    db = _ensure_db()
    conn = connect(db)
    try:
        if args.kind == "funding":
            print(format_funding(funding_hotspots(conn, weeks=args.weeks), args.weeks))
        elif args.kind == "headlines":
            print(format_headline_diff(headline_diff(conn)))
        elif args.kind == "topics":
            print(format_topics(topic_heat(conn, weeks=args.weeks), args.weeks))
    finally:
        conn.close()


def cmd_weekly(args) -> None:
    from app.report.weekly import build_weekly
    res = build_weekly(anchor=args.week_of)
    if not res.get("ok"):
        print(f"❌ {res.get('reason')}")
        sys.exit(1)
    print(f"✅ 周报 {res['week_start']} ~ {res['week_end']}（{res['report_count']} 日 / {res['total_items']} 条）")
    print(f"   📝 {res['markdown']}")
    print(f"   📄 {res['html']}")
    if res.get("pdf"):
        print(f"   📕 {res['pdf']}")
    elif res.get("pdf_error"):
        print(f"   ⚠️  {res['pdf_error']}")


def cmd_watch(args) -> None:
    from app.storage.report_store import ReportStore as RS
    from app.utils.anomaly import run_checks, notify_local
    from app.utils.alert import send_alert
    db = _ensure_db()
    runlogs = RS("data/reports").all_runlogs()
    anomalies = run_checks(db, runlogs=runlogs, config_path="config/watch.yaml")
    if not anomalies:
        print("✅ 未发现异常。")
        return
    print(f"⚠️  发现 {len(anomalies)} 条异常:")
    for a in anomalies:
        print("  " + a.format())
    if args.dry_run:
        print("\n(dry-run) 未发送通知。")
        return
    text = "\n".join(a.format() for a in anomalies)
    sent = send_alert(f"日报异常巡检：\n{text}", level="warning")
    local = notify_local(f"发现 {len(anomalies)} 条异常", "AI 财经日报 watch")
    print(f"\n📨 webhook: {'已发送' if sent else '未配置/未发送'} ｜ 本地通知: {'已发送' if local else '不可用'}")


def cmd_subscribe(args) -> None:
    from app.personalization.store import SubscriptionStore
    store = SubscriptionStore("data/subscriptions")
    if args.list:
        subs = store.list_all()
        if not subs:
            print("（暂无订阅，用 --add 添加）")
        for s in subs:
            print(f"● {s.name}: 公司={s.companies or '—'} 栏目={s.categories or '—'}")
        return
    if args.add or args.categories:
        companies = [c.strip() for c in (args.add or "").split(",") if c.strip()]
        cats = [c.strip() for c in (args.categories or "").split(",") if c.strip()]
        sub = store.add(args.name, companies=companies, categories=cats)
        print(f"✅ 订阅已保存（{sub.name}）: 公司={sub.companies} 栏目={sub.categories}")
        return
    if args.remove:
        companies = [c.strip() for c in args.remove.split(",") if c.strip()]
        sub = store.remove(args.name, companies=companies)
        print(f"✅ 已移除 {companies}，当前: 公司={sub.companies} 栏目={sub.categories}")
        return
    print("用法: --add \"公司A,公司B\" --categories funding,policy ｜ --list ｜ --remove \"公司A\"")


def main() -> None:
    p = argparse.ArgumentParser(description="AI 财经日报")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="搜索策略信息").set_defaults(func=cmd_info)
    pc = sub.add_parser("collect", help="新闻采集")
    pc.add_argument("--test", action="store_true"); pc.add_argument("--batch"); pc.add_argument("--all", action="store_true")
    pc.set_defaults(func=cmd_collect)

    def add_shortcut(sp, name):
        sp.add_argument("--open", action="store_true", help="用默认应用打开")
        sp.add_argument("--no-open", action="store_true", help="只打印路径不打开")
        sp.add_argument("--json", action="store_true", help="打印日报 JSON 摘要")
        sp.add_argument("--stats", action="store_true", help="打印运行数字")
        sp.add_argument("--section", help="只看某栏目")
        sp.add_argument("--limit", type=int, default=10)
        sp.set_defaults(func=cmd_today if name == "today" else cmd_latest)
    add_shortcut(sub.add_parser("today", help="打开今天日报"), "today")
    add_shortcut(sub.add_parser("latest", help="打开最近日报"), "latest")

    pd = sub.add_parser("doctor", help="一行健康检查")
    pd.add_argument("--strict", action="store_true", help="警告也视为不通过")
    pd.set_defaults(func=cmd_doctor)

    pw = sub.add_parser("web", help="本地 Web 看板")
    pw.add_argument("--port", type=int, default=8910); pw.add_argument("--host", default="127.0.0.1")
    pw.set_defaults(func=cmd_web)

    pe = sub.add_parser("export", help="多格式导出")
    pe.add_argument("--date"); pe.add_argument("--format", default="all", help="markdown|wechat|email|notion|all")
    pe.add_argument("--all", action="store_true"); pe.add_argument("--out")
    pe.set_defaults(func=cmd_export)

    pca = sub.add_parser("cards", help="衍生卡片图")
    pca.add_argument("--date"); pca.add_argument("--style", default="light", choices=["light", "dark"])
    pca.add_argument("--only", choices=["top"]); pca.add_argument("--out")
    pca.set_defaults(func=cmd_cards)

    pf = sub.add_parser("feed", help="RSS/Atom feed")
    pf.add_argument("--port", type=int)
    pf.set_defaults(func=cmd_feed)

    pi = sub.add_parser("index", help="SQLite 情报库")
    pi.add_argument("action", choices=["build", "rebuild"])
    pi.set_defaults(func=cmd_index)

    pq = sub.add_parser("query", help="全文检索情报库")
    pq.add_argument("keyword"); pq.add_argument("--days", type=int); pq.add_argument("--category")
    pq.add_argument("--importance-min", type=int, dest="importance_min"); pq.add_argument("--limit", type=int, default=50)
    pq.set_defaults(func=cmd_query)

    ps = sub.add_parser("stats", help="情报库统计")
    ps.add_argument("--since"); ps.set_defaults(func=cmd_stats)

    pt = sub.add_parser("trend", help="跨期趋势")
    pt.add_argument("kind", choices=["funding", "headlines", "topics"])
    pt.add_argument("--weeks", type=int, default=4); pt.set_defaults(func=cmd_trend)

    pwy = sub.add_parser("weekly", help="周报聚合")
    pwy.add_argument("--week-of", dest="week_of"); pwy.set_defaults(func=cmd_weekly)

    pwat = sub.add_parser("watch", help="异常告警巡检")
    pwat.add_argument("--dry-run", action="store_true"); pwat.set_defaults(func=cmd_watch)

    psub = sub.add_parser("subscribe", help="订阅与个性化")
    psub.add_argument("--name", default="default")
    psub.add_argument("--add", help="公司，逗号分隔")
    psub.add_argument("--categories", help="栏目，逗号分隔")
    psub.add_argument("--remove", help="移除公司，逗号分隔")
    psub.add_argument("--list", action="store_true")
    psub.set_defaults(func=cmd_subscribe)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
