#!/usr/bin/env python3
"""
从已有日报 PDF 提取内容，用 bbox 精确解析并重渲染。
v2: 基于 pdftotext -bbox 的坐标级解析，从根源避免水印和断行问题。

用法: python3 scripts/pdf_to_report.py <pdf_path> [--watermark TEXT] [--output-dir DIR]
"""
from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
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


SECTION_MAP = {
    "今日头条": Category.TOP_NEWS,
    "模型发布与技术进展": Category.MODEL_TECH,
    "融资与资本动态": Category.FUNDING,
    "政策与监管": Category.POLICY,
    "学术与研究突破": Category.RESEARCH,
    "市场与产业动态": Category.INDUSTRY,
}

NS = {"xhtml": "http://www.w3.org/1999/xhtml"}

# 正文区域（A4 页面内）
MAIN_X_MIN = 65.0   # 左侧正文起始 x（左侧水印 < 65）
MAIN_X_MAX = 510.0  # 右侧正文结束 x（右侧水印 > 510）


def extract_bbox(pdf_path: str) -> str:
    """提取 PDF 的 bbox HTML。"""
    result = subprocess.run(
        ["pdftotext", "-bbox", pdf_path, "-"],
        capture_output=True, text=True,
    )
    return result.stdout


def parse_pages(bbox_html: str) -> list:
    """
    把 bbox HTML 解析成结构化行。
    返回: list of page_data，每页包含若干行 [{y, text, font_size, x_min, x_max}]
    
    关键改进:
    - 用 baseline(yMax) 对齐分行，避免数字和中文 baseline 不同导致拆行
    - 同行内 word 按 x 排序后智能拼接（中文间去空格，英文间保留空格）
    """
    root = ET.fromstring(bbox_html)
    pages = root.findall(".//xhtml:page", NS)
    result = []

    for page in pages:
        words = []
        for w in page.findall(".//xhtml:word", NS):
            text = w.text or ""
            if not text.strip():
                continue
            x_min = float(w.get("xMin"))
            x_max = float(w.get("xMax"))
            y_min = float(w.get("yMin"))
            y_max = float(w.get("yMax"))
            font_size = y_max - y_min
            words.append((x_min, x_max, y_min, y_max, font_size, text))

        # 过滤掉左侧竖排水印区 (x < MAIN_X_MIN)
        # 和右侧竖排水印 (x > MAIN_X_MAX 且单字)
        filtered = []
        for x1, x2, y1, y2, fs, t in words:
            if x2 < MAIN_X_MIN:
                continue
            if x1 > MAIN_X_MAX and len(t.strip()) <= 2:
                continue
            filtered.append((x1, x2, y1, y2, fs, t))

        # 用 baseline (y_max) 分行，同一行 baseline 差 < 3pt
        # 先按 y_max 排序
        filtered.sort(key=lambda w: w[3])  # 按 y_max 排

        lines = []
        current_line_words = []
        current_baseline = None

        for w in filtered:
            x1, x2, y1, y2, fs, t = w
            baseline = y2
            if current_baseline is None:
                current_baseline = baseline
                current_line_words = [w]
            elif abs(baseline - current_baseline) < 3.0:
                # 同行
                current_line_words.append(w)
            else:
                # 新行
                if current_line_words:
                    lines.append(_build_line(current_line_words))
                current_baseline = baseline
                current_line_words = [w]

        if current_line_words:
            lines.append(_build_line(current_line_words))

        result.append(lines)

    return result


def _build_line(words: list) -> dict:
    """把一行的 word 按 x 排序拼接成文本，过滤孤立水印单字。
    
    水印特征：字号显著大于正文(>=14pt)、单字或短数字、孤立分布。
    """
    ws = sorted(words, key=lambda w: w[0])  # 按 x 排序

    # 计算行内字号统计，识别"异常大字"（水印特征）
    # 水印字/数字通常 16-22pt，正文 9-11pt，字号差非常明显
    if len(ws) >= 2:
        font_sizes = sorted(w[4] for w in ws)
        # 用最小字号作为"正文字号基准"（水印字总是比正文大）
        min_fs = font_sizes[0]
        # 计算小字号组的平均字宽（用于间距判断）
        small_words = [w for w in ws if w[4] <= min_fs + 1.5]
        if small_words:
            avg_char_w = sum(w[1] - w[0] for w in small_words) / len(small_words)
        else:
            avg_char_w = 10.0
        # 过滤异常大字：字号比最小字号大 3pt 以上 + 短内容
        filtered = []
        for i, w in enumerate(ws):
            x1, x2, y1, y2, fs, t = w
            t_stripped = t.strip()
            # 字号显著大于最小字号 + 短内容 → 疑似水印
            # 规则：字号差 >3pt 且是短词(<=3字符)
            if fs > min_fs + 3.0 and len(t_stripped) <= 3:
                # 1. 水印专用字（杜皓杰日报·）直接过滤
                if t_stripped in "杜皓杰日报·.":
                    continue
                # 2. 字号差特别大（>6pt 或 >1.6倍）→ 几乎肯定是水印，无需间距判断
                if fs > min_fs + 6.0 or fs > min_fs * 1.6:
                    # 且内容是数字/符号/短字母组合（水印日期碎片特征）
                    if re.match(r'^[\d\-·.]+$', t_stripped):
                        continue
                # 3. 检查是否孤立（前后间距明显大于正文字宽）
                prev_gap = w[0] - ws[i-1][1] if i > 0 else 999
                next_gap = ws[i+1][0] - w[1] if i < len(ws) - 1 else 999
                if prev_gap > avg_char_w * 1.2 and next_gap > avg_char_w * 1.2:
                    continue
            filtered.append(w)
        ws = filtered

    # 智能拼接: 中文之间无空格，英文/数字之间有空格
    parts = []
    for i in range(len(ws)):
        x1, x2, y1, y2, fs, t = ws[i]
        if i == 0:
            parts.append(t)
            continue
        prev_x2 = ws[i-1][1]
        gap = x1 - prev_x2
        prev_last = ws[i-1][5][-1]
        curr_first = t[0]
        prev_is_cn = bool(re.search(r"[\u4e00-\u9fff，。、；：？！」』）】、]", prev_last))
        curr_is_cn = bool(re.search(r"[\u4e00-\u9fff]", curr_first))
        if prev_is_cn and curr_is_cn:
            parts.append(t)
        elif gap < 1.5:
            parts.append(t)
        else:
            parts.append(" " + t)

    text = "".join(parts).strip()
    avg_fs = sum(w[4] for w in ws) / len(ws) if ws else 0
    x_min = ws[0][0] if ws else 0
    x_max = ws[-1][1] if ws else 0
    baseline = ws[0][3] if ws else 0
    return {
        "y": baseline,
        "text": text,
        "font_size": avg_fs,
        "x_min": x_min,
        "x_max": x_max,
    }


# ── PyMuPDF 提取（推荐路径）─────────────────────────────────────
# 源 PDF 的水印是「旋转 45° 的整行文本」（如：全球动态日报 2026-08-29 · 杜皓杰）。
# pdftotext -bbox 会把这行斜向水印的单字按坐标散落进正文行，事后要做大量水印清洗；
# PyMuPDF 按 PDF 文本对象返回行，水印是独立的「旋转 line/span」，可在提取阶段整体
# 剔除——正文不再混入水印单字/日期数字，字号也直接用标称值（栏目 14 / 标题 11.5 /
# 正文 10.5 / 来源名 9.5 / 链接 7.5），断行与标题合并更稳。


def _is_cjk_char(ch: str) -> bool:
    o = ord(ch)
    if 0x4E00 <= o <= 0x9FFF:
        return True
    if 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF:  # CJK 标点 / 全角字符
        return True
    return ch in "—…·"


def _join_spans(spans: list) -> str:
    """同行 span 按 x 顺序智能拼接：CJK 之间无空格，拉丁/数字之间按间距留空格。"""
    parts = []
    for i, sp in enumerate(spans):
        t = sp["text"]
        if i == 0:
            parts.append(t)
            continue
        prev = spans[i - 1]
        gap = sp["bbox"][0] - prev["bbox"][2]
        if _is_cjk_char(prev["text"][-1]) and _is_cjk_char(t[0]):
            parts.append(t)
        elif gap < 1.5:
            parts.append(t)
        else:
            parts.append(" " + t)
    text = "".join(parts)
    text = re.sub(r"\[\s*(\d+)\s*\]", r"[\1]", text)  # [ 1 ] → [1]
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def _is_chrome_noise(text: str) -> bool:
    """页眉/页脚/结尾标记等非正文行。"""
    t = text.strip()
    if not t:
        return True
    if "推送人" in t and "微信" in t:                    # 页脚推送人行
        return True
    if re.search(r"第\s*\d+\s*页", t) and len(t) < 24:   # — 第 N 页 —
        return True
    if "本期日报完" in t:                                # 结尾分隔行
        return True
    return False


def parse_pages_pymupdf(pdf_path: str) -> list:
    """用 PyMuPDF 按原生文本对象解析每页的行。

    返回与 parse_pages 相同的结构：list[page]，每行为
        {"y", "text", "font_size", "x_min", "x_max"}
    旋转行（斜向水印）与链接图标字形（ZapfDingbats/Symbol）在提取阶段直接剔除。
    """
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    pages_out = []
    for page in doc:
        data = page.get_text("dict")
        lines_out = []
        for block in data.get("blocks", []):
            if block.get("type", 0) != 0:  # 跳过图片块
                continue
            for line in block.get("lines", []):
                dx, dy = line.get("dir", (1.0, 0.0))
                if abs(dy) > 0.01 or dx < 0.99:  # 旋转行 = 斜向水印
                    continue
                spans = [s for s in line.get("spans", []) if s["text"].strip()]
                # 去掉链接前缀图标（ZapfDingbats/Symbol 里的图形字形）
                spans = [
                    s for s in spans
                    if not any(f in s["font"] for f in ("ZapfDingbats", "Symbol"))
                ]
                if not spans:
                    continue
                text = _join_spans(spans)
                if _is_chrome_noise(text):
                    continue
                lines_out.append({
                    "y": line["bbox"][1],
                    "text": text,
                    "font_size": max(s["size"] for s in spans),
                    "x_min": min(s["bbox"][0] for s in spans),
                    "x_max": max(s["bbox"][2] for s in spans),
                })
        pages_out.append(lines_out)
    return pages_out


def is_section_header(line: dict) -> tuple[bool, str]:
    """判断一行是不是内容页的栏目标题（排除目录页）。
    注意: 内容页的栏目标题旁可能带竖排水印字/页码噪声，需要容错。
    排除: 目录页的栏目（后面跟大量点号 + 页码）。
    """
    text = line["text"].strip()
    if line["font_size"] <= 11:
        return False, ""
    # 排除目录项: 名称和页码之间有大量点号（超过 3 个连续的 .）
    if re.search(r"\.{3,}", text):
        return False, ""
    m = re.match(r"^[一二三四五六]、(.+)$", text)
    if not m:
        return False, ""
    raw_name = m.group(1).strip()
    # 精确匹配优先
    if raw_name in SECTION_MAP:
        return True, raw_name
    # 容错匹配: 从 SECTION_MAP 中找前缀匹配的（末尾有水印噪声）
    for name in SECTION_MAP:
        if raw_name.startswith(name):
            return True, name
    return False, ""


def is_item_title(line: dict) -> tuple[bool, int, str]:
    """判断一行是不是新闻条目开头（如"1. 标题"）。
    过滤条件: 字号 >= 10.8pt + 含足够中文 + 编号不能太大跳变。
    允许前导有少量水印噪声字符（1-2个孤立字/符号）。
    """
    text = line["text"].strip()
    # 直接匹配
    m = re.match(r"^(\d+)\.\s+(.+)$", text)
    if not m:
        # 尝试跳过前导噪声（1-3个非数字字符，通常是水印残留）
        m2 = re.match(r"^[^\d]{1,3}?(\d+)\.\s+(.+)$", text)
        if m2:
            num = int(m2.group(1))
            title_text = m2.group(2)
            # 验证：跳过的"噪声"部分必须真的是短的非正文内容
            prefix = text[:m2.start(1)]
            if len(prefix.strip()) <= 3:  # 噪声不超过3个字符
                m = m2
    if not m:
        return False, 0, ""
    # 字号过滤: 标题字号一般 >= 10.8pt（正文 9.5-10.5pt）
    if line["font_size"] < 10.8:
        return False, 0, ""
    num = int(m.group(1))
    title = m.group(2).strip()
    # 内容过滤: 标题必须以中文或正常英文词开头，不能全是数字/字母碎片
    # 统计中文字符比例
    cn_count = sum(1 for c in title if "一" <= c <= "鿿")
    if len(title) > 0 and cn_count / len(title) < 0.15 and num > 10:
        # 低序号可以是纯英文（美股相关），高序号低中文比例大概率是误识别
        return False, 0, ""
    if len(title) < 5:
        return False, 0, ""
    return True, num, title


def is_sources_label(line: dict) -> bool:
    return line["text"].strip() == "引用链接"


def is_source_name(line: dict) -> tuple[bool, int, str]:
    text = line["text"].strip()
    m = re.match(r"^\[(\d+)\]\s*(.+)$", text)
    if m:
        return True, int(m.group(1)), m.group(2).strip()
    return False, 0, ""


def is_source_url(line: dict) -> tuple[bool, str]:
    text = line["text"].strip()
    # URL 行以 ■ 开头，后跟 http(s)
    m = re.match(r"^[■□▲▶◆●]\s*(https?://\S+)", text)
    if m:
        return True, m.group(1).strip()
    # 有时没有符号，直接就是 URL
    if re.match(r"^https?://", text):
        return True, text.strip()
    return False, ""


def parse_report_from_lines(all_page_lines: list, report_date: str) -> DailyReport:
    """从结构化行解析 DailyReport。"""
    # 合并所有页的行，按页顺序
    all_lines = []
    for page_lines in all_page_lines:
        all_lines.extend(page_lines)

    # 1. 找导读
    editor_summary = ""
    summary_lines = []
    in_summary = False
    for line in all_lines:
        text = line["text"]
        if "本期导语：" in text:
            in_summary = True
            idx = text.index("本期导语：")
            summary_lines.append(text[idx + len("本期导语："):])
            continue
        if in_summary:
            # 遇到大字行（目录/栏目标题）就结束导读
            is_sec, _ = is_section_header(line)
            if is_sec or text.strip() == "目录" or line["font_size"] > 11.5:
                break
            if not text.strip():
                if summary_lines:
                    break
                continue
            summary_lines.append(text.strip())

    editor_summary = "".join(summary_lines).strip()

    # 2. 找各栏目起始位置
    # 注意: 目录页也有栏目名，内容页也有，会重复。
    # 策略: 每个栏目只保留最后一次出现（内容页的那个，后面跟着条目内容）
    section_starts_map: dict[str, int] = {}
    for i, line in enumerate(all_lines):
        is_sec, name = is_section_header(line)
        if is_sec:
            section_starts_map[name] = i  # 后面的覆盖前面的

    # 按出现顺序排列
    section_starts = sorted(section_starts_map.items(), key=lambda x: x[1])

    # 3. 解析每个栏目
    sections = []
    total_items = 0
    total_words = 0

    for sec_idx, (sec_name, start_idx) in enumerate(section_starts):
        cat = SECTION_MAP[sec_name]
        end_idx = section_starts[sec_idx + 1][1] if sec_idx + 1 < len(section_starts) else len(all_lines)
        sec_lines = all_lines[start_idx + 1:end_idx]

        items = parse_section(sec_lines, cat)
        for rank, item in enumerate(items, 1):
            item.rank = rank
            item.item_id = f"item_{total_items + rank:03d}"

        sections.append(ReportSection(
            section_id=cat,
            section_name=sec_name,
            item_count=len(items),
            items=items,
        ))
        total_items += len(items)
        total_words += sum(it.word_count for it in items)

    return DailyReport(
        report_id=f"daily_{report_date.replace('-', '')}",
        report_date=report_date,
        time_window_start=datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc),
        time_window_end=datetime.now(timezone.utc),
        total_items=total_items,
        total_word_count=total_words,
        editor_summary=editor_summary or None,
        sections=sections,
        generated_at=datetime.now(timezone.utc),
    )


def parse_section(lines: list, category: Category) -> list:
    """解析一个栏目内的所有条目。"""
    items = []
    current_title = ""
    current_body = []  # list of str，每行
    current_sources = []
    in_sources = False
    in_body = False

    def flush():
        nonlocal current_title, current_body, current_sources, in_sources, in_body
        if not current_title:
            return

        # 段落合并：空行分段，段内硬换行合并
        paragraphs = []
        para = []
        for line in current_body:
            line = line.strip()
            if not line:
                if para:
                    paragraphs.append("".join(para))
                    para = []
            else:
                para.append(line)
        if para:
            paragraphs.append("".join(para))
        details = "\n\n".join(paragraphs)

        # 水印已在 PyMuPDF 提取阶段作为「旋转文本」整体剔除，正文里不会再混入
        # 水印单字（杜/皓/杰）或日期数字；这里不再做单字删除——否则会把
        # "杜克大学" 这类正文字误删——仅做空白归一。
        current_title = re.sub(r"\s+", " ", current_title).strip()
        details = re.sub(r"[ \t]+", " ", details)
        details = re.sub(r"[ \t]*\n\n[ \t]*", "\n\n", details).strip()

        word_count = len(current_title) + len(details)
        item = ReportItem(
            item_id="tmp",
            event_id=f"evt_{len(items)}",
            rank=1,
            category=category,
            title=current_title.strip(),
            details=details,
            sources=[
                ReportSource(name=s["name"], url=s["url"], is_official=False)
                for s in current_sources if s.get("url")
            ],
            word_count=word_count,
        )
        items.append(item)
        current_title = ""
        current_body = []
        current_sources = []
        in_sources = False
        in_body = False

    i = 0
    while i < len(lines):
        line = lines[i]
        text = line["text"].strip()

        # 跳过页脚
        if text.startswith("推送人：") or (text.startswith("—第") and "页—" in text):
            i += 1
            continue

        # 检测新条目（以 "数字. " 开头为标志）
        is_title, num, title_text = is_item_title(line)
        if is_title and len(title_text) > 5:
            flush()
            current_title = title_text
            in_body = True
            title_fs = line["font_size"]
            i += 1
            # 标题合并策略: 最多 2 行（标题一般 1-2 行，极少 3 行）
            # 判断第二行是否是标题续行：字号接近 + 行间距接近 + 不以句号/完整词结尾
            title_lines_added = 0
            prev_y = line["y"]
            while i < len(lines) and title_lines_added < 1:  # 最多再合并 1 行
                next_line = lines[i]
                next_text = next_line["text"].strip()
                if not next_text:
                    break
                if is_sources_label(next_line):
                    break
                if is_item_title(next_line)[0]:
                    break
                if is_source_name(next_line)[0]:
                    break
                # 行距判断: 标题行距 ≈ 14-16pt（与字号相当），正文行距也差不多
                # 所以行距不可靠，用字号更靠谱
                # 但正文字号也有大的（首行下沉式）
                # 改用启发式: 如果当前标题已经有冒号结尾（冒号后接正文是常见结构），就不再续
                if current_title.rstrip().endswith(("：", ":")) and "。" not in next_text[:30]:
                    break
                # 字号必须与标题同档（PyMuPDF 标称值：标题 11.5 / 正文 10.5），
                # 用 0.8pt 容差即可干净区分"标题续行"与"正文"，避免正文被并入标题
                if next_line["font_size"] < title_fs - 0.8:
                    break
                # 合并
                current_title += next_text
                title_lines_added += 1
                prev_y = next_line["y"]
                i += 1
            continue

        if not in_body:
            i += 1
            continue

        # sources 区
        if is_sources_label(line):
            in_sources = True
            i += 1
            continue

        if in_sources:
            is_src, num, src_name = is_source_name(line)
            if is_src:
                # 清理来源名中的水印/页码残留
                # 1. 末尾的 2-3 位孤立数字（水印日期/页码）
                src_name = re.sub(r"\s*\d{2,3}$", "", src_name)
                # 2. "名称-数字" 模式（数字是水印）
                src_name = re.sub(r"-\d$", "", src_name)
                # 3. 末尾单个水印字（杜/皓/杰），但保留"日报""时报"等合法词
                #    只有当末尾单字且前面是空格/括号时才删
                src_name = re.sub(r"([\s（])[杜皓杰]$", r"\1", src_name)
                src_name = re.sub(r"^[杜皓杰]\s+", "", src_name)
                # 4. 夹在英文词中间的单字水印（如 "Communeify AI 日"）
                src_name = re.sub(r"([A-Za-z])\s+[日报]\s*$", r"\1", src_name)
                current_sources.append({"name": src_name.strip(), "url": ""})
                i += 1
                continue
            is_url, url = is_source_url(line)
            if is_url and current_sources:
                # URL 清理：去掉前后夹杂的水印字
                url = re.sub(r"^[日报杜皓杰\s]+", "", url)
                url = re.sub(r"[日报杜皓杰\s]+$", "", url)
                current_sources[-1]["url"] = url
                i += 1
                continue
            # 空行跳过
            if not text:
                i += 1
                continue
            # 下一个条目开始
            if is_item_title(line)[0]:
                in_sources = False
                continue
            # 其他情况跳过（页脚等）
            i += 1
            continue

        # 正文行
        if text:
            current_body.append(text)
        else:
            # 空行作为段落分隔
            if current_body and current_body[-1] != "":
                current_body.append("")
        i += 1

    flush()
    return items


async def main():
    parser = argparse.ArgumentParser(description="从 PDF 提取内容并重渲染日报（bbox 精确版）")
    parser.add_argument("pdf_path", help="输入 PDF 路径")
    parser.add_argument("--watermark", default="Cyber_Gm", help="水印前缀")
    parser.add_argument("--editor-name", default="广明", help="推送人姓名")
    parser.add_argument("--wechat-id", default="Cyber_Gm", help="微信号")
    parser.add_argument("--company", default="明雯科技", help="公司名")
    parser.add_argument("--report-title", default="AI 行业全球动态日报", help="报告标题")
    parser.add_argument("--output-dir", default="data/reports", help="输出目录")
    parser.add_argument("--date", help="报告日期 YYYY-MM-DD，默认从文件名提取")
    args = parser.parse_args()

    if not args.date:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", args.pdf_path)
        args.date = m.group(1) if m else datetime.now().strftime("%Y-%m-%d")

    print(f"PDF: {args.pdf_path}")
    print(f"日期: {args.date}")
    print(f"水印: {args.watermark}")

    # 1+2. PyMuPDF 解析原生文本行（斜向旋转水印在提取阶段整体剔除）
    all_page_lines = parse_pages_pymupdf(args.pdf_path)
    total_lines = sum(len(p) for p in all_page_lines)
    print(f"页面: {len(all_page_lines)} 页, 共 {total_lines} 行")

    # 3. 解析报告结构
    report = parse_report_from_lines(all_page_lines, args.date)
    print(f"栏目: {len(report.sections)} 个")
    for s in report.sections:
        print(f"  {s.section_name}: {s.item_count} 条")
    print(f"总条目: {report.total_items}")
    print(f"总字数: {report.total_word_count}")
    if report.editor_summary:
        print(f"导读: {len(report.editor_summary)} 字")

    # 4. 配置渲染器
    config = RenderConfig(
        report_title=args.report_title,
        company=args.company,
        wechat_id=args.wechat_id,
        editor_name=args.editor_name,
        output_dir=args.output_dir,
        filename_pattern=f"AI行业全球动态日报_{'{date}'}@{args.wechat_id}.pdf",
    )
    renderer = PDFRenderer(config=config)

    out_dir = Path(args.output_dir) / args.date
    out_dir.mkdir(parents=True, exist_ok=True)

    # HTML
    html_path = out_dir / f"report_{args.date}_CyberGm.html"
    html = renderer.render_html(report)
    html_path.write_text(html, encoding="utf-8")
    print(f"HTML: {html_path}")

    # JSON
    json_path = out_dir / f"daily_{args.date}_CyberGm.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"JSON: {json_path}")

    # PDF
    print("生成 PDF...")
    pdf_path = await renderer.render_pdf(report)
    print(f"PDF: {pdf_path}")
    print(f"大小: {pdf_path.stat().st_size / 1024:.1f} KB")
    print("\n完成！")


if __name__ == "__main__":
    asyncio.run(main())
