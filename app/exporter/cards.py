"""
衍生卡片图（建议 #5 · T-B5）
=================================================
每条事件生成一张 1080×1080 可分享卡片（朋友圈/微博/小红书）。

- 使用 Pillow 绘制 PNG（``pip install Pillow``）。
- 支持 light / dark 两种主题；``--only top`` 只出头条卡片。
- 中文字体自动探测常见路径；缺失时降级 Pillow 默认字体（不崩溃，
  测试仅校验尺寸/文件可读，不依赖字形）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from app.schemas.models import DailyReport

CARD_SIZE = (1080, 1080)
MARGIN = 80

# (目录, 常规, 粗体) 候选字体；命中即用
_FONT_CANDIDATES = [
    ("/System/Library/Fonts", "Hiragino Sans GB.ttc", "Hiragino Sans GB.ttc"),
    ("/System/Library/Fonts/Supplemental", "Songti.ttc", "Songti.ttc"),
    ("/System/Library/Fonts", "STHeiti Medium.ttc", "STHeiti Medium.ttc"),
    ("/usr/share/fonts/opentype/noto", "NotoSansCJK-Regular.ttc", "NotoSansCJK-Bold.ttc"),
    ("/usr/share/fonts/truetype/noto", "NotoSansCJK-Regular.ttc", "NotoSansCJK-Bold.ttc"),
    ("/usr/share/fonts", "NotoSansCJK-Regular.ttc", "NotoSansCJK-Bold.ttc"),
    ("C:/Windows/Fonts", "msyh.ttc", "msyhbd.ttc"),
]

_THEME = {
    "light": {"bg": (247, 248, 250), "card": (255, 255, 255), "accent": (43, 108, 176),
              "title": (26, 32, 44), "body": (74, 85, 104), "keydata": (192, 86, 33), "footer": (160, 174, 192)},
    "dark": {"bg": (15, 23, 42), "card": (30, 41, 59), "accent": (96, 165, 250),
             "title": (241, 245, 249), "body": (203, 213, 225), "keydata": (251, 146, 60), "footer": (148, 163, 184)},
}

_CATEGORY_COLOR = {
    "top_news": (229, 62, 62), "model_tech": (49, 130, 206), "funding": (192, 86, 33),
    "policy": (126, 87, 194), "research": (38, 166, 154), "industry": (72, 152, 103),
    "us_stocks": (113, 92, 62),
}


def find_font(size: int, bold: bool = False):
    """返回可用的 TrueType 字体；找不到则返回 Pillow 默认位图字体。"""
    from PIL import ImageFont
    for folder, regular, bold_name in _FONT_CANDIDATES:
        name = bold_name if bold else regular
        p = Path(folder) / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    """按像素宽度贪心折行（中文逐字、英文整词，避免把 Latin 单词拦腰截断）。"""
    import re
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\.\,\-\:]*|[\u4e00-\u9fff]|\s+|.", text or "")
    lines: list[str] = []
    cur = ""
    for tok in tokens:
        if tok == "\n":
            lines.append(cur.rstrip())
            cur = ""
            continue
        trial = cur + tok
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            # 超长的单个 Latin 单词硬切，其余整体换行
            if tok.strip() and draw.textlength(tok, font=font) > max_width:
                while tok:
                    cut = 1
                    for i in range(1, len(tok) + 1):
                        if draw.textlength(tok[:i], font=font) <= max_width:
                            cut = i
                        else:
                            break
                    if cur:
                        lines.append(cur.rstrip())
                    cur = tok[:cut]
                    tok = tok[cut:]
                continue
            if cur.strip():
                lines.append(cur.rstrip())
            cur = tok.lstrip() if tok.strip() else ""
    if cur.strip() or not lines:
        lines.append(cur.rstrip())
    return lines or [""]


def _safe_filename(text: str, idx: int) -> str:
    digest = hashlib.sha1(text.encode()).hexdigest()[:6]
    return f"{idx:02d}_{digest}.png"


def render_card(
    title: str,
    category_name: str,
    section_id: str,
    date: str,
    key_data: list[dict[str, str]] | None = None,
    body: str = "",
    style: str = "light",
    out_path: str | Path | None = None,
    brand: str = "AI 财经日报",
) -> Path:
    """绘制单张 1080×1080 卡片并保存，返回路径。"""
    from PIL import Image, ImageDraw

    theme = _THEME.get(style, _THEME["light"])
    img = Image.new("RGB", CARD_SIZE, theme["bg"])
    draw = ImageDraw.Draw(img)

    # 顶部色条
    accent = _CATEGORY_COLOR.get(section_id, theme["accent"])
    draw.rectangle([0, 0, CARD_SIZE[0], 28], fill=accent)

    # 卡片主体
    draw.rounded_rectangle([MARGIN - 30, 120, CARD_SIZE[0] - MARGIN + 30, CARD_SIZE[1] - 160],
                           radius=28, fill=theme["card"])

    # 栏目标签
    tag_font = find_font(30, bold=True)
    tag = f"# {category_name}"
    draw.text((MARGIN, 170), tag, font=tag_font, fill=accent)

    # 标题
    title_font = find_font(52, bold=True)
    title_lines = wrap_text(draw, title, title_font, CARD_SIZE[0] - 2 * MARGIN)[:5]
    y = 240
    for line in title_lines:
        draw.text((MARGIN, y), line, font=title_font, fill=theme["title"])
        y += 70

    # 关键数据
    if key_data:
        kd_font = find_font(34, bold=True)
        y += 10
        kd_text = " ｜ ".join(f"{k['label']}: {k['value']}" for k in key_data[:4])
        for line in wrap_text(draw, kd_text, kd_font, CARD_SIZE[0] - 2 * MARGIN)[:3]:
            draw.text((MARGIN, y), line, font=kd_font, fill=theme["keydata"])
            y += 50

    # 正文摘要（截断）
    if body:
        body_font = find_font(28)
        y = max(y + 20, 700)
        snippet = body[:240] + ("…" if len(body) > 240 else "")
        for line in wrap_text(draw, snippet, body_font, CARD_SIZE[0] - 2 * MARGIN)[:5]:
            draw.text((MARGIN, y), line, font=body_font, fill=theme["body"])
            y += 44

    # 底部品牌水印
    foot_font = find_font(26)
    draw.text((MARGIN, CARD_SIZE[1] - 110), brand, font=foot_font, fill=accent)
    date_w = draw.textlength(date, font=foot_font)
    draw.text((CARD_SIZE[0] - MARGIN - date_w, CARD_SIZE[1] - 110), date, font=foot_font, fill=theme["footer"])

    out_path = Path(out_path) if out_path else Path("card.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")
    return out_path


def generate_cards(
    report: DailyReport,
    out_dir: str | Path,
    style: str = "light",
    only: str | None = None,
) -> list[Path]:
    """
    为日报每条事件生成卡片。

    only="top" 仅头条；None 为全部。文件按栏目分目录：``cards/{section}/NN_xxx.png``。
    """
    out_dir = Path(out_dir)
    paths: list[Path] = []
    counter = 0
    for section in report.sections:
        sid = section.section_id.value if hasattr(section.section_id, "value") else str(section.section_id)
        if only == "top" and sid != "top_news":
            continue
        sub = out_dir / sid
        for item in section.items:
            counter += 1
            kd = [{"label": k.label, "value": k.value} for k in item.key_data]
            fname = _safe_filename(item.title, counter)
            p = render_card(
                title=item.title,
                category_name=section.section_name,
                section_id=sid,
                date=report.report_date,
                key_data=kd,
                body=item.details or "",
                style=style,
                out_path=sub / fname,
            )
            paths.append(p)
    return paths
