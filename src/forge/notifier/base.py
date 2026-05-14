"""NotifierAdapter ABC — Telegram/Slack 공통 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class NotifierAdapter(ABC):
    """프로젝트별 알림 어댑터 기반 클래스.

    시그니처는 기존 forge.telegram.notifier.notify()와 호환 유지.
    `buttons`는 [["/resume", "/stop"], ["/status"]]처럼 라벨 행 리스트.
    Slack 어댑터는 라벨의 앞 "/"를 제거하고 Block Kit 버튼으로 변환한다.
    """

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """백엔드가 활성화 상태인지 (토큰/채널 등 설정 완료)."""

    @abstractmethod
    def notify(
        self,
        event_type: str,
        message: str,
        file_path: Optional[Path] = None,
        project_name: str = "",
        buttons: Optional[list[list[str]]] = None,
    ) -> bool:
        """알림 전송. 성공 시 True. 비활성 상태면 False."""

    @abstractmethod
    def start(self) -> None:
        """수신 데몬 시작 (백그라운드 스레드). 이미 시작됐으면 no-op."""

    @abstractmethod
    def stop(self) -> None:
        """수신 데몬 중단."""

    def notify_agent_say(
        self,
        text: str,
        *,
        project_name: str = "",
    ) -> bool:
        """LLM이 사용자 의견에 답하거나 진행 상황을 평문으로 흘릴 때 thread에 echo.

        큰 그림 3 (docs/plan-judgment-velocity.md:239) 의 양방향 채널 구현:
        whisper로 받은 사용자 평문에 대해 LLM이 stdout에 답하면, 이 함수가
        그 평문을 Slack thread reply로 흘려서 사용자가 LLM 응답을 볼 수 있게 한다.

        기본 구현은 no-op. 양방향 echo가 의미 있는 백엔드(Slack)만 오버라이드.
        반환: 전송 성공 시 True, 비활성/미구현이면 False.
        """
        return False
