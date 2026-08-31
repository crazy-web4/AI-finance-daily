#!/usr/bin/env python3
"""
搜索美股盘前资讯，并入已有日报 JSON，并重渲染 PDF。
用法: python3 scripts/add_us_stocks.py <daily_json_path> [--output-dir DIR]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.schemas.models import (
    Category,
    DailyReport,
    ReportItem,
    ReportSection,
    ReportSource,
)
from app.search.queries import SearchQuery
from app.pipeline.collector import NewsCollector, normalize_result
from app.report.renderer import PDFRenderer, RenderConfig


US_STOCK_QUERIES = [
    ("US stocks premarket movers today", "盘前异动"),
    ("US stock futures premarket news today", "期指盘前"),
    ("NVIDIA earnings preview AI stock", "英伟达财报"),
    ("AI stocks premarket movers today NVIDIA Microsoft", "AI 概念股"),
    ("Tesla stock news today AI", "特斯拉"),
    ("Apple AI stock news today", "苹果"),
    ("US tech earnings this week AI", "科技财报"),
    ("Magnificent 7 stocks today AI", "Magnificent 7"),
    ("stock market rally selloff today AI sector", "大盘走势"),
    ("US semiconductor stocks today AI chips", "半导体"),
]


async def search_us_stocks(api_key: str, tavily_key: str = "") -> list:
    """搜索美股盘前资讯。AnySearch 失败时 fallback 到纯 Tavily。"""
    queries = [
        SearchQuery(query=q, batch_id="us_stocks", category="us_stocks",
                     max_results=8)
        for q, _ in US_STOCK_QUERIES
    ]

    try:
        collector = NewsCollector(api_key=api_key)
    except Exception:
        collector = None

    if collector:
        try:
            articles = await collector.collect(
                queries[:6],
                batch_id="us_stocks",
                tavily_top_n=5,
                max_age_hours=24,
                url_dedup=True,
                title_dedup=True,
                min_content_length=0,
            )
            await collector.close()
            return articles
        except RuntimeError as e:
            print(f"   ⚠️ AnySearch 失败，改用纯 Tavily: {e}")
            await collector.close()
        except Exception as e:
            print(f"   ⚠️ AnySearch 异常，改用纯 Tavily: {e}")
            try:
                await collector.close()
            except Exception:
                pass

    # Fallback: 直接用 TavilyClient
    print("   🛟 使用 Tavily 直接搜索...")
    from app.search.anysearch import TavilyClient
    import os
    tav_key = tavily_key or os.environ.get("TAVILY_API_KEY", "")
    if not tav_key:
        print("   ❌ 无 TAVILY_API_KEY")
        return []
    tavily = TavilyClient(api_key=tav_key)
    try:
        import asyncio
        results = []
        for q, _ in US_STOCK_QUERIES[:8]:
            items = await tavily.search(q, max_results=5, time_range="day", search_depth="advanced")
            sq = SearchQuery(query=q, batch_id="us_stocks", category="us_stocks", max_results=5)
            for item in items:
                art = normalize_result(item, query=sq)
                results.append(art)
        # 简单去重
        seen_urls = set()
        unique = []
        for a in results:
            if a.url not in seen_urls:
                seen_urls.add(a.url)
                unique.append(a)
        return unique
    finally:
        await tavily.close()


def articles_to_items(articles: list, max_items: int = 6) -> list:
    """把 RawNewsArticle 列表转成 ReportItem 列表（简易版）。

    第三轮 T9: 先过滤短摘要、再取前 max_items（原实现先切片后过滤，
    存在短摘要时最终条数会少于 max_items）。
    """
    items = []
    rank = 0
    for art in articles:
        # 构造简易标题 + 摘要作为正文
        title = art.title
        details = art.snippet.strip()
        if not details and art.content:
            details = art.content[:500]

        # 去掉过短的
        if len(details) < 50:
            continue
        rank += 1

        source_name = art.source_name or art.source_domain
        source_url = str(art.url)

        item = ReportItem(
            item_id=f"us_{rank:03d}",
            event_id=f"evt_us_{rank}",
            rank=rank,
            category=Category.US_STOCKS,
            title=title,
            details=details,
            sources=[ReportSource(
                name=source_name,
                url=source_url,
                is_official=False,
            )],
            word_count=len(title) + len(details),
        )
        items.append(item)
        if len(items) >= max_items:
            break
    return items


def add_us_stocks_section(report: DailyReport, items: list) -> DailyReport:
    """给日报添加美股盘前资讯栏目。"""
    # 检查是否已有该栏目
    existing = None
    for s in report.sections:
        if s.section_id == Category.US_STOCKS:
            existing = s
            break

    new_section = ReportSection(
        section_id=Category.US_STOCKS,
        section_name="美股盘前资讯",
        item_count=len(items),
        items=items,
    )

    if existing:
        # 替换
        sections = [new_section if s.section_id == Category.US_STOCKS else s
                    for s in report.sections]
    else:
        # 追加到末尾
        sections = list(report.sections) + [new_section]

    # 更新统计
    total_items = sum(s.item_count for s in sections)
    total_words = sum(it.word_count for s in sections for it in s.items)

    # 返回新的 report
    report_data = report.model_dump()
    report_data["sections"] = [s.model_dump() for s in sections]
    report_data["total_items"] = total_items
    report_data["total_word_count"] = total_words

    return DailyReport(**report_data)


async def main():
    parser = argparse.ArgumentParser(description="搜索美股盘前资讯并加入日报")
    parser.add_argument("daily_json", help="已有日报 JSON 路径")
    parser.add_argument("--max-items", type=int, default=6, help="最多条目数")
    parser.add_argument("--output-dir", default="", help="输出目录（默认同目录）")
    parser.add_argument("--watermark", default="    广明 Cyber_Gm    ", help="水印文字")
    parser.add_argument("--editor-name", default="广明", help="推送人")
    parser.add_argument("--wechat-id", default="Cyber_Gm", help="微信号")
    args = parser.parse_args()

    # 加载已有日报
    report = DailyReport.model_validate_json(Path(args.daily_json).read_text())
    print(f"已有日报: {report.report_date}, {report.total_items} 条")

    # 搜索
    api_key = os.environ.get("ANYSEARCH_API_KEY", "")
    if not api_key:
        print("❌ 未配置 ANYSEARCH_API_KEY")
        sys.exit(1)

    print("🔍 搜索美股盘前资讯...")
    articles = await search_us_stocks(api_key)
    print(f"   采集到 {len(articles)} 篇")

    # 转成 ReportItem
    items = articles_to_items(articles, max_items=args.max_items)
    print(f"   精选 {len(items)} 条")

    # 添加栏目
    report = add_us_stocks_section(report, items)
    print(f"   新总条目: {report.total_items}")

    # 输出目录
    out_dir = args.output_dir or str(Path(args.daily_json).parent)

    # 保存 JSON
    json_path = Path(out_dir) / f"daily_{report.report_date}_CyberGm_us.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"📋 JSON: {json_path}")

    # 渲染 PDF
    config = RenderConfig(
        watermark_text=args.watermark,
        editor_name=args.editor_name,
        wechat_id=args.wechat_id,
        output_dir=out_dir,
        filename_pattern=f"AI行业全球动态日报_{'{date}'}@{args.wechat_id}_美股版.pdf",
    )
    renderer = PDFRenderer(config=config)

    html_path = Path(out_dir) / f"report_{report.report_date}_CyberGm_us.html"
    html = renderer.render_html(report)
    html_path.write_text(html, encoding="utf-8")
    print(f"🌐 HTML: {html_path}")

    print("📕 生成 PDF...")
    pdf_path = await renderer.render_pdf(report)
    print(f"PDF: {pdf_path}")
    print(f"大小: {pdf_path.stat().st_size / 1024:.1f} KB")
    print("\n✅ 完成！")


if __name__ == "__main__":
    asyncio.run(main())
