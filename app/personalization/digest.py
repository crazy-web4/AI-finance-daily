"""
订阅推送闭环（第 14 批续 · T14c）
=================================================
出报后，为每个订阅（``data/subscriptions/*.yaml``）生成个性化过滤版，
把摘要推送到已配置的通道：

- **Webhook**（钉钉 / 企微 / 通用 JSON）：复用 ``app.utils.alert.send_alert``
  的通道识别，走环境变量 ``ALERT_WEBHOOK_URL`` 或订阅自带 webhook。
- **邮件 SMTP**：环境变量 ``DIGEST_SMTP_HOST`` 等配置时发送邮件 HTML
  （复用 ``app.exporter.email.report_to_email_html``）。

设计为**纯 best-effort**：未配置通道 / 无订阅 / 推送失败都不影响出报主流程，
只在结果里留痕。所有网络动作用标准库 ``urllib`` / ``smtplib``，无新依赖。

摘要文本与 Markdown 为纯函数，便于单测；``push_all`` 负责编排与发送。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.exporter.email import email_subject, report_to_email_html
from app.personalization.filter import filter_report
from app.personalization.store import Subscription, SubscriptionStore
from app.schemas.models import DailyReport


@dataclass
class PushResult:
    user: str
    items: int
    channels: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.channels) and not self.errors


def digest_text(report: DailyReport, user: str, max_items: int = 12) -> str:
    """生成纯文本推送摘要（钉钉/企微 text 消息用）。"""
    lines = [
        f"📊 AI 财经日报 · 个性化订阅版（{user}）",
        f"日期 {report.report_date} ｜ 命中 {report.total_items} 条",
        "",
    ]
    shown = 0
    for sec in report.sections:
        if sec.item_count == 0:
            continue
        lines.append(f"【{sec.section_name}】")
        for it in sec.items:
            lines.append(f"  {it.rank}. {it.title}")
            shown += 1
            if shown >= max_items:
                break
        if shown >= max_items:
            lines.append("  …（更多见完整版）")
            break
    return "\n".join(lines)


def digest_markdown(report: DailyReport, user: str, base_url: str = "", max_items: int = 12) -> str:
    """生成 Markdown 摘要（通用 webhook / 邮件正文可选）。"""
    link = f"{base_url.rstrip('/')}/my?user={user}" if base_url else ""
    lines = [
        f"### 📊 AI 财经日报 · 订阅版（{user}）",
        f"> {report.report_date} ｜ 命中 **{report.total_items}** 条",
        "",
    ]
    if report.editor_summary:
        lines.append(report.editor_summary)
        lines.append("")
    shown = 0
    for sec in report.sections:
        if sec.item_count == 0:
            continue
        lines.append(f"**{sec.section_name}**")
        for it in sec.items:
            lines.append(f"- {it.title}")
            shown += 1
            if shown >= max_items:
                break
        lines.append("")
        if shown >= max_items:
            break
    if link:
        lines.append(f"👉 [打开看板看完整版]({link})")
    return "\n".join(lines)


def _send_webhook(url: str, text: str, markdown: str, timeout: float = 10.0) -> tuple[bool, str]:  # noqa: C901
    """按 webhook 类型推送。返回 (ok, channel_name)。"""
    import urllib.request

    if "dingtalk.com" in url:
        payload = {"msgtype": "markdown",
                   "markdown": {"title": "AI 财经日报订阅推送", "text": markdown}}
        channel = "dingtalk"
    elif "wecom.qq.com" in url or "weixin.qq.com" in url:
        payload = {"msgtype": "markdown", "markdown": {"content": markdown}}
        channel = "wecom"
    else:
        payload = {"level": "info", "message": text, "markdown": markdown}
        channel = "webhook"
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (200 <= resp.status < 300), channel
    except Exception as e:  # noqa: BLE001
        return False, f"{channel}:{type(e).__name__}"


def _send_email(report: DailyReport, to_addrs: list[str]) -> tuple[bool, str]:
    """SMTP 发送邮件版 HTML。配置来自环境变量。"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    host = os.environ.get("DIGEST_SMTP_HOST")
    if not host or not to_addrs:
        return False, "smtp:未配置"
    port = int(os.environ.get("DIGEST_SMTP_PORT", "465"))
    user = os.environ.get("DIGEST_SMTP_USER", "")
    password = os.environ.get("DIGEST_SMTP_PASSWORD", "")
    sender = os.environ.get("DIGEST_SMTP_FROM", user)
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = email_subject(report)
        msg["From"] = sender
        msg["To"] = ", ".join(to_addrs)
        msg.attach(MIMEText(report_to_email_html(report), "html", "utf-8"))
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls()
        if user:
            server.login(user, password)
        server.sendmail(sender, to_addrs, msg.as_string())
        server.quit()
        return True, "email"
    except Exception as e:  # noqa: BLE001
        return False, f"smtp:{type(e).__name__}:{e}"


def push_one(
    report: DailyReport,
    sub: Subscription,
    *,
    webhook_url: str = "",
    base_url: str = "",
    sender: Optional[Callable[[str, str, str], tuple[bool, str]]] = None,
    email_sender: Optional[Callable[[DailyReport, list[str]], tuple[bool, str]]] = None,
) -> PushResult:
    """为单个订阅生成个性化版并推送。"""
    result = PushResult(user=sub.name, items=0)
    filtered = filter_report(report, sub.companies, sub.categories, user=sub.name)
    result.items = filtered.total_items
    if filtered.total_items == 0:
        return result  # 订阅条件当日无命中，不打扰

    text = digest_text(filtered, sub.name)
    markdown = digest_markdown(filtered, sub.name, base_url=base_url)

    url = webhook_url or sub.webhook or os.environ.get("ALERT_WEBHOOK_URL", "")
    if url:
        send = sender or _send_webhook
        ok, ch = send(url, text, markdown)
        if ok:
            result.channels.append(ch)
        else:
            result.errors.append(ch if isinstance(ch, str) and ":" in ch else "webhook:失败")

    emails = sub.emails or [e for e in [os.environ.get("DIGEST_EMAIL_TO", "")] if e]
    if emails:
        esend = email_sender or _send_email
        ok, ch = esend(filtered, emails)
        if ok:
            result.channels.append(ch)
        else:
            result.errors.append(ch)

    return result


def push_all(
    report: DailyReport,
    *,
    subs_dir: str | Path = "data/subscriptions",
    webhook_url: str = "",
    base_url: str = "",
    sender=None,
    email_sender=None,
) -> list[PushResult]:
    """遍历所有订阅推送。无订阅/无通道时返回空列表，不抛异常。"""
    store = SubscriptionStore(subs_dir)
    results: list[PushResult] = []
    subs_dir_p = Path(subs_dir)
    if not subs_dir_p.exists():
        return results
    for f in sorted(subs_dir_p.glob("*.yaml")):
        sub = store.get(f.stem)
        try:
            results.append(push_one(report, sub, webhook_url=webhook_url, base_url=base_url,
                                    sender=sender, email_sender=email_sender))
        except Exception as e:  # noqa: BLE001
            r = PushResult(user=sub.name, items=0)
            r.errors.append(f"push:{type(e).__name__}")
            results.append(r)
    return results
