"""
告警通知模块（架构评审 #19）
支持 webhook/钉钉/企微 等告警通道，cron 失败时主动通知。

用法:
    from app.utils.alert import send_alert

    # 简单用法
    send_alert("日报生成失败：采集步骤异常", level="error")

    # 自定义 webhook
    send_alert("测试告警", webhook_url="https://hooks.example.com/xxx")
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def send_alert(
    message: str,
    level: str = "info",
    webhook_url: str | None = None,
    timeout: float = 10.0,
) -> bool:
    """
    发送告警通知。

    支持通道：
    1. 环境变量 ALERT_WEBHOOK_URL 指定的通用 webhook
    2. 钉钉机器人 (webhook 含 dingtalk.com)
    3. 企业微信机器人 (webhook 含 wecom.qq.com)

    Args:
        message: 告警消息内容
        level: 告警级别 (info/warning/error)
        webhook_url: 可选的自定义 webhook URL，优先级高于环境变量
        timeout: 请求超时时间（秒）

    Returns:
        发送成功返回 True，失败返回 False
    """
    url = webhook_url or os.environ.get("ALERT_WEBHOOK_URL")

    if not url:
        # 无配置时静默失败，避免影响主流程
        return False

    # 检测 webhook 类型并构造对应格式
    if "dingtalk.com" in url:
        payload = _format_dingtalk(message, level)
    elif "wecom.qq.com" in url or "weixin.qq.com" in url:
        payload = _format_wecom(message, level)
    else:
        # 通用 webhook JSON 格式
        payload = {"level": level, "message": message}

    return _send_webhook(url, payload, timeout)


def _format_dingtalk(message: str, level: str) -> dict[str, Any]:
    """钉钉机器人消息格式。"""
    emojis = {"info": "ℹ️", "warning": "⚠️", "error": "❌"}
    emoji = emojis.get(level, "📢")
    return {
        "msgtype": "text",
        "text": {"content": f"{emoji} AI 财经日报告警\n{message}"},
    }


def _format_wecom(message: str, level: str) -> dict[str, Any]:
    """企业微信机器人消息格式。"""
    emojis = {"info": "ℹ️", "warning": "⚠️", "error": "❌"}
    emoji = emojis.get(level, "📢")
    return {
        "msgtype": "text",
        "text": {"content": f"{emoji} AI 财经日报告警\n{message}"},
    }


def _send_webhook(url: str, payload: dict[str, Any], timeout: float) -> bool:
    """发送 webhook 请求。"""
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        # 告警发送失败不抛异常，避免干扰主流程
        return False
