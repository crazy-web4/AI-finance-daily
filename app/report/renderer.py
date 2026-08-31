"""
PDF 渲染器
接口编号: IF-005
职责: 把 DailyReport → HTML → PDF
技术: Jinja2 + Playwright + Chromium
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from pydantic import BaseModel, Field
from app.utils.text_cleaner import complete_title, safe_render_clean

from app.schemas.models import DailyReport


class RenderConfig(BaseModel):
    """PDF 渲染配置。"""
    template_dir: str = "templates"
    template_name: str = "report.html"

    report_title: str = "AI 行业全球动态日报"
    company: str = "明雯科技"
    wechat_id: str = "Cyber_Gm"
    editor_name: str = "广明"
    subtitle_tags: str = "模型 · 资本 · 政策 · 科研 · 产业"

    output_dir: str = "data/reports"
    filename_pattern: str = "AI行业全球动态日报_{date}@Cyber_Gm.pdf"
    watermark_text: str = "AI财经日报 广明 Cyber_Gm"  # 中央水印文字前缀，渲染时会拼接日期


class PDFRenderer:
    """
    PDF 渲染器。

    用法:
        renderer = PDFRenderer()
        path = renderer.render(daily_report)
    """

    def __init__(self, config: RenderConfig | None = None) -> None:
        self.config = config or RenderConfig()
        self.env = Environment(
            loader=FileSystemLoader(self.config.template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self._ensure_output_dir()

    def _ensure_output_dir(self, report_date: str | None = None) -> Path:
        base = Path(self.config.output_dir)
        if report_date:
            out_dir = base / report_date
        else:
            out_dir = base
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    # ── HTML 渲染 ───────────────────────────────────

    def render_html(self, report: DailyReport) -> str:
        """把日报数据渲染成 HTML 字符串（CSS 内联，脱离相对路径依赖）。"""
        template = self.env.get_template(self.config.template_name)
        ctx = self._build_context(report)
        html = template.render(**ctx)
        # 架构评审 #18: 内联 CSS，临时 HTML 可放任意目录
        css_path = Path(self.config.template_dir) / "css" / "style.css"
        if css_path.exists():
            css = css_path.read_text(encoding="utf-8")
            # 动态生成 SVG 水印（带日期），打印时每页显示
            wm_text = self.config.watermark_text + " " + report.report_date.replace("-", ".")
            import html as _html
            wm_escaped = _html.escape(wm_text)
            svg_parts = [
                "data:image/svg+xml;utf8,",
                "<svg xmlns='http://www.w3.org/2000/svg' width='600' height='800'>",
                "<text x='300' y='420' font-family='Noto Serif SC, serif' ",
                "font-size='72' font-weight='700' ",
                "fill='rgba(180,150,120,0.10)' ",
                "text-anchor='middle' transform='rotate(-35 300 420)'>",
                wm_escaped,
                "</text></svg>",
            ]
            svg = "".join(svg_parts)
            wm_css_lines = [
                "background-image: url('" + svg + "');",
                "  background-repeat: repeat;",
                "  background-attachment: fixed;",
            ]
            wm_css = "\n".join(wm_css_lines)
            css = css.replace("/* __WATERMARK_SVG__ */", wm_css)
            style_tag = "<style>" + css + "</style>"
            html = html.replace(
                '<link rel="stylesheet" href="css/style.css">',
                style_tag,
            )
        return html

    def _build_context(self, report: DailyReport) -> dict:
        """构造 Jinja2 模板上下文。"""
        sections = []
        for s in report.sections:
            items = []
            for item in s.items:
                items.append({
                    "item_id": item.item_id,
                    "rank": item.rank,
                    "title": complete_title(item.title),
                    "key_data": [{"label": kd.label, "value": kd.value} for kd in item.key_data],
                    "details": self._render_paragraphs(safe_render_clean(item.details)),
                    "analysis": self._render_paragraphs(safe_render_clean(item.analysis)) if item.analysis else None,
                    "sources": [
                        {"name": src.name, "url": str(src.url), "is_official": src.is_official}
                        for src in item.sources
                    ],
                })
            sections.append({
                "section_id": s.section_id.value,
                "section_name": s.section_name,
                "item_count": s.item_count,
                "article_list": items,
            })

        return {
            "report_title": self.config.report_title,
            "company": self.config.company,
            "wechat_id": self.config.wechat_id,
            "editor_name": self.config.editor_name,
            "subtitle_tags": self.config.subtitle_tags,
            "report_date": report.report_date,
            "report_date_cn": self._format_date_cn(report.report_date),
            "watermark_text": f"{self.config.watermark_text} {report.report_date.replace("-", ".")}",
            "sections": sections,
            "editor_summary": self._render_paragraphs(safe_render_clean(report.editor_summary)) if report.editor_summary else None,
        }

    @staticmethod
    def _format_date_cn(date_str: str) -> str:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.year}年{dt.month}月{dt.day}日"

    @staticmethod
    def _render_paragraphs(text: str | None) -> Markup:
        """
        第二轮 R6: 把多段正文转成 HTML <p> 段落。
        LLM 输出的 details/analysis 用空行分段，直接塞进 HTML 会塌成一段。
        第三轮 P0: 逐段 html.escape 后再拼 <p>——Markup 会绕过 autoescape，
        不转义则上游网页片段可注入标签进 PDF。
        """
        import html as _html
        if not text:
            return Markup("")
        text = text.strip()
        if not text:
            return Markup("")
        # 按空行分段（兼容 CRLF 和 LF）
        normalized = text.replace(chr(13) + chr(10), chr(10))
        raw_paras = [p.strip() for p in normalized.split(chr(10) + chr(10)) if p.strip()]
        if not raw_paras:
            return Markup(_html.escape(text))
        paras_html = "".join("<p>" + _html.escape(p) + "</p>" for p in raw_paras)
        return Markup(paras_html)

    # ── PDF 渲染 ───────────────────────────────────

    async def render_pdf(self, report: DailyReport) -> Path:
        """渲染成 PDF 文件，返回文件路径。"""
        from playwright.async_api import async_playwright

        html = self.render_html(report)

        # 输出路径（按日期归档，文件已存在时加版本号后缀 v2/v3...）
        out_dir = self._ensure_output_dir(report.report_date)
        base_filename = self.config.filename_pattern.format(
            company=self.config.company,
            date=report.report_date,
        )
        stem = Path(base_filename).stem
        suffix = Path(base_filename).suffix
        candidate = out_dir / base_filename
        version = 2
        while candidate.exists():
            candidate = out_dir / f"{stem}_v{version}{suffix}"
            version += 1
        out_path = candidate

        # 架构评审 #18: 临时 HTML 放系统 tempdir（不再污染 templates/ 源码目录）
        import tempfile
        fd, tmp_name = tempfile.mkstemp(suffix=".html", prefix="daily_render_")
        os.close(fd)
        html_path = Path(tmp_name)
        html_path.write_text(html, encoding="utf-8")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.goto(f"file://{html_path}")
                await page.wait_for_load_state("networkidle")
                await page.pdf(
                    path=str(out_path),
                    format="A4",
                    print_background=True,
                    margin={
                        "top": "20mm",
                        "bottom": "22mm",
                        "left": "18mm",
                        "right": "18mm",
                    },
                    display_header_footer=False,
                )
                await browser.close()
        finally:
            if html_path.exists():
                html_path.unlink()

        return out_path

    # ── 保存 HTML（调试用） ─────────────────────────

    def save_html(self, report: DailyReport, filename: str | None = None) -> Path:
        """保存 HTML 文件（用于调试）。"""
        html = self.render_html(report)
        out_dir = self._ensure_output_dir(report.report_date)
        if not filename:
            filename = f"report_{report.report_date}.html"
        path = out_dir / filename
        path.write_text(html, encoding="utf-8")
        return path
