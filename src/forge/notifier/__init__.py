"""notifier 패키지 — 백엔드 어댑터 팩토리."""

from __future__ import annotations

from ..config import ForgeConfig, ProjectPaths
from .base import NotifierAdapter


def get_notifier(config: ForgeConfig, paths: ProjectPaths) -> NotifierAdapter:
    """FORGE_NOTIFIER_BACKEND 값에 따라 어댑터 인스턴스 반환."""
    backend = (config.notifier_backend or "telegram").lower().strip()
    if backend == "slack":
        from .slack.adapter import SlackNotifier
        return SlackNotifier(config, paths)
    # 기본값 telegram
    from .telegram.adapter import TelegramNotifier
    return TelegramNotifier(config, paths)


__all__ = ["NotifierAdapter", "get_notifier"]
