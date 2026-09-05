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
from urllib.parse import quote, unquote, urlparse

from app.storage.report_store import ReportArtifacts, ReportStore
from app.utils.timeutil import report_now
from app.web.feed import build_atom, build_rss


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
"""


def _layout(title: str, body: str) -> str:
    nav = ('<nav><a href="/">日报</a><a href="/health">运行健康</a><a href="/config">配置</a>'
           '<a href="/feed.xml">RSS</a></nav>')
    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)} · AI 财经日报看板</title><style>{CSS}</style></head><body>"
        f"<header><h1>📊 AI 财经日报看板</h1>{nav}</header><main>{body}</main></body></html>"
    )


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
    def handle(self, method: str, path: str) -> Response:
        parsed = urlparse(path)
        route = parsed.path
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
            if method == "GET" and route.startswith("/report/"):
                return self._page_report(unquote(route[len("/report/"):]))
            if method == "GET" and route.startswith("/file/"):
                return self._serve_file(route[len("/file/"):])
            if method == "GET" and route == "/api/reports":
                return Response.json(self.api_reports())
            if method == "GET" and route == "/api/health":
                return Response.json(self.health_summary())
            if method == "GET" and route == "/api/config":
                return Response.json(self.config_snapshot())
            if method == "POST" and route == "/trigger":
                return self._trigger()
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
            links.append(f"<a class='btn' href='/report/{latest.date}'>详情</a>")
            cards.append("<p>" + " ".join(links) + "</p>")
        else:
            cards.append("<p>暂无日报，先运行 <code>python run_daily.py --test</code>。</p>")
        cards.append('<form method="post" action="/trigger" style="margin-top:12px"><button class="btn" type="submit">🚀 后台触发一次出报（测试模式）</button></form>')
        cards.append("</div>")

        rows = []
        for art in reversed(list(self.store.iter_reports())[-8:]):
            rl = self.store.load_runlog(art.date) or {}
            raw = self.store.load_raw(art.date) or {}
            ok = rl.get("success")
            status = _badge(ok is True, "成功" if ok else ("失败" if ok is False else "无runlog"))
            rows.append(
                f"<tr><td><a href='/report/{art.date}'>{art.date}</a></td>"
                f"<td>{raw.get('total_items','-')}</td><td>{rl.get('elapsed_sec','-')}s</td>"
                f"<td>{status}</td>"
                f"<td>{'📕' if art.has_pdf else '—'} {'📄' if art.htmls else ''}</td></tr>"
            )
        body = "".join(cards) + (
            '<div class="card"><h2>🗂 近期日报</h2><table><tr><th>日期</th><th>条目</th><th>耗时</th><th>状态</th><th>产物</th></tr>'
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

    # ── 文件下载/预览 ──────────────────────────────
    def _serve_file(self, rel: str) -> Response:
        parts = [p for p in unquote(rel).split("/") if p and p != ".."]
        if len(parts) < 2:
            return Response.text("bad path", status=400)
        date, fname = parts[0], parts[-1]
        target = (self.store.root / date / fname).resolve()
        root = self.store.root.resolve()
        if not str(target).startswith(str(root)) or not target.exists():
            return Response.text("not found", status=404)
        ctype = {
            ".pdf": "application/pdf", ".html": "text/html; charset=utf-8",
            ".json": "application/json; charset=utf-8", ".md": "text/markdown; charset=utf-8",
            ".png": "image/png", ".jpg": "image/jpeg",
        }.get(target.suffix.lower(), "application/octet-stream")
        return Response(body=target.read_bytes(), status=200, content_type=ctype)

    # ── 后台触发 ───────────────────────────────────
    def _trigger(self) -> Response:
        try:
            log_dir = self.base_dir / "logs"
            log_dir.mkdir(exist_ok=True)
            logf = open(log_dir / "web_trigger.log", "ab")
            subprocess.Popen(self.trigger_cmd, cwd=str(self.base_dir), stdout=logf, stderr=logf,
                             start_new_session=True)
            return Response.json({"ok": True, "message": "已在后台启动出报（测试模式），详见 logs/web_trigger.log",
                                  "cmd": self.trigger_cmd})
        except Exception as e:  # noqa: BLE001
            return Response.json({"ok": False, "error": str(e)}, status=500)


# ── HTTP 传输层（薄封装） ──────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    app: WebApp = None  # 由 serve 注入

    def _do(self, method: str) -> None:
        resp = self.app.handle(method, self.path)
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
