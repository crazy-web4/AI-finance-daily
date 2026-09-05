"""
实体（公司/机构）词典与提取（T-C7 索引 / T-C8 趋势共用）
从日报条目标题/摘要中识别知名 AI 公司与机构，用于跨期聚合。
无需 NLP 依赖：基于别名表的子串匹配，命中归一到规范名。
"""

from __future__ import annotations

# 规范名 → 别名（小写匹配；中文直接子串）
COMPANY_ALIASES: dict[str, list[str]] = {
    "OpenAI": ["openai", "oai"],
    "Anthropic": ["anthropic", "claude"],
    "Google": ["google", "谷歌", "deepmind", "gemini", "alphabet"],
    "Meta": ["meta", "facebook", "llama", "muse spark"],
    "Microsoft": ["microsoft", "微软"],
    "Apple": ["apple", "苹果"],
    "Amazon": ["amazon", "aws", "亚马逊"],
    "Nvidia": ["nvidia", "英伟达"],
    "AMD": ["amd", "超威"],
    "Intel": ["intel", "英特尔"],
    "Broadcom": ["broadcom", "博通"],
    "TSMC": ["tsmc", "台积电"],
    "xAI": ["xai", "grok"],
    "Mistral": ["mistral"],
    "Cohere": ["cohere"],
    "Perplexity": ["perplexity"],
    "Hugging Face": ["hugging face", "huggingface"],
    "ByteDance": ["bytedance", "字节", "字节跳动", "豆包", "doubao"],
    "Alibaba": ["alibaba", "阿里", "通义", "qwen", "千问"],
    "Tencent": ["tencent", "腾讯", "hunyuan", "混元"],
    "Baidu": ["baidu", "百度", "文心", "ernie"],
    "Huawei": ["huawei", "华为", "盘古"],
    "Moonshot": ["moonshot", "月之暗面", "kimi"],
    "MiniMax": ["minimax"],
    "Zhipu": ["zhipu", "智谱", "chatglm", "glm"],
    "DeepSeek": ["deepseek", "深度求索"],
    "01.AI": ["01.ai", "零一万物", "yi "],
    "Tesla": ["tesla", "特斯拉"],
    "Oracle": ["oracle", "甲骨文"],
    "Salesforce": ["salesforce"],
    "IBM": ["ibm"],
    "Samsung": ["samsung", "三星"],
    "SK Hynix": ["sk hynix", "海力士"],
    "CoreWeave": ["coreweave"],
    "Databricks": ["databricks"],
    "Snowflake": ["snowflake"],
    "ServiceNow": ["servicenow"],
    "Palantir": ["palantir"],
    "CrowdStrike": ["crowdstrike"],
    "Palo Alto Networks": ["palo alto", "panw"],
    "Fortinet": ["fortinet"],
    "Marvell": ["marvell"],
    "Qualcomm": ["qualcomm", "高通"],
    "ARM": ["arm holdings", "arm 架构"],
    "T-Mobile": ["t-mobile"],
    "Comcast": ["comcast"],
}


def extract_companies(text: str | None) -> list[str]:
    """返回文本中出现的公司规范名（去重、保持词典顺序）。"""
    if not text:
        return []
    low = text.lower()
    found: list[str] = []
    seen: set[str] = set()
    for canon, aliases in COMPANY_ALIASES.items():
        hit = canon.lower() in low
        if not hit:
            for alias in aliases:
                if alias and alias in low:
                    hit = True
                    break
        if hit and canon not in seen:
            seen.add(canon)
            found.append(canon)
    return found
