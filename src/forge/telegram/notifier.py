"""Telegram 알림 — httpx 기반. 설정이 없으면 no-op."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import httpx

from ..config import ForgeConfig

EMOJI = {
    "planner_done": "📋",
    "spec_detail": "📄",
    "plan_revision": "⚠️",
    "sprint_contract": "📝",
    "generator_start": "⚙️",
    "generator_end": "🔧",
    "qa_pass": "✅",
    "qa_fail": "❌",
    "warning": "🔴",
    "error": "🚨",
    "info": "🔔",
    "session_stop": "⏹️",
    "sprint_pass_next": "✅",
    "project_complete": "🎉",
    "auto_stop": "⚠️",
    "budget_exceeded": "💰",
    "journal": "📔",
}

_API_BASE = "https://api.telegram.org"


def _base_url(config: ForgeConfig) -> str:
    return f"{_API_BASE}/bot{config.telegram_bot_token}"


def _reply_markup(buttons: Optional[list[list[str]]]) -> Optional[str]:
    """[[/resume, /stop], [/status]] → reply keyboard JSON.

    탭하면 해당 텍스트가 그대로 채팅으로 전송되므로 receiver 수정 불필요.
    """
    if not buttons:
        return None
    keyboard = [[{"text": label} for label in row] for row in buttons]
    return json.dumps({
        "keyboard": keyboard,
        "resize_keyboard": True,
        "one_time_keyboard": True,
    })


def notify(
    config: ForgeConfig,
    event_type: str,
    message: str,
    file_path: Optional[Path] = None,
    project_name: str = "",
    buttons: Optional[list[list[str]]] = None,
) -> bool:
    """이벤트 알림 전송. file_path 있으면 sendDocument, 없으면 sendMessage."""
    if not config.telegram_enabled:
        return False
    emoji = EMOJI.get(event_type, "🔔")
    title = f"{emoji} [{project_name}] {event_type}" if project_name else f"{emoji} {event_type}"
    body = f"{title}\n\n{message}"
    if file_path and Path(file_path).exists():
        return send_file(config, Path(file_path), caption=body, buttons=buttons)
    return send_message(config, body, buttons=buttons)


def send_message(
    config: ForgeConfig,
    text: str,
    buttons: Optional[list[list[str]]] = None,
) -> bool:
    if not config.telegram_enabled:
        return False
    data = {"chat_id": config.telegram_chat_id, "text": text[:4096]}
    markup = _reply_markup(buttons)
    if markup:
        data["reply_markup"] = markup
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{_base_url(config)}/sendMessage", data=data)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def send_file(
    config: ForgeConfig,
    file_path: Path,
    caption: str = "",
    buttons: Optional[list[list[str]]] = None,
) -> bool:
    if not config.telegram_enabled:
        return False
    data = {
        "chat_id": config.telegram_chat_id,
        "caption": caption[:1024],
    }
    markup = _reply_markup(buttons)
    if markup:
        data["reply_markup"] = markup
    try:
        with file_path.open("rb") as f:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{_base_url(config)}/sendDocument",
                    data=data,
                    files={"document": (file_path.name, f)},
                )
        return resp.status_code == 200
    except (httpx.HTTPError, OSError):
        return False
