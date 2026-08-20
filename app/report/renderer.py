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
from pydantic import BaseModel, Field

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

    show_toc: bool = True  # 页数少时不显示目录
    show_cover: bool = True


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
            html = html.replace(
                '<link rel="stylesheet" href="css/style.css">',
                f"<style>{css}</style>",
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
                    "title": item.title,
                    "lead": item.lead,
                    "key_data": [{"label": kd.label, "value": kd.value} for kd in item.key_data],
                    "details": item.details,
                    "analysis": item.analysis,
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
            "watermark_text": f"广明 {report.report_date.replace('-', '.')}",
            "sections": sections,
            "editor_summary": report.editor_summary,
            "show_toc": self.config.show_toc,
            "show_cover": self.config.show_cover,
        }

    @staticmethod
    def _format_date_cn(date_str: str) -> str:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.year}年{dt.month}月{dt.day}日"

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
