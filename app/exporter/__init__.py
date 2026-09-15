"""
多格式导出（建议 #4 · T-B4）
PDF 之外，同时产出 Markdown / 公众号 / 邮件 / Notion 四种格式。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.schemas.models import DailyReport
from app.exporter.markdown import export_markdown
from app.exporter.wechat import export_wechat
from app.exporter.email import export_email
from app.exporter.notion import export_notion

ALL_EXPORTERS = ("markdown", "wechat", "email", "notion")

_EXPORTER_FN = {
    "markdown": export_markdown,
    "wechat": export_wechat,
    "email": export_email,
    "notion": export_notion,
}


def run_all_exporters(
    report: DailyReport,
    out_dir: str | Path,
    enabled: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """
    运行全部（或指定）导出器。

    各导出器独立 try：单个失败只记录，不影响其它格式与 PDF 主流程。
    返回 ``{format: {"path": Path|None, "ok": bool, "error": str|None}}``。
    """
    enabled = tuple(enabled) if enabled else ALL_EXPORTERS
    out_dir = Path(out_dir)
    results: dict[str, Any] = {}
    for fmt in ALL_EXPORTERS:
        if fmt not in enabled:
            continue
        try:
            path = _EXPORTER_FN[fmt](report, out_dir)
            results[fmt] = {"path": path, "ok": True, "error": None}
        except Exception as e:  # noqa: BLE001 - 单格式失败不阻断
            results[fmt] = {"path": None, "ok": False, "error": f"{type(e).__name__}: {e}"}
    return results
