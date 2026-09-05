#!/usr/bin/env python3
"""
从 Markdown 深度研报生成 PDF，复用日报模板。
用法: python3 scripts/md_to_research_report.py <md_path> [--watermark TEXT]
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas.models import (
    Category,
    DailyReport,
    ReportItem,
    ReportSection,
    ReportSource,
)
from app.report.renderer import PDFRenderer, RenderConfig


def _clean_text(text: str) -> tuple[str, list[ReportSource]]:
    """清理 markdown 文本格式，提取来源链接。"""
    sources = []
    source_pattern = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')
    seen_urls = set()
    for match in source_pattern.finditer(text):
        name = match.group(1).strip()
        url = match.group(2).strip()
        if url not in seen_urls and len(name) < 50:
            seen_urls.add(url)
            sources.append(ReportSource(name=name[:30], url=url, is_official=False))
    
    clean = source_pattern.sub(r'\1', text)
    clean = re.sub(r'\*\*(.+?)\*\*', r'\1', clean)
    clean = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'\1', clean)
    return clean, sources[:10]


def _make_item(title: str, body: str, cat: Category, idx: int) -> ReportItem:
    clean, srcs = _clean_text(body)
    return ReportItem(
        item_id=f"item_{idx:03d}",
        event_id=f"evt_{idx}",
        rank=1,
        category=cat,
        title=title,
        details=clean.strip(),
        sources=srcs,
        word_count=len(title) + len(clean.strip()),
    )


def parse_md_report(md_path: str, report_date: str) -> DailyReport:
    md = Path(md_path).read_text(encoding='utf-8')
    lines = md.split('\n')

    main_title = "AI 深度研报"
    for line in lines:
        if line.startswith('# '):
            main_title = line[2:].strip()
            break

    sections = []
    cur_sec_name = None
    cur_sec_body = []
    cur_item_title = None
    cur_item_body = []
    items_in_sec = []

    cat_list = [
        Category.TOP_NEWS,
        Category.MODEL_TECH,
        Category.FUNDING,
        Category.POLICY,
        Category.RESEARCH,
        Category.INDUSTRY,
        Category.US_STOCKS,
    ]

    def flush_item():
        nonlocal cur_item_title, cur_item_body
        if cur_item_title is not None and cur_sec_name is not None:
            body = '\n'.join(cur_item_body)
            items_in_sec.append((cur_item_title, body))
        cur_item_title = None
        cur_item_body = []

    def flush_section():
        nonlocal cur_sec_name, cur_sec_body
        flush_item()
        if cur_sec_name is None:
            return
        
        cat = cat_list[len(sections) % len(cat_list)]
        
        if items_in_sec:
            items = []
            for j, (t, b) in enumerate(items_in_sec):
                clean, srcs = _clean_text(b)
                items.append(ReportItem(
                    item_id=f"item_{len(sections)*100+j:03d}",
                    event_id=f"evt_{len(sections)}_{j}",
                    rank=j+1,
                    category=cat,
                    title=t,
                    details=clean.strip(),
                    sources=srcs,
                    word_count=len(t) + len(clean.strip()),
                ))
        else:
            body = '\n'.join(cur_sec_body)
            clean, srcs = _clean_text(body)
            items = [ReportItem(
                item_id=f"item_{len(sections)*100:03d}",
                event_id=f"evt_{len(sections)}_0",
                rank=1,
                category=cat,
                title=cur_sec_name,
                details=clean.strip(),
                sources=srcs,
                word_count=len(cur_sec_name) + len(clean.strip()),
            )]
        
        sections.append(ReportSection(
            section_id=cat,
            section_name=cur_sec_name,
            item_count=len(items),
            items=items,
        ))
        cur_sec_name = None
        cur_sec_body = []
        items_in_sec.clear()

    skip_sec = False
    for line in lines:
        # 跳过目录/参考文献/待完善
        if line.startswith('## '):
            title = line[3:].strip()
            if title in ('目录', '参考文献', '待完善事项'):
                flush_section()
                skip_sec = True
                continue
            else:
                skip_sec = False
                flush_section()
                cur_sec_name = title
                cur_sec_body = []
                continue
        
        if skip_sec:
            continue
        
        if line.startswith('### ') and cur_sec_name is not None:
            flush_item()
            cur_item_title = line[4:].strip()
            cur_item_body = []
            continue
        
        if line.startswith('---'):
            continue
        
        # 正文行
        if cur_item_title is not None:
            cur_item_body.append(line)
        elif cur_sec_name is not None:
            cur_sec_body.append(line)

    flush_section()

    total_items = sum(s.item_count for s in sections)
    total_words = sum(it.word_count for s in sections for it in s.items)
    
    editor_summary = ""
    if sections:
        first = sections[0]
        if first.items:
            editor_summary = first.items[0].details[:500]

    return DailyReport(
        report_id=f"research_{report_date.replace('-', '')}",
        report_date=report_date,
        time_window_start=datetime(2026, 1, 1),
        time_window_end=datetime.now(),
        total_items=total_items,
        total_word_count=total_words,
        editor_summary=editor_summary or None,
        sections=sections,
        generated_at=datetime.now(),
    )


async def main():
    parser = argparse.ArgumentParser(description="从 Markdown 深度研报生成 PDF")
    parser.add_argument("md_path")
    parser.add_argument("--watermark", default="AI深度研报 广明 Cyber_Gm")
    parser.add_argument("--editor-name", default="广明")
    parser.add_argument("--wechat-id", default="Cyber_Gm")
    parser.add_argument("--company", default="明雯科技")
    parser.add_argument("--report-title", default="AI 深度研报")
    parser.add_argument("--output-dir", default="data/reports")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    report_date = args.date
    if not report_date:
        md = Path(args.md_path).read_text(encoding='utf-8')
        m = re.search(r'(\d{4}-\d{2}-\d{2})', md)
        if m:
            report_date = m.group(1)
    if not report_date:
        report_date = datetime.now().strftime('%Y-%m-%d')

    print(f"研报: {args.md_path}")
    print(f"日期: {report_date}")
    print(f"水印: {args.watermark}")

    report = parse_md_report(args.md_path, report_date)
    print(f"章节: {len(report.sections)} 个")
    for s in report.sections:
        print(f"  {s.section_name}: {s.item_count} 节")
    print(f"总小节: {report.total_items}")
    print(f"总字数: {report.total_word_count}")

    config = RenderConfig(
        watermark_text=args.watermark,
        report_title=args.report_title,
        company=args.company,
        wechat_id=args.wechat_id,
        editor_name=args.editor_name,
        output_dir=args.output_dir,
        filename_pattern="AI深度研报_{date}@" + args.wechat_id + ".pdf",
    )
    renderer = PDFRenderer(config=config)

    out_dir = Path(args.output_dir) / report_date
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / f"research_{report_date}_CyberGm.html"
    html = renderer.render_html(report)
    html_path.write_text(html, encoding="utf-8")
    print(f"HTML: {html_path}")

    json_path = out_dir / f"research_{report_date}_CyberGm.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"JSON: {json_path}")

    print("生成 PDF...")
    pdf_path = await renderer.render_pdf(report)
    print(f"PDF: {pdf_path}")
    print(f"大小: {pdf_path.stat().st_size / 1024:.1f} KB")
    print("\n完成！")


if __name__ == "__main__":
    asyncio.run(main())
