"""
飞书 (Feishu / Lark) Notifier for GPT Researcher.

Sends the generated report to a Feishu group chat via Webhook or Bot API.

Usage:
    1. Webhook (simplest):
       - In Feishu group: 群设置 -> 机器人 -> 添加机器人 -> 自定义机器人
       - Set a name and get Webhook URL
       - Set FEISHU_WEBHOOK_URL in .env

    2. Bot API (richer messages, supports cards):
       - Go to open.feishu.cn -> Create enterprise self-built app
       - Enable "机器人" capability -> Get App ID + App Secret
       - Add app to your group -> Get chat_id
       - Set FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_CHAT_ID in .env

Both methods are FREE for personal use.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def send_report_to_feishu(
    report: str,
    task: str = "",
    trigger: str = "gpt-researcher",
) -> bool:
    """
    Send the research report to Feishu.

    Prefers Webhook if set; otherwise falls back to Bot API.

    Args:
        report: The Markdown report content.
        task: The research task query (used as title).
        trigger: Identifier for the message source.

    Returns:
        True if sending succeeded, False otherwise.
    """
    webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if webhook_url:
        return _send_via_webhook(webhook_url, report, task, trigger)

    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    chat_id = os.getenv("FEISHU_CHAT_ID", "").strip()
    if app_id and app_secret:
        return _send_via_bot_api(app_id, app_secret, chat_id, report, task, trigger)

    logger.info(
        "Feishu notifier skipped: set FEISHU_WEBHOOK_URL or "
        "(FEISHU_APP_ID + FEISHU_APP_SECRET) in .env to enable."
    )
    return False


def _send_via_webhook(
    webhook_url: str,
    report: str,
    task: str,
    trigger: str,
) -> bool:
    """Send via Webhook — simplest, no extra credentials needed."""
    title = task or "GPT Researcher 报告"

    # Feishu rich-text post format — title is a heading, report is below.
    content = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": [
                        [{"tag": "text", "text": report}],
                    ],
                }
            }
        },
    }

    return _post(webhook_url, content, "webhook")


def _send_via_bot_api(
    app_id: str,
    app_secret: str,
    chat_id: str,
    report: str,
    task: str,
    trigger: str,
) -> bool:
    """Send via Bot API — supports message cards, needs App ID/Secret."""
    # Step 1: Get tenant_access_token
    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    token_resp = _post(token_url, {"app_id": app_id, "app_secret": app_secret}, "token-endpoint")
    if not token_resp:
        return False

    try:
        data = json.loads(token_resp)
    except json.JSONDecodeError:
        logger.error("Feishu: failed to parse token response")
        return False

    token = data.get("tenant_access_token", "")
    if not token:
        logger.error(f"Feishu: no tenant_access_token — {data.get('msg', 'unknown error')}")
        return False

    # Step 2: Resolve chat_id if not set
    if not chat_id:
        chat_id = _resolve_default_chat_id(token)

    # Step 3: Send message
    title = task or "GPT Researcher 报告"
    send_url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"

    # Use interactive card for nicer layout (title header + report body)
    card_content = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": title, "tag": "plain_text"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"content": report[:5000], "tag": "lark_md"},
            }
        ],
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    body = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card_content, ensure_ascii=False),
    }

    import urllib.request
    req = urllib.request.Request(
        send_url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body_text = resp.read().decode("utf-8")
            result = json.loads(body_text)
            if result.get("code") == 0:
                logger.info(f"Feishu: report sent to chat_id={chat_id}")
                return True
            else:
                logger.error(f"Feishu: send failed — {result.get('msg', body_text[:200])}")
                return False
    except Exception as e:
        logger.error(f"Feishu: request failed — {e}")
        return False


def _resolve_default_chat_id(token: str) -> str:
    """If chat_id not configured, fetch the bot's first chat."""
    import urllib.request
    list_url = "https://open.feishu.cn/open-apis/im/v1/chats?page_size=20"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    req = urllib.request.Request(list_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            items = result.get("data", {}).get("items", [])
            if items:
                return items[0].chat_id
    except Exception:
        pass
    return ""


def _post(url: str, payload: dict, label: str = "") -> Optional[str]:
    """POST JSON, return response body string or None on failure."""
    import urllib.request
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("gbk", errors="replace")
    except Exception as e:
        # Windows 控制台日志可能遇到 GBK 编码错误——只静默忽略
        logger.error(f"Feishu ({label}): request failed — {e}")
        return None
