"""
本地 Web 看板（建议 #1 · T-A1）
=================================================
``python main.py web --port 8910`` 起一个无第三方依赖的看板
（标准库 ``http.server``），提供：

- ``/``              今日卡片 + 近 7 天日报列表
- ``/report/<date>`` 日报详情（PDF 下载 / HTML 预览 / runlog 摘要 / 衍生格式）
- ``/health``        近 30 天成功率、平均耗时、缓存命中、LLM 调用
- ``/config``        当前配置（key 脱敏）与一键校验
- ``/feed.xml``      RSS 2.0（/atom.xml Atom 1.0）
- ``/file/<date>/<name>`` 下载/预览产物文件
- ``/api/reports|health|config`` JSON
- ``POST /trigger``  后台触发一次出报（子进程，不阻塞页面）

路由逻辑集中在 :class:`WebApp`，返回 :class:`Response`，
不触碰 socket，因此 ``tests/test_web.py`` 可直接测 handler。
"""

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlparse

from app.storage.report_store import ReportArtifacts, ReportStore
from app.utils.timeutil import report_now
from app.web.feed import build_atom, build_rss
from app.web.readview import (
    render_company_timeline,
    render_item_detail,
    render_reading_view,
    render_weekly_dashboard,
)


@dataclass
class Response:
    body: bytes
    status: int = 200
    content_type: str = "text/html; charset=utf-8"

    @classmethod
    def html(cls, text: str, status: int = 200) -> "Response":
        return cls(body=text.encode("utf-8"), status=status, content_type="text/html; charset=utf-8")

    @classmethod
    def json(cls, obj: Any, status: int = 200) -> "Response":
        return cls(body=json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"),
                   status=status, content_type="application/json; charset=utf-8")

    @classmethod
    def text(cls, text: str, status: int = 200, ctype: str = "text/plain; charset=utf-8") -> "Response":
        return cls(body=text.encode("utf-8"), status=status, content_type=ctype)


CSS = """
*{box-sizing:border-box}body{font-family:-apple-system,'PingFang SC',Arial,sans-serif;margin:0;background:#f4f6f9;color:#1a202c;line-height:1.6}
header{background:#1a365d;color:#fff;padding:16px 28px;display:flex;align-items:center;gap:20px;flex-wrap:wrap}
header h1{font-size:20px;margin:0}header nav a{color:#bee3f8;text-decoration:none;margin-right:16px;font-size:14px}
main{max-width:960px;margin:24px auto;padding:0 20px}
.card{background:#fff;border-radius:10px;padding:18px 22px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card h2{margin-top:0;font-size:17px;color:#2b6cb0;border-bottom:2px solid #ebf4ff;padding-bottom:8px}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px 10px;border-bottom:1px solid #edf2f7;text-align:left}
th{background:#f7fafc;color:#4a5568}a{color:#2b6cb0}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600}
.ok{background:#c6f6d5;color:#22543d}.warn{background:#fefcbf;color:#744210}.err{background:#fed7d7;color:#742a2a}
.muted{color:#718096;font-size:13px}.btn{display:inline-block;background:#2b6cb0;color:#fff;padding:8px 16px;border-radius:6px;text-decoration:none;font-size:14px;border:0;cursor:pointer}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.stat{background:#ebf8ff;border-radius:8px;padding:14px;text-align:center}.stat .n{font-size:26px;font-weight:700;color:#2b6cb0}.stat .l{font-size:12px;color:#4a5568}
code{background:#edf2f7;padding:1px 6px;border-radius:4px;font-size:13px}

.banner{background:#fef3c7;border:1px solid #f6e05e;color:#744210;padding:10px 16px;border-radius:8px;margin-bottom:16px;font-size:14px}
.read-card h2.sec-title{border-left:4px solid #4a5568;padding-left:10px;font-size:16px}
.news{border-left:3px solid #4a5568;padding:6px 0 14px 14px;margin:14px 0}
.news h4{margin:0 0 8px;font-size:15px;color:#1a202c}
.news .rank{display:inline-block;min-width:22px;height:22px;line-height:22px;text-align:center;background:#2b6cb0;color:#fff;border-radius:50%;font-size:12px;margin-right:6px}
.news p{margin:6px 0;font-size:14px;color:#2d3748}
.news .ana{background:#ebf8ff;border-left:3px solid #2b6cb0;padding:8px 12px;border-radius:6px;font-size:13px;color:#2c5282;margin:8px 0}
.kd-grid{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0}
.kd{background:#f7fafc;border:1px solid #e2e8f0;border-radius:6px;padding:4px 10px;font-size:13px}
.kd-l{color:#718096;margin-right:6px}.kd-v{font-weight:600;color:#2b6cb0}
.src{margin-top:6px;font-size:13px}.src a{margin-right:14px;text-decoration:none}
.wc{font-size:12px;margin-top:4px}
mark{background:#faf089;padding:0 2px;border-radius:2px}
.searchbar{display:flex;gap:8px;margin:6px 0 14px;flex-wrap:wrap}
.searchbar input[type=text]{flex:1;min-width:200px;padding:9px 12px;border:1px solid #cbd5e0;border-radius:6px;font-size:14px}
.searchbar select,.searchbar button{padding:9px 12px;border-radius:6px;border:1px solid #cbd5e0;font-size:14px}
.bar-row{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:13px}
.bar-row .lbl{width:150px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar{background:#2b6cb0;height:16px;border-radius:4px;min-width:2px}
.bar-row .num{color:#4a5568}
.heat{display:flex;gap:3px;align-items:flex-end;height:60px;margin:10px 0}
.heat .col{flex:1;background:#63b3ed;border-radius:3px 3px 0 0;min-height:2px;position:relative}
.sub-form input{padding:8px 10px;border:1px solid #cbd5e0;border-radius:6px;font-size:14px;margin:4px 6px 4px 0}
.tag{display:inline-block;background:#edf2f7;border-radius:12px;padding:2px 10px;font-size:12px;margin:2px}

.pager{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px}.btn.disabled{background:#a0aec0;cursor:default;pointer-events:none}
.toc-list{columns:2;list-style:none;padding:0;margin:0}.toc-list li{margin:4px 0;font-size:14px;break-inside:avoid}
.item-tools{margin-top:6px;display:flex;gap:14px;align-items:center}.detail-link{font-size:13px;text-decoration:none;font-weight:600}
.detail-title{font-size:20px;color:#1a202c;line-height:1.4}.src-list{list-style:none;padding:0;margin:0}.src-list li{margin:6px 0;font-size:13px;word-break:break-all}
"""


def _layout(title: str, body: str) -> str:
    nav = ('<nav><a href="/">日报</a><a href="/search">🔍 搜索</a><a href="/insights">📈 洞察</a><a href="/weekly">📅 周报</a>'
           '<a href="/my">⭐ 我的订阅</a><a href="/health">运行健康</a>'
           '<a href="/config">配置</a><a href="/feed.xml">RSS</a></nav>')
    searchbox = (
        '<form class="searchbar" action="/search" method="get" style="margin:0">'
        '<input type="text" name="q" placeholder="搜索情报：公司 / 关键词，如 OpenAI 融资" '
        'style="flex:0 1 260px;min-width:160px;padding:6px 10px">'
        '<button class="btn" type="submit" style="padding:6px 14px">搜索</button></form>'
    )
    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)} · AI 财经日报看板</title><style>{CSS}</style></head><body>"
        f"<header><h1>📊 AI 财经日报看板</h1>{nav}{searchbox}</header><main>{body}</main></body></html>"
    )


def _int_or_none(v):
    try:
        return int(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def _hl(text, q):
    from app.web.readview import highlight
    return highlight(text, q)



def _badge(ok: bool, label: str) -> str:
    cls = "ok" if ok else "err"
    return f'<span class="badge {cls}">{html.escape(label)}</span>'


class WebApp:
    """看板路由处理器（与 HTTP 传输解耦）。"""

    def __init__(self, reports_dir: str | Path = "data/reports", base_dir: str | Path = ".",
                 trigger_cmd: list[str] | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.store = ReportStore(reports_dir)
        self.trigger_cmd = trigger_cmd or [sys.executable, "run_daily.py", "--test"]

    # ── 路由 ───────────────────────────────────────
    def handle(self, method: str, path: str, body: bytes = b"") -> Response:
        parsed = urlparse(path)
        route = parsed.path
        self._post_body = body or b""
        try:
            if method == "GET" and route in ("/", "/index.html"):
                return self._page_index()
            if method == "GET" and route == "/health":
                return self._page_health()
            if method == "GET" and route == "/config":
                return self._page_config()
            if method == "GET" and route == "/feed.xml":
                return Response.text(build_rss(self.store), ctype="application/rss+xml; charset=utf-8")
            if method == "GET" and route == "/atom.xml":
                return Response.text(build_atom(self.store), ctype="application/atom+xml; charset=utf-8")
            if method == "GET" and route.startswith("/item/"):
                return self._page_item(route[len("/item/"):])
            if method == "GET" and route.startswith("/company/"):
                return self._page_company(unquote(route[len("/company/"):]))
            if method == "GET" and route == "/archive":
                return self._page_archive()
            if method == "GET" and route == "/weekly":
                return self._page_weekly(parsed.query)
            if method == "GET" and route.startswith("/read/"):
                return self._page_read(unquote(route[len("/read/"):]))
            if method == "GET" and route.startswith("/report/"):
                return self._page_report(unquote(route[len("/report/"):]))
            if method == "GET" and route.startswith("/file/"):
                return self._serve_file(route[len("/file/"):])
            if method == "GET" and route == "/search":
                return self._page_search(parsed.query)
            if method == "GET" and route == "/api/search":
                return self._api_search(parsed.query)
            if method == "GET" and route == "/insights":
                return self._page_insights()
            if method == "GET" and route == "/my":
                return self._page_my(parsed.query)
            if method == "GET" and route == "/subscriptions":
                return self._page_subscriptions()
            if method == "POST" and route == "/subscriptions":
                return self._post_subscriptions()
            if method == "GET" and route == "/api/subscriptions":
                return self._api_subscriptions()
            if method == "GET" and route == "/api/reports":
                return Response.json(self.api_reports())
            if method == "GET" and route == "/api/health":
                return Response.json(self.health_summary())
            if method == "GET" and route == "/api/config":
                return Response.json(self.config_snapshot())
            if method == "POST" and route == "/trigger":
                return self._trigger(parsed.query, body)
            return Response.html(_layout("404", "<div class='card'><h2>404</h2><p>页面不存在。</p></div>"), status=404)
        except Exception as e:  # noqa: BLE001 - 看板不因单点错误崩
            return Response.html(
                _layout("错误", f"<div class='card'><h2>处理出错</h2><p>{html.escape(type(e).__name__)}: {html.escape(str(e))}</p></div>"),
                status=500,
            )

    # ── 数据聚合 ───────────────────────────────────
    def health_summary(self, days: int = 30) -> dict[str, Any]:
        cutoff = (report_now() - timedelta(days=days)).date().isoformat()
        runlogs = [(d, rl) for d, rl in self.store.all_runlogs() if d >= cutoff]
        total = len(runlogs)
        ok = sum(1 for _, rl in runlogs if rl.get("success"))
        elapsed = [rl.get("elapsed_sec") for _, rl in runlogs if isinstance(rl.get("elapsed_sec"), (int, float))]
        llm_calls = sum((rl.get("llm_stats") or {}).get("calls", 0) for _, rl in runlogs)
        cache_hits = sum((rl.get("extract_stats") or {}).get("cache_hit", 0) for _, rl in runlogs)
        cache_total = sum((rl.get("extract_stats") or {}).get("total_urls", 0) for _, rl in runlogs)
        flags = [f for _, rl in runlogs for f in (rl.get("flags") or [])]
        return {
            "window_days": days,
            "runs": total,
            "success": ok,
            "success_rate": round(ok / total, 3) if total else None,
            "avg_elapsed_sec": round(sum(elapsed) / len(elapsed), 1) if elapsed else None,
            "llm_calls": llm_calls,
            "extract_cache_hit": cache_hits,
            "extract_cache_total": cache_total,
            "cache_hit_rate": round(cache_hits / cache_total, 3) if cache_total else None,
            "recent_flags": flags[-10:],
            "report_days": len(self.store.report_dates()),
        }

    def config_snapshot(self) -> dict[str, Any]:
        def mask(v: str | None) -> str:
            if not v:
                return "未配置"
            return v[:6] + "…" + v[-4:] if len(v) > 12 else "已配置"

        env = os.environ
        snap = {
            "timezone": os.environ.get("REPORT_TIMEZONE", "Asia/Shanghai"),
            "environment": os.environ.get("ENVIRONMENT", "development"),
            "keys": {
                "ANYSEARCH_API_KEY": mask(env.get("ANYSEARCH_API_KEY")),
                "ARK_API_KEY": mask(env.get("ARK_API_KEY")),
                "OPENAI_API_KEY": mask(env.get("OPENAI_API_KEY")),
                "TAVILY_API_KEY": mask(env.get("TAVILY_API_KEY")),
                "ALERT_WEBHOOK_URL": mask(env.get("ALERT_WEBHOOK_URL")),
            },
            "llm_model": env.get("LLM_MODEL", "(yaml 默认)"),
            "output_dir": "data/reports",
        }
        try:
            import yaml
            cfg_path = self.base_dir / "config" / "app_config.yaml"
            if cfg_path.exists():
                data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                snap["app_config"] = {k: data.get(k) for k in ("cache", "concurrency", "monitoring") if k in data}
        except Exception:
            snap["app_config"] = "(读取失败)"
        return snap

    def api_reports(self) -> dict[str, Any]:
        rows = []
        for art in list(self.store.iter_reports())[-30:]:
            rl = self.store.load_runlog(art.date) or {}
            raw = self.store.load_raw(art.date) or {}
            rows.append({
                "date": art.date,
                "pdf": str(art.primary_pdf()) if art.primary_pdf() else None,
                "html": str(art.htmls[0]) if art.htmls else None,
                "total_items": raw.get("total_items"),
                "success": rl.get("success"),
                "elapsed_sec": rl.get("elapsed_sec"),
            })
        return {"reports": rows, "count": len(rows)}

    # ── 页面 ───────────────────────────────────────
    def _page_index(self) -> Response:
        latest = self.store.latest_or_today()
        cards = ['<div class="card"><h2>📰 今日 / 最新日报</h2>']
        if latest:
            raw = self.store.load_raw(latest.date) or {}
            cards.append(f"<p><strong>日期</strong>：{latest.date}　<strong>条目</strong>：{raw.get('total_items','-')}　<strong>字数</strong>：{raw.get('total_word_count','-')}</p>")
            if raw.get("editor_summary"):
                cards.append(f"<p class='muted'>{html.escape(raw['editor_summary'][:300])}</p>")
            links = []
            if latest.primary_pdf():
                links.append(f"<a class='btn' href='/file/{latest.date}/{quote(latest.primary_pdf().name)}'>📕 打开 PDF</a>")
            if latest.htmls:
                links.append(f"<a class='btn' href='/file/{latest.date}/{quote(latest.htmls[0].name)}'>📄 HTML 预览</a>")
            links.append(f"<a class='btn' href='/read/{latest.date}'>📖 在线阅读</a>")
            links.append(f"<a class='btn' href='/report/{latest.date}'>产物详情</a>")
            cards.append("<p>" + " ".join(links) + "</p>")
        else:
            cards.append("<p>暂无日报，先运行 <code>python run_daily.py --test</code>。</p>")
        cards.append(
            '<form method="post" action="/trigger" style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">'
            '<button class="btn" type="submit" name="mode" value="test">🚀 触发出报（测试·省额度）</button>'
            '<button class="btn" type="submit" name="mode" value="full" style="background:#2f855a">📦 触发出报（全量·完整）</button>'
            '<span class="muted">后台运行，进度见 logs/web_trigger.log</span></form>')
        cards.append("</div>")

        rows = []
        for art in reversed(list(self.store.iter_reports())[-8:]):
            rl = self.store.load_runlog(art.date) or {}
            raw = self.store.load_raw(art.date) or {}
            ok = rl.get("success")
            status = _badge(ok is True, "成功" if ok else ("失败" if ok is False else "无runlog"))
            rows.append(
                f"<tr><td><a href='/read/{art.date}'>{art.date}</a></td>"
                f"<td>{raw.get('total_items','-')}</td><td>{rl.get('elapsed_sec','-')}s</td>"
                f"<td>{status}</td>"
                f"<td>{'📕' if art.has_pdf else '—'} {'📄' if art.htmls else ''}</td></tr>"
            )
        body = "".join(cards) + (
            '<div class="card"><h2>🗂 近期日报　<a class="muted" style="font-size:13px;font-weight:400" href="/archive">查看全部归档 →</a></h2>'
            '<table><tr><th>日期</th><th>条目</th><th>耗时</th><th>状态</th><th>产物</th></tr>'
            + "".join(rows) + "</table></div>"
        )
        return Response.html(_layout("首页", body))

    def _page_report(self, date: str) -> Response:
        art = self.store.get(date)
        if not art.has_report:
            return Response.html(_layout("无日报", f"<div class='card'><h2>{html.escape(date)}</h2><p>该日期无日报数据。</p></div>"), status=404)
        raw = self.store.load_raw(date) or {}
        rl = self.store.load_runlog(date) or {}
        b = [f"<div class='card'><h2>日报 {html.escape(date)}</h2>"]
        b.append(f'<p><a class="btn" href="/read/{date}">📖 在线阅读版</a></p>')
        b.append(f"<p class='muted'>report_id: {html.escape(str(raw.get('report_id')))} ｜ 条目 {raw.get('total_items')} ｜ 字数 {raw.get('total_word_count')}</p>")
        for f in sorted(art.dir.iterdir()):
            if f.is_file():
                icon = {"pdf": "📕", "html": "📄", "json": "🧾", "md": "📝"}.get(f.suffix.lstrip(".").lower(), "📎")
                b.append(f'<li>{icon} <a href="/file/{date}/{quote(f.name)}">{html.escape(f.name)}</a> <span class="muted">{f.stat().st_size//1024} KB</span></li>')
        b.append("</ul></div>")

        if raw.get("editor_summary"):
            b.append(f'<div class="card"><h2>📌 今日导读</h2><p>{html.escape(raw["editor_summary"])}</p></div>')

        b.append('<div class="card"><h2>📋 条目</h2>')
        for sec in raw.get("sections", []):
            if not sec.get("items"):
                continue
            b.append(f"<h3>{html.escape(sec.get('section_name',''))}</h3><ul>")
            for it in sec["items"]:
                b.append(f"<li>{it.get('rank')}. {html.escape(it.get('title',''))}</li>")
            b.append("</ul>")
        b.append("</div>")

        if rl:
            b.append('<div class="card"><h2>🩺 运行摘要</h2><table>')
            b.append(f"<tr><th>模式</th><td>{rl.get('mode')}</td><th>结果</th><td>{_badge(rl.get('success'), '成功' if rl.get('success') else '失败')}</td></tr>")
            b.append(f"<tr><th>耗时</th><td>{rl.get('elapsed_sec')}s</td><th>文章/事件</th><td>{rl.get('articles')} / {rl.get('events')}</td></tr>")
            b.append(f"<tr><th>LLM 调用</th><td>{(rl.get('llm_stats') or {}).get('calls')}</td><th>阶段</th><td>{html.escape(json.dumps(rl.get('stages',{}),ensure_ascii=False))}</td></tr>")
            if rl.get("flags"):
                b.append("<tr><th>flags</th><td colspan='3'>" + "<br>".join(html.escape(str(f)) for f in rl["flags"]) + "</td></tr>")
            b.append("</table></div>")
        return Response.html(_layout(f"日报 {date}", "".join(b)))

    def _page_health(self) -> Response:
        h = self.health_summary()
        stats = [
            ("运行次数", h["runs"]), ("成功率", f"{h['success_rate']:.0%}" if h["success_rate"] is not None else "-"),
            ("平均耗时", f"{h['avg_elapsed_sec']}s" if h["avg_elapsed_sec"] else "-"),
            ("LLM 调用", h["llm_calls"]), ("缓存命中率", f"{h['cache_hit_rate']:.0%}" if h["cache_hit_rate"] is not None else "-"),
            ("日报天数", h["report_days"]),
        ]
        body = '<div class="card"><h2>🩺 近 30 天运行健康</h2><div class="grid">'
        body += "".join(f'<div class="stat"><div class="n">{v}</div><div class="l">{html.escape(k)}</div></div>' for k, v in stats)
        body += "</div></div>"
        if h["recent_flags"]:
            body += '<div class="card"><h2>⚠️ 近期 flags</h2><ul>' + "".join(f"<li>{html.escape(str(f))}</li>" for f in h["recent_flags"]) + "</ul></div>"
        else:
            body += '<div class="card"><h2>✅ 无异常 flags</h2></div>'
        return Response.html(_layout("运行健康", body))

    def _page_config(self) -> Response:
        c = self.config_snapshot()
        rows = "".join(f"<tr><td>{html.escape(k)}</td><td><code>{html.escape(str(v))}</code></td></tr>" for k, v in c["keys"].items())
        body = (
            f'<div class="card"><h2>⚙️ 当前配置</h2>'
            f"<p>时区 <code>{html.escape(c['timezone'])}</code> ｜ 环境 <code>{html.escape(c['environment'])}</code> ｜ "
            f"模型 <code>{html.escape(str(c['llm_model']))}</code> ｜ 输出 <code>{html.escape(c['output_dir'])}</code></p>"
            f"<table><tr><th>配置项</th><th>状态</th></tr>{rows}</table>"
            f'<p class="muted">完整自检请运行 <code>python main.py doctor</code></p></div>'
        )
        return Response.html(_layout("配置", body))

    # ── T13-A 在线读报 ─────────────────────────────
    def _page_read(self, date: str, query: str = "", banner: str = "") -> Response:
        art = self.store.get(date)
        if not art.has_report:
            return Response.html(
                _layout("无日报", f"<div class='card'><h2>{html.escape(date)}</h2><p>该日期无日报数据。</p></div>"),
                status=404)
        raw = self.store.load_raw(date) or {}
        dates = self.store.report_dates()
        prev_d = next((d for d in dates if d < date), None)
        next_d = next((d for d in reversed(dates) if d > date), None)
        nav = ['<div class="pager">']
        nav.append(f'<a class="btn" href="/archive">🗂 归档</a>')
        nav.append(f'<a class="btn" href="/read/{prev_d}">← 上一期 {prev_d}</a>' if prev_d
                   else '<span class="btn disabled">← 无上一期</span>')
        nav.append(f'<a class="btn" href="/read/{next_d}">下一期 {next_d} →</a>' if next_d
                   else '<span class="btn disabled">已是最新 →</span>')
        nav.append("</div>")
        links = [f'<a class="btn" href="/">← 首页</a>']
        if art.primary_pdf():
            links.append(f'<a class="btn" href="/file/{date}/{quote(art.primary_pdf().name)}">📕 PDF</a>')
        if art.htmls:
            links.append(f'<a class="btn" href="/file/{date}/{quote(art.htmls[0].name)}">📄 原始HTML</a>')
        links.append(f'<a class="btn" href="/my?date={date}">⭐ 订阅版</a>')
        head = f"<div class='card'>{''.join(nav)}<p>{' '.join(links)}</p></div>"
        body = head + render_reading_view(raw, date, banner=banner, query=query)
        return Response.html(_layout(f"日报 {date}", body))

    # ── T14-A 历史归档 ─────────────────────────────
    def _page_archive(self) -> Response:
        groups: dict[str, list] = {}
        total = 0
        for d in reversed(self.store.report_dates()):
            art = self.store.get(d)
            rl = self.store.load_runlog(d) or {}
            raw = self.store.load_raw(d) or {}
            ok = rl.get("success")
            groups.setdefault(d[:7], []).append({
                "date": d, "items": raw.get("total_items", "-"),
                "elapsed": rl.get("elapsed_sec"), "ok": ok,
                "pdf": bool(art.primary_pdf()),
            })
            total += 1
        b = [f'<div class="card"><h2>🗂 历史归档（{total} 期）</h2>']
        b.append('<p class="muted">按月分组，点击日期进入在线阅读。</p></div>')
        for month in sorted(groups, reverse=True):
            b.append(f'<div class="card"><h2>{month}</h2><table><tr><th>日期</th><th>条目</th><th>耗时</th><th>状态</th><th>PDF</th></tr>')
            for r in groups[month]:
                badge = _badge(r["ok"] is True, "成功" if r["ok"] else ("失败" if r["ok"] is False else "无runlog"))
                b.append(
                    f'<tr><td><a href="/read/{r["date"]}">{r["date"]}</a></td>'
                    f'<td>{r["items"]}</td><td>{r["elapsed"] or "-"}s</td>'
                    f'<td>{badge}</td><td>{"📕" if r["pdf"] else "—"}</td></tr>')
            b.append("</table></div>")
        return Response.html(_layout("历史归档", "".join(b)))

    # ── 周报在线页 ─────────────────────────────────
    def _page_weekly(self, querystring: str = "") -> Response:
        from app.report.weekly import aggregate_weekly, load_week_reports, week_range
        qs = parse_qs(querystring)
        anchor_date = qs.get("date", [None])[0] or self.store.latest_or_today().date if self.store.latest_or_today() else None
        if anchor_date is None:
            return Response.html(_layout("周报", "<div class='card'><h2>📅 周报</h2><p>暂无日报数据。</p></div>"))
        reports, mon, sun = load_week_reports(self.store, anchor_date)
        # 周选择：上一/下一周
        from datetime import date as _date, timedelta as _td
        ad = _date.fromisoformat(mon)
        prev_mon = (ad - _td(days=7)).isoformat()
        next_mon = (ad + _td(days=7)).isoformat()
        pager = ('<div class="pager">'
                 f'<a class="btn" href="/weekly?date={prev_mon}">← 上一周</a>'
                 f'<a class="btn" href="/weekly?date={next_mon}">下一周 →</a>'
                 f'<a class="btn" href="/archive">🗂 归档</a></div>')
        if not reports:
            body = (f"<div class='card'>{pager}<h2>📅 周报 {mon} ~ {sun}</h2>"
                    "<p class='muted'>该周区间内无日报数据，试试切换周。</p></div>")
            return Response.html(_layout("周报", body))
        agg = aggregate_weekly(reports, mon, sun)
        body = f"<div class='card'>{pager}</div>" + render_weekly_dashboard(agg)
        # 已生成的离线周报产物
        wdir = self.base_dir / "data" / "reports" / "weekly" / mon
        if wdir.exists():
            files = sorted(wdir.glob("*"))
            if files:
                links = " ".join(
                    f'<a class="btn" href="/file/weekly/{quote(mon)}/{quote(f.name)}">📄 {html.escape(f.suffix.lstrip(".").upper())}</a>'
                    for f in files if f.suffix in (".html", ".pdf", ".md"))
                if links:
                    body += f'<div class="card"><h2>📦 离线周报产物</h2>{links}</div>'
        return Response.html(_layout(f"周报 {mon}", body))

    # ── T14-C 条目下钻 ─────────────────────────────
    def _find_item(self, date: str, item_id: str):
        raw = self.store.load_raw(date)
        if not raw:
            return None, None
        for sec in raw.get("sections", []):
            for it in sec.get("items") or []:
                if it.get("item_id") == item_id:
                    return it, raw
        return None, raw

    def _page_item(self, rel: str) -> Response:
        parts = [p for p in rel.split("/") if p]
        if len(parts) < 2:
            return Response.html(_layout("404", "<div class='card'><p>链接格式应为 /item/&lt;日期&gt;/&lt;条目id&gt;。</p></div>"), status=404)
        date, item_id = parts[0], parts[1]
        item, _ = self._find_item(date, item_id)
        if item is None:
            return Response.html(_layout("未找到", f"<div class='card'><h2>条目不存在</h2><p>{html.escape(date)} / {html.escape(item_id)}</p></div>"), status=404)
        # 跨期相关：取标题首段关键词做检索
        related = []
        try:
            from app.storage.query import search_conn
            kw = (item.get("title") or "").split("，")[0][:12]
            conn = self._open_db()
            try:
                related = search_conn(conn, keyword=kw, limit=12)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            related = []
        head = (f"<div class='card'><p><a class='btn' href='/read/{date}'>← 返回 {date} 日报</a> "
                f"<a class='btn' href='/archive'>🗂 归档</a></p></div>")
        body = head + render_item_detail(item, date, related=related)
        return Response.html(_layout("深度阅读", body))

    # ── T14-D 公司时间线 ───────────────────────────
    def _page_company(self, name: str) -> Response:
        name = name.strip()
        if not name:
            return Response.html(_layout("公司", "<div class='card'><p>缺少公司名。</p></div>"), status=400)
        rows = []
        try:
            from app.storage.query import search_conn
            conn = self._open_db()
            try:
                rows = search_conn(conn, keyword=name, limit=100)
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            return Response.html(_layout("公司", f"<div class='card'><p>情报库不可用：{html.escape(str(e))}</p></div>"), status=200)
        # 公司名标签（从洞察页高频公司也可跳来）
        head = (f"<div class='card'><p><a class='btn' href='/insights'>← 返回洞察</a> "
                f"<a class='btn' href='/search?q={quote(name)}'>🔍 全文搜索「{html.escape(name)}」</a></p></div>")
        body = head + render_company_timeline(name, rows)
        return Response.html(_layout(f"公司：{name}", body))

    # ── T13-B 全站情报搜索 ─────────────────────────
    def _open_db(self):
        from app.storage.db import DEFAULT_DB_PATH, connect
        from app.storage.indexer import build_index
        db_path = self.base_dir / DEFAULT_DB_PATH
        if not db_path.exists():
            build_index(str(db_path), str(self.base_dir / "data" / "reports"))
        return connect(str(db_path))

    def _page_search(self, querystring: str) -> Response:
        qs = parse_qs(querystring)
        q = (qs.get("q", [""])[0]).strip()
        days = _int_or_none(qs.get("days", [None])[0])
        category = qs.get("category", [""])[0].strip() or None
        body = ['<div class="card"><h2>🔍 全站情报搜索</h2>']
        body.append(
            '<form class="searchbar" action="/search" method="get">'
            f'<input type="text" name="q" value="{html.escape(q)}" placeholder="公司 / 关键词，如 OpenAI 融资">'
            '<select name="days"><option value="">全部时间</option>'
            + "".join(f'<option value="{d}"{" selected" if days==d else ""}>近 {d} 天</option>'
                      for d in (7, 30, 90, 180))
            + '</select>'
            '<button class="btn" type="submit">搜索</button></form>')
        if not q:
            body.append('<p class="muted">输入关键词检索全部历史日报（标题 / 正文 / 点评 / 公司名）。</p></div>')
            return Response.html(_layout("搜索", "".join(body)))
        try:
            from app.storage.query import search_conn
            conn = self._open_db()
            try:
                rows = search_conn(conn, keyword=q, days=days, category=category)
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            body.append(f'<p>搜索失败：{html.escape(str(e))}</p></div>')
            return Response.html(_layout("搜索", "".join(body)), status=500)
        body.append(f'<p class="muted">「{html.escape(q)}」命中 {len(rows)} 条</p></div>')
        if not rows:
            body.append('<div class="card"><p>没有匹配条目。换个关键词，或先用 <code>python main.py index build</code> 建库。</p></div>')
        else:
            body.append('<div class="card"><table><tr><th>日期</th><th>栏目</th><th>重要度</th><th>标题</th></tr>')
            for r in rows:
                comp = "、".join((r.get("companies") or [])[:3])
                comp_s = f' <span class="muted">[{html.escape(comp)}]</span>' if comp else ""
                body.append(
                    f'<tr><td><a href="/read/{r["date"]}">{r["date"]}</a></td>'
                    f'<td>{html.escape(r.get("section_name") or "")}</td>'
                    f'<td>{r.get("importance", "-")}</td>'
                    f'<td><a href="/read/{r["date"]}">{_hl(r.get("title"), q)}</a>{comp_s}</td></tr>')
            body.append("</table></div>")
        return Response.html(_layout(f"搜索：{q}", "".join(body)))

    def _api_search(self, querystring: str) -> Response:
        qs = parse_qs(querystring)
        q = (qs.get("q", [""])[0]).strip()
        if not q:
            return Response.json({"error": "缺少 q 参数"}, status=400)
        days = _int_or_none(qs.get("days", [None])[0])
        category = qs.get("category", [""])[0].strip() or None
        from app.storage.query import search_conn
        conn = self._open_db()
        try:
            rows = search_conn(conn, keyword=q, days=days, category=category)
        finally:
            conn.close()
        return Response.json({"query": q, "count": len(rows), "results": rows})

    # ── T13-C 趋势洞察 ─────────────────────────────
    def _page_insights(self) -> Response:
        from app.storage.trend import funding_hotspots, headline_diff, topic_heat
        try:
            conn = self._open_db()
        except Exception as e:  # noqa: BLE001
            return Response.html(_layout("洞察", f"<div class='card'><h2>📈 趋势洞察</h2><p>情报库不可用：{html.escape(str(e))}</p><p class='muted'>运行 <code>python main.py index build</code> 后重试。</p></div>"))
        b = ['<div class="card"><h2>📈 趋势洞察</h2><p class="muted">基于全部已索引日报聚合。</p></div>']
        try:
            from app.storage.db import stats_overview
            s = stats_overview(conn)
            # 栏目分布条形图
            b.append('<div class="card"><h2>📰 栏目分布</h2>')
            sections = sorted(s.get("by_section", []), key=lambda x: x["n"], reverse=True)
            mx = max((x["n"] for x in sections), default=1) or 1
            for sec in sections:
                w = max(2, int(sec["n"] / mx * 220))
                b.append(f'<div class="bar-row"><span class="lbl">{html.escape(sec["section_name"])}</span>'
                         f'<span class="bar" style="width:{w}px"></span><span class="num">{sec["n"]}</span></div>')
            b.append("</div>")
            # 公司 TOP
            b.append('<div class="card"><h2>🏢 高频公司 / 机构 TOP 15</h2><p>')
            for c in (s.get("top_companies") or [])[:15]:
                nm = c["name"]
                b.append(f'<a class="tag" href="/company/{quote(nm)}">{html.escape(nm)} · {c["mentions"]}次/{c["days"]}天</a> ')
            b.append("</p></div>")
            # 融资热点
            fh = funding_hotspots(conn, weeks=8, top=12)
            if fh:
                b.append('<div class="card"><h2>💰 近 8 周融资热点</h2><table><tr><th>公司</th><th>提及</th><th>活跃天数</th></tr>')
                for f in fh:
                    b.append(f'<tr><td>{html.escape(f["company"])}</td><td>{f["count"]}</td><td>{f["days"]}</td></tr>')
                b.append("</table></div>")
            # 头条差异
            hd = headline_diff(conn)
            b.append('<div class="card"><h2>🔄 今日头条周报</h2>')
            b.append(f'<p class="muted">本周（{hd.get("week_start","-")}）vs 上周（{hd.get("last_week_start","-")}）</p>')
            b.append(f'<p><strong>🆕 本周新增（{len(hd.get("added",[]))}）</strong></p><ul>')
            for r in hd.get("added", [])[:10]:
                b.append(f'<li>[{r["date"]}] {html.escape(r["title"])}</li>')
            b.append("</ul>")
            b.append(f'<p><strong>📉 上周淡出（{len(hd.get("dropped",[]))}）</strong></p><ul>')
            for r in hd.get("dropped", [])[:10]:
                b.append(f'<li>[{r["date"]}] {html.escape(r["title"])}</li>')
            b.append("</ul></div>")
            # 话题热度（纯 CSS 柱状，近 8 周总条目）
            heat = topic_heat(conn, weeks=8)
            if heat:
                cols = list(heat.values())
                totals = [(c["week_start"], sum(c["topics"].values())) for c in cols]
                hmax = max((t for _, t in totals), default=1) or 1
                b.append('<div class="card"><h2>📊 近 8 周出报量</h2><div class="heat">')
                for ws, t in totals:
                    h = max(3, int(t / hmax * 56))
                    b.append(f'<div class="col" style="height:{h}px" title="{ws}: {t}条"></div>')
                b.append("</div><p class='muted'>" + " · ".join(f"{ws[5:]}:{t}" for ws, t in totals) + "</p></div>")
        finally:
            conn.close()
        return Response.html(_layout("趋势洞察", "".join(b)))

    # ── T13-D 我的订阅 / 个性化 ─────────────────────
    def _sub_store(self):
        from app.personalization.store import SubscriptionStore
        return SubscriptionStore(self.base_dir / "data" / "subscriptions")

    def _page_my(self, querystring: str) -> Response:
        from app.personalization.filter import filter_report
        qs = parse_qs(querystring)
        user = qs.get("user", ["default"])[0]
        date = qs.get("date", [None])[0]
        sub = self._sub_store().get(user)
        art = self.store.find_on_date(date) if date else self.store.latest_or_today()
        if art is None:
            return Response.html(_layout("我的订阅", "<div class='card'><h2>⭐ 我的订阅</h2><p>暂无日报。</p></div>"))
        report = self.store.load_report(art.date)
        if report is None:
            return Response.html(_layout("我的订阅", "<div class='card'><p>日报数据无法解析。</p></div>"), status=500)
        if not sub.companies and not sub.categories:
            banner = "你还没有设置订阅条件，下面是完整日报。到「我的订阅」页添加关注公司/栏目即可得到定制版。"
            filtered = report
        else:
            scope = "、".join(sub.companies + sub.categories)
            banner = f"📌 订阅版（{user}）｜关注：{scope}"
            filtered = filter_report(report, sub.companies, sub.categories, user=user)
        raw = filtered.model_dump()
        body = (f"<div class='card'><p><a class='btn' href='/subscriptions'>⚙️ 管理订阅</a> "
                f"<a class='btn' href='/read/{art.date}'>看完整版</a></p></div>")
        body += render_reading_view(raw, art.date, banner=banner)
        return Response.html(_layout(f"我的订阅 {art.date}", body))

    def _page_subscriptions(self) -> Response:
        store = self._sub_store()
        subs = list((self.base_dir / "data" / "subscriptions").glob("*.yaml")) if (self.base_dir / "data" / "subscriptions").exists() else []
        b = ['<div class="card"><h2>⭐ 订阅管理</h2>']
        if subs:
            b.append("<p>已有订阅：</p><ul>")
            for f in sorted(subs):
                s = store.get(f.stem)
                b.append(f'<li><strong>{html.escape(s.name)}</strong>：公司={html.escape("、".join(s.companies) or "—")} ｜ 栏目={html.escape("、".join(s.categories) or "—")}</li>')
            b.append("</ul>")
        b.append(
            '<form class="sub-form" method="post" action="/subscriptions">'
            '<p>订阅名（默认 default）：<input type="text" name="name" value="default"></p>'
            '<p>关注公司（逗号分隔，如 OpenAI,Anthropic,英伟达）：<br><input type="text" name="companies" size="60"></p>'
            '<p>关注栏目（栏目 id，逗号分隔）：<br><input type="text" name="categories" size="60" placeholder="top_news,funding,model_tech,policy,research,industry,us_stocks"></p>'
            '<button class="btn" type="submit">保存订阅</button></form>')
        b.append('<p class="muted">保存后到 <a href="/my">⭐ 我的订阅</a> 查看个性化日报。</p></div>')
        return Response.html(_layout("订阅管理", "".join(b)))

    def _post_subscriptions(self) -> Response:
        from app.personalization.store import Subscription
        form = self._post_body.decode("utf-8", "ignore")
        data = parse_qs(form)
        name = (data.get("name", ["default"])[0] or "default").strip() or "default"
        companies = [c.strip() for c in (data.get("companies", [""])[0]).split(",") if c.strip()]
        categories = [c.strip() for c in (data.get("categories", [""])[0]).split(",") if c.strip()]
        self._sub_store().save(Subscription(name=name, companies=companies, categories=categories))
        body = (f'<div class="card"><h2>✅ 订阅已保存</h2><p>订阅 <strong>{html.escape(name)}</strong>：'
                f'公司 {html.escape("、".join(companies) or "—")} ｜ 栏目 {html.escape("、".join(categories) or "—")}</p>'
                f'<p><a class="btn" href="/my?user={quote(name)}">查看我的订阅日报 →</a> '
                f'<a class="btn" href="/subscriptions">返回</a></p></div>')
        return Response.html(_layout("已保存", body))

    def _api_subscriptions(self) -> Response:
        d = self.base_dir / "data" / "subscriptions"
        out = []
        if d.exists():
            for f in sorted(d.glob("*.yaml")):
                s = self._sub_store().get(f.stem)
                out.append({"name": s.name, "companies": s.companies, "categories": s.categories})
        return Response.json({"subscriptions": out})


    # ── 文件下载/预览 ──────────────────────────────
    def _serve_file(self, rel: str) -> Response:
        parts = [p for p in unquote(rel).split("/") if p and p != ".."]
        if len(parts) < 2:
            return Response.text("bad path", status=400)
        # 常规：/file/<date>/<fname>；周报：/file/weekly/<mon>/<fname>（忽略 ?dir= 查询串）
        target = (self.store.root / Path(*parts)).resolve()
        root = self.store.root.resolve()
        if not str(target).startswith(str(root)) or not target.exists() or not target.is_file():
            return Response.text("not found", status=404)
        ctype = {
            ".pdf": "application/pdf", ".html": "text/html; charset=utf-8",
            ".json": "application/json; charset=utf-8", ".md": "text/markdown; charset=utf-8",
            ".png": "image/png", ".jpg": "image/jpeg",
        }.get(target.suffix.lower(), "application/octet-stream")
        return Response(body=target.read_bytes(), status=200, content_type=ctype)

    # ── 后台触发 ───────────────────────────────────
    def _trigger(self, querystring: str = "", body: bytes = b"") -> Response:
        try:
            params = {k: v[0] for k, v in parse_qs(querystring).items()}
            if body:
                params.update({k: v[0] for k, v in parse_qs(body.decode("utf-8", "ignore")).items()})
            mode = params.get("mode", "test")
            if mode not in ("test", "full"):
                mode = "test"
            cmd = [sys.executable, "run_daily.py", "--test" if mode == "test" else "--full"]
            log_dir = self.base_dir / "logs"
            log_dir.mkdir(exist_ok=True)
            logf = open(log_dir / "web_trigger.log", "ab")
            subprocess.Popen(cmd, cwd=str(self.base_dir), stdout=logf, stderr=logf,
                             start_new_session=True)
            label = "测试模式（省额度）" if mode == "test" else "全量模式（完整出报）"
            return Response.json({"ok": True, "mode": mode,
                                  "message": f"已在后台启动出报（{label}），详见 logs/web_trigger.log",
                                  "cmd": cmd})
        except Exception as e:  # noqa: BLE001
            return Response.json({"ok": False, "error": str(e)}, status=500)


# ── HTTP 传输层（薄封装） ──────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    app: WebApp = None  # 由 serve 注入

    def _do(self, method: str) -> None:
        body = b""
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(length) if length else b""
            except (ValueError, TypeError):
                body = b""
        resp = self.app.handle(method, self.path, body=body)
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(resp.body)

    def do_GET(self) -> None:
        self._do("GET")

    def do_POST(self) -> None:
        self._do("POST")

    def log_message(self, *args: Any) -> None:  # 静默，避免污染终端
        pass


def serve(port: int = 8910, host: str = "127.0.0.1", **kwargs: Any) -> None:
    app = WebApp(**kwargs)
    handler = type("BoundHandler", (_Handler,), {"app": app})
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"📊 AI 财经日报看板已启动: http://{host}:{port}")
    print("   按 Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
