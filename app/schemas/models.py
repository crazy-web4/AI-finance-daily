"""
JSON Schema 数据模型（接口编号: IF-004）
=================================================
数据链路:
  SearchResultItem  ← IF-001 搜索层
         ↓
  RawNewsArticle        原始新闻（归一化后）
         ↓
  NewsEvent             事件（去重聚类后，多对一文章→事件）
         ↓
  ReportItem            Analyst 编辑输出（V1 合并研究/核查/分类职责，
                        事实核查见 app/agents/factcheck.py）
         ↓
  DailyReport           总编辑输出（最终产物）

注: prompts/01~05 的五角色拆分（ResearchEvent/FactCheckedEvent/ClassifiedEvent）
为设计稿，V1 未启用；相关模型已于第 4 批清理（见 架构评审与优化计划.md #14）。

所有模型使用 Pydantic v2，自动生成 JSON Schema。
用 `python -m app.schemas.models --generate` 可导出全部 JSON Schema。
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ═══════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════

class Category(str, Enum):
    TOP_NEWS = "top_news"
    MODEL_TECH = "model_tech"
    FUNDING = "funding"
    POLICY = "policy"
    RESEARCH = "research"
    INDUSTRY = "industry"


CATEGORY_NAMES = {
    Category.TOP_NEWS: "今日头条",
    Category.MODEL_TECH: "模型发布与技术进展",
    Category.FUNDING: "融资与资本动态",
    Category.POLICY: "政策与监管",
    Category.RESEARCH: "学术与研究突破",
    Category.INDUSTRY: "市场与产业动态",
}

CATEGORY_ORDER = [
    Category.TOP_NEWS,
    Category.MODEL_TECH,
    Category.FUNDING,
    Category.POLICY,
    Category.RESEARCH,
    Category.INDUSTRY,
]


class EventType(str, Enum):
    MODEL_RELEASE = "model_release"
    MODEL_UPDATE = "model_update"
    API_LAUNCH = "api_launch"
    FUNDING_ROUND = "funding_round"
    ACQUISITION = "acquisition"
    PARTNERSHIP = "partnership"
    POLICY_CHANGE = "policy_change"
    REGULATION_UPDATE = "regulation_update"
    RESEARCH_BREAKTHROUGH = "research_breakthrough"
    PRODUCT_LAUNCH = "product_launch"
    CHIP_HARDWARE = "chip_hardware"
    DATACENTER_INFRA = "datacenter_infra"
    COMPANY_STRATEGY = "company_strategy"
    LAWSUIT_LEGAL = "lawsuit_legal"
    MARKET_DATA = "market_data"
    SAFETY_SECURITY = "safety_security"
    OTHER = "other"


class SourceReliability(str, Enum):
    HIGH = "high"       # 官方一手 / 顶级权威媒体
    MEDIUM = "medium"   # 主流科技媒体
    LOW = "low"         # 博客 / 社交媒体 / 次级媒体
    UNKNOWN = "unknown"


class FactCheckRecommendation(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


# ═══════════════════════════════════════════════════════
# L1: 搜索结果（来自 IF-001）
# ═══════════════════════════════════════════════════════

class SearchResultItem(BaseModel):
    """单条搜索结果。"""
    result_id: str
    title: str
    url: HttpUrl
    source_domain: str
    source_name: str | None = None
    snippet: str = ""
    content: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime
    language: str | None = None
    country: str | None = None
    author: str | None = None
    score: float | None = None
    query_origin: str | None = None

    @classmethod
    def make_id(cls, url: str, title: str) -> str:
        seed = f"{url}|{title}".lower()
        return "res_" + hashlib.sha256(seed.encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════
# L2: 原始新闻（归一化后）
# ═══════════════════════════════════════════════════════

def normalize_url(url: str) -> str:
    """
    URL 归一化（用于去重与文章ID）:
    小写 scheme/netloc、去 fragment、去追踪参数(utm_*/fbclid/...)、去末尾斜杠。
    """
    from urllib.parse import urlparse, urlunparse
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    query_params = []
    if parsed.query:
        for pair in parsed.query.split("&"):
            if not pair:
                continue
            key = pair.split("=")[0].lower()
            if key.startswith("utm_") or key in (
                "fbclid", "gclid", "ref", "ref_src", "referrer", "mc_cid", "mc_eid",
            ):
                continue
            query_params.append(pair)
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/") or "/",
        parsed.params,
        "&".join(query_params),
        "",
    ))


class RawNewsArticle(BaseModel):
    """归一化后的原始新闻文章（单一事实源，采集/聚类/分析共用）。"""
    article_id: str = Field(..., description="文章唯一ID（sha256(归一化url)前12位）")
    title: str
    url: HttpUrl
    source_domain: str
    source_name: str | None = None
    content: str = Field(default="", description="正文内容，纯文本")
    snippet: str = ""
    summary: str | None = None
    category: str | None = Field(default=None, description="业务分类标签（来自查询打标）")
    published_at: datetime | None = None
    fetched_at: datetime
    language: str | None = None
    country: str | None = None
    author: str | None = None
    search_query: str | None = None
    search_batch: str | None = None
    source_reliability: SourceReliability = SourceReliability.UNKNOWN
    result_count: int = Field(default=1, description="在多少条查询中出现")

    @classmethod
    def make_id(cls, url: str) -> str:
        return "art_" + hashlib.sha256(normalize_url(url).encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════
# L3: 事件（聚类后）
# ═══════════════════════════════════════════════════════

class NewsEvent(BaseModel):
    """
    聚类后的事件。
    多篇文章描述同一事件 → 一个 NewsEvent。
    """
    event_id: str = Field(..., description="事件唯一ID")
    canonical_title: str = Field(..., description="代表性标题（从多篇中选最优）")
    article_ids: list[str] = Field(..., description="关联的文章ID列表")
    article_count: int = Field(..., description="关联文章数量")
    event_type_guess: EventType | None = None
    earliest_published_at: datetime | None = None
    latest_published_at: datetime | None = None
    source_domains: list[str] = []
    companies_mentioned: list[str] = []
    cluster_score: float | None = Field(
        default=None,
        description="聚类置信度（0~1），越高表示组内文章越相关",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def make_id(cls, seed: str) -> str:
        return "evt_" + hashlib.sha256(seed.encode()).hexdigest()[:10]


# ═══════════════════════════════════════════════════════
# L4: Agent-1 研究员输出
# ═══════════════════════════════════════════════════════

class KeyDataPoint(BaseModel):
    """关键数据点。"""
    key: str = Field(..., description="数据指标名称，如 '融资金额'、'估值'、'MMLU分数'")
    value: str = Field(..., description="数值（字符串形式，保留原文格式）")
    unit: str | None = Field(default=None, description="单位，如 '亿美元'、'%'、'参数'")
    is_verified: bool = Field(default=False, description="是否经过多源交叉验证")
    source_indexes: list[int] = Field(
        default_factory=list,
        description="支撑该数据的来源索引（对应 sources 数组的下标）",
    )


# ═══════════════════════════════════════════════════════
# L7: Agent-4 编辑输出（日报条目）
# ═══════════════════════════════════════════════════════

class ReportKeyData(BaseModel):
    """日报条目中的关键数据。"""
    label: str = Field(..., description="数据项标签，如 '发布时间'、'融资额'")
    value: str = Field(..., description="数值/内容")
    source_indexes: list[int] = Field(default_factory=list)


class ReportSource(BaseModel):
    """日报条目中的来源。"""
    name: str
    url: HttpUrl
    is_official: bool = False


class ReportItem(BaseModel):
    """Agent-4 编辑好的日报条目。"""
    item_id: str = Field(..., description="条目ID，如 item_001")
    event_id: str
    rank: int = Field(ge=1, description="在所属栏目内的排名")
    category: Category
    title: str = Field(..., description="条目标题")
    lead: str = Field(..., description="导语，2-3句话")
    key_data: list[ReportKeyData] = Field(default_factory=list)
    details: str = Field(..., description="事件详情，1-2段")
    analysis: str | None = Field(default=None, description="行业影响/编辑判断")
    sources: list[ReportSource] = Field(default_factory=list)
    word_count: int = Field(ge=0, description="正文字数统计")
    edited_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def make_id(cls, idx: int) -> str:
        return f"item_{idx:03d}"


# ═══════════════════════════════════════════════════════
# L8: Agent-5 总编辑输出（最终日报）
# ═══════════════════════════════════════════════════════

class RemovedItem(BaseModel):
    """被总编辑移除的条目及原因。"""
    event_id: str
    reason: str
    merged_into: str | None = None


class ReportSection(BaseModel):
    """日报的一个栏目。"""
    section_id: Category
    section_name: str
    item_count: int
    items: list[ReportItem] = Field(default_factory=list)


class DailyReport(BaseModel):
    """
    最终日报数据结构。
    这是整个流水线的核心产出，直接喂给 PDF 渲染器。
    """
    report_id: str = Field(..., description="日报ID，如 daily_20260819")
    report_date: str = Field(..., description="报告日期，格式 YYYY-MM-DD")
    time_window_start: datetime = Field(..., description="数据时间窗口起点")
    time_window_end: datetime = Field(..., description="数据时间窗口终点")
    total_items: int = Field(ge=0, description="总条目数")
    total_word_count: int = Field(ge=0, description="总字数")
    editor_summary: str | None = Field(
        default=None,
        description="今日导读 / 卷首语（可选，100-200字）",
    )
    sections: list[ReportSection] = Field(
        default_factory=list,
        description="六大栏目，按固定顺序排列",
    )
    removed_items: list[RemovedItem] = Field(default_factory=list)
    quality_flags: list[str] = Field(
        default_factory=list,
        description="质量问题标记，供人工复核",
    )
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = Field(default="1.0.0", description="日报格式版本")

    @field_validator("sections")
    @classmethod
    def validate_sections_order(cls, v: list[ReportSection]) -> list[ReportSection]:
        """确保栏目顺序正确且完整。"""
        if len(v) > 6:
            raise ValueError("栏目不能超过6个")
        # 检查是否有重复
        ids = [s.section_id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("栏目不能重复")
        return v


# ═══════════════════════════════════════════════════════
# 工具：导出 JSON Schema
# ═══════════════════════════════════════════════════════

ALL_MODELS: list[type[BaseModel]] = [
    SearchResultItem,
    RawNewsArticle,
    NewsEvent,
    ReportItem,
    DailyReport,
]


def export_all_schemas(out_dir: str = "schemas") -> None:
    """导出所有模型的 JSON Schema 到 schemas/ 目录。"""
    import os
    os.makedirs(out_dir, exist_ok=True)
    for model in ALL_MODELS:
        name = model.__name__
        path = os.path.join(out_dir, f"{name}.json")
        schema = model.model_json_schema()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        print(f"  ✓ {name}.json")


if __name__ == "__main__":
    if "--generate" in sys.argv:
        print("导出 JSON Schema...")
        export_all_schemas()
        print("完成！")
    else:
        print("用法: python -m app.schemas.models --generate")
