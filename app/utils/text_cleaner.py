"""
文本清洗与纠错工具（架构评审第二轮 · 第 5 批重构）
=================================================
分层约定（P0-4）:
  - 上游（run_daily.do_extract_fulltexts）: 对 extract 全文做 clean_full()，
    清理水印字/断词；数字水印清理仅对长行启用（min_line_len），避免吞真实数字。
  - 渲染层（renderer）: 只对发布终稿做零风险的 fix_broken_words() 断词修复，
    绝不对终稿做水印猜测（终稿由 LLM 写成，激进正则只会损坏干净文本）。

所有函数 None-safe（P0-1）。
"""

from __future__ import annotations

import re

# 水印字符集（P0-2）: 仅中文字符。
# 严禁加入单字符拉丁字母——'A'/'I' 会误删 "Series A 轮" / "Grade A" 等合法英文。
WATERMARK_CHARS_CN = set("行业全球动态日报杜皓杰明雯科技广明")

# 常见断词修复（被水印/换行打断的英文单词/专有名词）——零风险，上下游均可用
COMMON_BROKEN_WORDS = [
    (r'Clau\s+de\b', 'Claude'),
    (r'C8laude', 'Claude'),
    (r'Claud\s+e\b', 'Claude'),
    (r'Mar\s+vell\b', 'Marvell'),
    (r'Mal\s+pass\b', 'Malpass'),
    (r'Anthr\s+opic\b', 'Anthropic'),
    (r'Ant\s+hropic\b', 'Anthropic'),
    (r'Op\s+enAI\b', 'OpenAI'),
    (r'Deep\s+Seek\b', 'DeepSeek'),
    (r'Git\s+Hub\b', 'GitHub'),
    (r'G\s+mail\b', 'Gmail'),
    (r'Co\s+work\b', 'Cowork'),
]

COMMON_BROKEN_CN = [
    (r'具-身', '具身'),
]


def clean_watermark_chars(text: str, wm_chars: str | set | None = None) -> str:
    """
    清理文本中的单字水印（被空格包围的单个水印字）。
    仅用于上游原文清洗，不要用于发布终稿。
    """
    if not text:
        return text or ""
    if wm_chars is None:
        wm_chars = WATERMARK_CHARS_CN
    elif isinstance(wm_chars, str):
        wm_chars = set(wm_chars)

    for wc in wm_chars:
        text = re.sub(r' ' + re.escape(wc) + r' ', ' ', text)
        text = re.sub(r'^' + re.escape(wc) + r' ', '', text, flags=re.MULTILINE)
        text = re.sub(r' ' + re.escape(wc) + r'$', '', text, flags=re.MULTILINE)
    return text


def clean_watermark_digits(text: str, min_line_len: int = 20) -> str:
    """
    清理右侧竖排数字水印（日期被打散成行尾单数字）。

    保守策略（P0-3）:
      - 仅对长度 >= min_line_len 的行启用——短行（如「评分 9」「iPhone 1」）
        的尾数字视为合法内容，一律保留；
      - 排除引用编号 [1]、日期/金额结尾等模式；
      - 仅用于上游原文清洗。
    """
    if not text:
        return text or ""
    cleaned_lines = []
    for line in text.split('\n'):
        stripped = line.rstrip()
        m = re.search(r' (\d)$', stripped)
        if m and len(stripped) >= min_line_len:
            if re.search(r'[\[（(]\d+[\]）)]$', stripped):
                cleaned_lines.append(line)
                continue
            if re.search(r'[年月日时点分秒]\d$', stripped):
                cleaned_lines.append(line)
                continue
            if re.search(r'[万亿元美欧港元亿万个%倍]+\d$', stripped):
                cleaned_lines.append(line)
                continue
            cleaned_lines.append(stripped[:-1].rstrip())
        else:
            cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)


def fix_broken_words(text: str) -> str:
    """修复常见断词/错别字。零风险，上下游均可用。"""
    if not text:
        return text or ""
    for pattern, replacement in COMMON_BROKEN_WORDS:
        text = re.sub(pattern, replacement, text)
    for pattern, replacement in COMMON_BROKEN_CN:
        text = re.sub(pattern, replacement, text)
    return text


# ═══════════════════════════════════════════════════
# 内联水印碎片（第三轮 T3）
# ═══════════════════════════════════════════════════
# 头条/新浪系竖排日期水印（如 2026-08-28）被抽取器打散成内联碎片
# （"20"/"26"/"08"/"28"/"8-"/"-0"）散落正文，旧版 clean_full 只覆盖
# "空格包围单字"与"长行尾单数字"，拦不住内联碎片。
#
# 安全边界（宁可漏删、不可误删真实数字）:
#  - 零风险类: 破折号碎片（"汉8-汉/汉8-行尾/-0+数字/0-+数字"）在合法
#    财经文本中几乎不内联出现，直接删；
#  - 上下文限定类: "20/26/08/28" 两位数字仅当 前字非约数词 且 后字非量词
#    时才删——"约20亿美元/前20家/超20起/8月20日" 全部保留。

INLINE_SAFE_FRAGS = [
    re.compile(r'(?<=[一-鿿])8-(?=[一-鿿A-Za-z])'),
    re.compile(r'(?<=[一-鿿])8-$'),
    # 行首/空白后的 "-08" 类碎片（如 "-08 月 28 日"）；
    # 不匹配「沪指-0.11%」这类合法负数（前有非空白字符时不删）
    re.compile(r'(?<!\S)-0(?=\d)'),
]

_NUM_PRE_EXCLUDE = set("第前约超近达共逾满隔每")
_NUM_POST_EXCLUDE = set("亿万家个起的的天日月年位篇轮倍%％、，。；;")
INLINE_NUM_FRAG = re.compile(r'([一-鿿])(20|26|08|28)([一-鿿])')


def clean_inline_watermark(text: str) -> str:
    """清理内联水印碎片。零风险类直接删；两位数字碎片带上下文白名单。"""
    if not text:
        return text or ""
    for pat in INLINE_SAFE_FRAGS:
        text = pat.sub('', text)

    def _sub(m: "re.Match[str]") -> str:
        pre, frag, post = m.group(1), m.group(2), m.group(3)
        if pre in _NUM_PRE_EXCLUDE or post in _NUM_POST_EXCLUDE:
            return m.group(0)
        return pre + post

    return INLINE_NUM_FRAG.sub(_sub, text)


def light_clean(text: str) -> str:
    """title/snippet 级轻量清洗（第三轮 T3）: 断词修复 + 内联水印碎片。
    在 normalize 阶段对搜索层输入生效，阻断噪声进入聚类/LLM 上下文。"""
    if not text:
        return text or ""
    return clean_inline_watermark(fix_broken_words(text))


def clean_full(text: str, wm_chars: str | set | None = None, digits: bool = True) -> str:
    """
    上游原文完整清洗：水印字 → 数字水印(长行) → 断词修复。
    供 do_extract_fulltexts 在喂给 LLM 前调用。
    """
    if not text:
        return text or ""
    text = clean_watermark_chars(text, wm_chars)
    text = clean_inline_watermark(text)
    if digits:
        text = clean_watermark_digits(text)
    text = fix_broken_words(text)
    return text


def safe_render_clean(text: str) -> str:
    """渲染层清洗（P0-4）: 只做零风险断词修复，不做水印猜测。None-safe。"""
    return fix_broken_words(text) if text else (text or "")


def complete_title(title: str) -> str:
    """
    渲染层标题清洗: 断词修复 + 混入正文截断 + 去尾标点。None-safe。
    """
    if not title:
        return title or ""
    title = fix_broken_words(title).strip()

    # 标题里出现句号说明可能混进了正文，截到第一个句号
    if '。' in title and len(title) > 60:
        idx = title.find('。')
        if idx > 10:
            title = title[:idx + 1]

    return title.rstrip(' ，,、').strip()
