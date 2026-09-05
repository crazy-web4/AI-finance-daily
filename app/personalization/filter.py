"""
个性化过滤（建议 #11 · T-D11）
根据订阅规则（公司 + 栏目）过滤日报，生成定制版 DailyReport。
"""

from __future__ import annotations

from typing import Iterable

from app.schemas.models import (
    Category,
    DailyReport,
    ReportItem,
    ReportSection,
)
from app.storage.entities import extract_companies


def _item_companies(item: ReportItem) -> set[str]:
    return set(extract_companies(f"{item.title} {item.details} {item.analysis or ''}"))


def _matches_company(text_companies: set[str], wanted: Iterable[str]) -> bool:
    wanted_lower = {w.strip().lower() for w in wanted if w.strip()}
    if not wanted_lower:
        return False
    have = {c.lower() for c in text_companies}
    if have & wanted_lower:
        return True
    return False


def _item_text(item: ReportItem) -> str:
    return f"{item.title} {item.details} {item.analysis or ''}".lower()


def filter_report(report: DailyReport, companies: list[str], categories: list[str],
                  user: str = "default") -> DailyReport:
    """
    返回过滤后的新 DailyReport。

    条目保留条件（满足其一）：
    - 所属栏目在订阅 categories 内（整栏目保留）；
    - 标题/正文命中任一订阅公司名（含别名/中文名子串）。
    头条栏目也按同样规则过滤，排名重排。无任何订阅条件时原样返回。
    """
    companies = [c for c in (companies or []) if c.strip()]
    categories = [c for c in (categories or []) if c.strip()]
    if not companies and not categories:
        return report

    cat_set = set(categories)
    comp_lower = [c.lower() for c in companies]

    new_sections: list[ReportSection] = []
    for section in report.sections:
        sid = section.section_id.value if hasattr(section.section_id, "value") else str(section.section_id)
        keep_items: list[ReportItem] = []
        for item in section.items:
            in_category = sid in cat_set
            hit_company = _matches_company(_item_companies(item), companies)
            if not hit_company and comp_lower:
                text = _item_text(item)
                hit_company = any(c in text for c in comp_lower)
            if in_category or hit_company:
                keep_items.append(item)
        if not keep_items:
            continue
        # 重新排名
        reranked = []
        for new_rank, item in enumerate(keep_items, 1):
            reranked.append(item.model_copy(update={"rank": new_rank}))
        new_sections.append(ReportSection(
            section_id=section.section_id,
            section_name=section.section_name,
            item_count=len(reranked),
            items=reranked,
        ))

    total_items = sum(s.item_count for s in new_sections)
    total_words = sum(it.word_count for s in new_sections for it in s.items)
    scope = []
    if companies:
        scope.append("公司: " + "、".join(companies))
    if categories:
        scope.append("栏目: " + "、".join(categories))
    banner = f"📌 个性化订阅版（{user}）｜订阅范围 - " + "；".join(scope)
    summary = (report.editor_summary or "")
    summary = (banner + "\n\n" + summary).strip()

    return report.model_copy(update={
        "report_id": f"{report.report_id}_{user}_personalized",
        "sections": new_sections,
        "total_items": total_items,
        "total_word_count": total_words,
        "editor_summary": summary,
    })
