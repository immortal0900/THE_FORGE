"""Telegram 알림 — httpx 기반. 설정이 없으면 no-op."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx

from ..config import ForgeConfig

EMOJI = {
    "planner_done": "📋",
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
}

_API_BASE = "https://api.telegram.org"


def _base_url(config: ForgeConfig) -> str:
    return f"{_API_BASE}/bot{config.telegram_bot_token}"


def notify(
    config: ForgeConfig,
    event_type: str,
    message: str,
    file_path: Optional[Path] = None,
    project_name: str = "",
) -> bool:
    """이벤트 알림 전송. file_path 있으면 sendDocument, 없으면 sendMessage."""
    if not config.telegram_enabled:
        return False
    emoji = EMOJI.get(event_type, "🔔")
    title = f"{emoji} [{project_name}] {event_type}" if project_name else f"{emoji} {event_type}"
    body = f"{title}\n\n{message}"
    if file_path and Path(file_path).exists():
        return send_file(config, Path(file_path), caption=body)
    return send_message(config, body)


def send_message(config: ForgeConfig, text: str) -> bool:
    if not config.telegram_enabled:
        return False
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{_base_url(config)}/sendMessage",
                data={"chat_id": config.telegram_chat_id, "text": text[:4096]},
            )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def send_file(config: ForgeConfig, file_path: Path, caption: str = "") -> bool:
    if not config.telegram_enabled:
        return False
    try:
        with file_path.open("rb") as f:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{_base_url(config)}/sendDocument",
                    data={
                        "chat_id": config.telegram_chat_id,
                        "caption": caption[:1024],
                    },
                    files={"document": (file_path.name, f)},
                )
        return resp.status_code == 200
    except (httpx.HTTPError, OSError):
        return False
