#!/usr/bin/env python3
"""
把美股盘前资讯翻译成中文并重新渲染。
用法: python3 scripts/translate_us_stocks.py <daily_json_path>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas.models import DailyReport, ReportItem
from app.agents.base import LLMClient
from app.report.renderer import PDFRenderer, RenderConfig


def translate_items(items: list, llm: LLMClient) -> list:
    """用 LLM 批量翻译美股资讯条目。"""
    items_json = json.dumps([
        {"index": i, "title": it.title, "details": it.details[:500]}
        for i, it in enumerate(items)
    ], ensure_ascii=False)

    prompt = f"""请将以下美股盘前新闻翻译成中文，并用中文财经新闻的风格改写。

要求：
1. 标题 20-40 字，符合中文财经媒体风格
2. 摘要 100-200 字，保留关键数据和事实
3. 只输出 JSON 数组，格式：[{{"index": 0, "title": "...", "details": "..."}}]

原文：
{items_json}"""

    result_text = llm.chat_text(
        system_prompt="你是一名资深财经编辑，擅长把英文美股资讯翻译成高质量的中文财经新闻。",
        user_prompt=prompt,
        temperature=0.3,
    )

    # 提取 JSON
    import re
    m = re.search(r'\[.*\]', result_text, re.DOTALL)
    if not m:
        print(f"  ⚠️ LLM 返回无 JSON: {result_text[:200]}")
        return items

    try:
        translated = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"  ⚠️ JSON 解析失败: {e}")
        return items

    # 按 index 回填
    result = list(items)
    for t in translated:
        idx = t.get("index", -1)
        if 0 <= idx < len(result):
            new_title = t.get("title", "").strip()
            new_details = t.get("details", "").strip()
            if new_title and new_details:
                old = result[idx]
                result[idx] = ReportItem(
                    item_id=old.item_id,
                    event_id=old.event_id,
                    rank=old.rank,
                    category=old.category,
                    title=new_title,
                    details=new_details,
                    sources=old.sources,
                    word_count=len(new_title) + len(new_details),
                )
    return result


async def main():
    parser = argparse.ArgumentParser(description="翻译美股盘前资讯为中文")
    parser.add_argument("daily_json", help="日报 JSON 路径")
    parser.add_argument("--watermark", default="    广明 Cyber_Gm    ")
    parser.add_argument("--editor-name", default="广明")
    parser.add_argument("--wechat-id", default="Cyber_Gm")
    args = parser.parse_args()

    report = DailyReport.model_validate_json(Path(args.daily_json).read_text())

    # 找美股栏目
    us_sec = None
    for s in report.sections:
        if s.section_id.value == "us_stocks":
            us_sec = s
            break
    if not us_sec or not us_sec.items:
        print("❌ 未找到美股盘前资讯栏目")
        sys.exit(1)

    print(f"翻译 {len(us_sec.items)} 条美股资讯...")
    llm = LLMClient()
    translated = translate_items(us_sec.items, llm)
    print(f"  完成")

    # 更新栏目
    new_sections = []
    for s in report.sections:
        if s.section_id.value == "us_stocks":
            s = s.model_copy(update={
                "items": translated,
                "item_count": len(translated),
            })
        new_sections.append(s)

    # 更新统计
    total_items = sum(s.item_count for s in new_sections)
    total_words = sum(it.word_count for s in new_sections for it in s.items)

    report = report.model_copy(update={
        "sections": new_sections,
        "total_items": total_items,
        "total_word_count": total_words,
    })

    out_dir = Path(args.daily_json).parent

    # 保存 JSON
    json_path = out_dir / f"daily_{report.report_date}_CyberGm_中文美股.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"📋 JSON: {json_path}")

    # 渲染
    config = RenderConfig(
        watermark_text=args.watermark,
        editor_name=args.editor_name,
        wechat_id=args.wechat_id,
        output_dir=str(out_dir),
        filename_pattern=f"AI行业全球动态日报_{'{date}'}@{args.wechat_id}_中文版.pdf",
    )
    renderer = PDFRenderer(config=config)

    html_path = out_dir / f"report_{report.report_date}_CyberGm_中文版.html"
    html = renderer.render_html(report)
    html_path.write_text(html, encoding="utf-8")
    print(f"🌐 HTML: {html_path}")

    print("📕 生成 PDF...")
    pdf_path = await renderer.render_pdf(report)
    # 挪到正确目录
    import shutil
    dest = out_dir / pdf_path.name
    if pdf_path.parent != dest.parent:
        shutil.move(str(pdf_path), str(dest))
        pdf_path = dest
    print(f"PDF: {pdf_path}")
    print(f"大小: {pdf_path.stat().st_size/1024:.1f} KB")
    print("\n✅ 完成！")


if __name__ == "__main__":
    asyncio.run(main())
