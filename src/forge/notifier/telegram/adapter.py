"""Telegram NotifierAdapter — 기존 notify + TelegramReceiver 래핑."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...config import ForgeConfig, ProjectPaths
from ..base import NotifierAdapter
from .notifier import notify as _notify
from .receiver import TelegramReceiver


class TelegramNotifier(NotifierAdapter):
    def __init__(self, config: ForgeConfig, paths: ProjectPaths):
        self._config = config
        self._paths = paths
        self._receiver = TelegramReceiver(config, paths)

        # 단계 9: 동시 N개 알림 폭주 보호 (Slack과 동형).
        from ..routing import TokenBucketRateLimiter

        self._rate_limiter = TokenBucketRateLimiter(rate_per_sec=2.0, burst=4)

    @property
    def enabled(self) -> bool:
        return self._config.telegram_enabled

    def notify(
        self,
        event_type: str,
        message: str,
        file_path: Optional[Path] = None,
        project_name: str = "",
        buttons: Optional[list[list[str]]] = None,
    ) -> bool:
        try:
            self._rate_limiter.acquire(timeout=10.0)
        except Exception:
            pass
        return _notify(
            self._config,
            event_type,
            message,
            file_path=file_path,
            project_name=project_name or self._paths.project_name,
            buttons=buttons,
        )

    def start(self) -> None:
        self._receiver.start()

    def stop(self) -> None:
        self._receiver.stop()
