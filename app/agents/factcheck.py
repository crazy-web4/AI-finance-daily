"""
事实核查（架构评审 #6）
=================================================
两道防线:
  1. 确定性溯源 ground_key_data(): key_data 的数值核心必须字面出现在
     来源文本（全文+摘要）中，否则剔除并记入 quality_flags——
     零成本拦截数字幻觉。
  2. LLM 复核 FactCheckerAgent: 重要性 >=85 的条目做二次交叉核对，
     只允许修订（删/改无依据表述），不允许新增内容。
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.agents.base import LLMClient


class VerifyResult(BaseModel):
    """LLM 复核输出。"""
    verified: bool = True
    corrected_details: str | None = None
    unsupported_claims: list[str] = []


def _numeric_core(value: str) -> str:
    """提取数值核心，如 '200亿美元' → '200'，'1.8万亿' → '1.8'。"""
    m = re.search(r"\d+(?:[.,]\d+)*", str(value))
    return m.group(0) if m else str(value).strip()


def ground_key_data(
    key_data: list[dict],
    source_text: str,
) -> tuple[list[dict], list[str]]:
    """
    确定性溯源: 保留数值能在来源文本中字面找到的 key_data。

    Returns:
        (grounded, dropped_labels) dropped 形如 ['融资额=200亿美元']
    """
    grounded: list[dict] = []
    dropped: list[str] = []
    for kd in key_data or []:
        if not isinstance(kd, dict):
            continue
        core = _numeric_core(kd.get("value", ""))
        if core and core in source_text:
            grounded.append(kd)
        else:
            dropped.append(f"{kd.get('label', '?')}={kd.get('value', '?')}")
    return grounded, dropped


VERIFY_PROMPT = """你是一名严谨的事实核查编辑。对照提供的新闻原文/摘要，核查日报条目草稿。

规则:
- 只允许原文中出现的事实与数字；
- 若草稿含原文无法支持的表述，输出修订后的 details（只删/改无依据部分，保持其余信息量）；
- 不要新增原文没有的内容；不要改变标题。

只输出严格JSON:
{
  "verified": true,
  "corrected_details": "修订后的details；无需修订则为null",
  "unsupported_claims": ["原文无法支持的表述，逐条列出；没有则为空数组"]
}"""


class FactCheckerAgent:
    """高分条目（>=85）的 LLM 二次复核。"""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def verify(self, analysis: dict, context_text: str) -> VerifyResult | None:
        user = (
            f"【条目草稿】\n标题: {analysis.get('title', '')}\n"
            f"详情: {analysis.get('details', '')}\n\n"
            f"【来源材料】\n{context_text[:6000]}"
        )
        try:
            return self.llm.chat_json(
                system_prompt=VERIFY_PROMPT,
                user_prompt=user,
                response_model=VerifyResult,
                temperature=0.1,
            )
        except Exception as e:
            print(f"  ⚠️ 事实核查调用失败: {e}", flush=True)
            return None
