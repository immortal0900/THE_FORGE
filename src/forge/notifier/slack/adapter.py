"""Slack Socket Mode NotifierAdapter.

1 Slack App → N개의 WebSocket 연결(최대 10개). 각 프로젝트가 자기 WebSocket 소유.
메시지 전송 시 username/icon_emoji를 프로젝트별로 커스터마이징해 가상 봇 얼굴을 만든다.
버튼 value에 `project_name::action` 꼬리표를 넣어 수신 시 다른 프로젝트 건은 필터링한다.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from ...config import ForgeConfig, ProjectPaths
from ..base import NotifierAdapter

logger = logging.getLogger(__name__)

# 이벤트 타입 → 아이콘 (Telegram notifier.EMOJI와 일치)
EVENT_EMOJI = {
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

# 버튼 액션 → 표시 아이콘
BUTTON_EMOJI = {
    "resume": "✅", "approve": "✅", "계속": "✅", "진행": "✅",
    "stop": "⏹️", "중단": "⏹️",
    "eval": "🔄", "재평가": "🔄",
    "skip": "⏭️", "스킵": "⏭️", "무시": "⏭️",
    "exit": "🚪", "종료": "🚪",
    "status": "📊", "상태": "📊",
    "continue": "▶️",
    "help": "❓", "도움": "❓",
}

# 버튼 액션 → Slack 스타일 ("primary" | "danger" | default)
BUTTON_STYLE = {
    "resume": "primary", "approve": "primary", "계속": "primary", "진행": "primary",
    "stop": "danger", "exit": "danger", "중단": "danger", "종료": "danger",
}

# 액션 명령어 → signal 파일 필드명 (Telegram receiver._handle_command과 동일)
ACTION_TO_SIGNAL: dict[str, tuple[str, str]] = {
    "resume": ("approval_signal", "resume"),
    "approve": ("approval_signal", "resume"),
    "계속": ("approval_signal", "resume"),
    "진행": ("approval_signal", "resume"),
    "skip": ("skip_signal", "skip"),
    "스킵": ("skip_signal", "skip"),
    "무시": ("skip_signal", "skip"),
    "continue": ("continue_signal", "continue"),
    "exit": ("exit_signal", "exit"),
    "종료": ("exit_signal", "exit"),
    "eval": ("eval_signal", "eval"),
    "재평가": ("eval_signal", "eval"),
    "stop": ("stop_signal", "stop"),
    "중단": ("stop_signal", "stop"),
}


def _parse_action(raw: str) -> str:
    """`/resume` → `resume`, `resume` → `resume`."""
    return raw.lstrip("/").strip().lower()


class SlackNotifier(NotifierAdapter):
    def __init__(self, config: ForgeConfig, paths: ProjectPaths):
        self._config = config
        self._paths = paths
        self._channel = config.slack_channel
        self._display_name = config.resolved_display_name(paths.project_root)
        self._project_name = config.resolved_project_name(paths.project_root)
        self._emoji = config.bot_emoji or ":hammer_and_wrench:"

        self._web = None
        self._socket = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        if not self.enabled:
            return

        # import을 조건부로 하여 slack_sdk 미설치 시에도 import 에러 없이 TelegramNotifier 사용 가능
        from slack_sdk import WebClient
        from slack_sdk.socket_mode import SocketModeClient

        self._web = WebClient(token=config.slack_bot_token)
        self._socket = SocketModeClient(
            app_token=config.slack_app_token,
            web_client=self._web,
        )

    @property
    def enabled(self) -> bool:
        return self._config.slack_enabled

    # ── 전송 ─────────────────────────────────────────────────────────────

    def notify(
        self,
        event_type: str,
        message: str,
        file_path: Optional[Path] = None,
        project_name: str = "",
        buttons: Optional[list[list[str]]] = None,
    ) -> bool:
        if not self.enabled or self._web is None:
            return False

        display_project = project_name or self._project_name
        title_emoji = EVENT_EMOJI.get(event_type, "🔔")
        title = f"{title_emoji} [{display_project}] {event_type}"
        fallback_text = f"{title}\n\n{message}"

        blocks = self._build_blocks(title, message, buttons, display_project)

        try:
            self._web.chat_postMessage(
                channel=self._channel,
                username=self._display_name,
                icon_emoji=self._emoji,
                text=fallback_text[:3000],
                blocks=blocks,
            )
        except Exception as e:
            logger.warning("Slack chat_postMessage 실패: %s", e)
            return False

        if file_path and Path(file_path).exists():
            try:
                self._web.files_upload_v2(
                    channel=self._channel,
                    file=str(file_path),
                    title=Path(file_path).name,
                    initial_comment=f"📎 {Path(file_path).name}",
                )
            except Exception as e:
                logger.warning("Slack files_upload_v2 실패 (%s): %s", file_path, e)

        return True

    def _build_blocks(
        self,
        title: str,
        body: str,
        buttons: Optional[list[list[str]]],
        project_name: str,
    ) -> list[dict]:
        """Block Kit 블록 배열 생성."""
        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title[:150], "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body[:2900] if body else "_(no message)_"},
            },
        ]

        if not buttons:
            return blocks

        # 버튼 행들을 하나의 actions 블록으로 합칠 수도 있지만,
        # Slack의 actions 블록은 최대 25개 요소까지 허용하므로 그냥 평탄화.
        elements: list[dict] = []
        for row in buttons:
            for raw_label in row:
                action = _parse_action(raw_label)
                emoji = BUTTON_EMOJI.get(action, "")
                display = f"{emoji} {action}".strip() if emoji else action or raw_label
                elem: dict = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": display[:75], "emoji": True},
                    "action_id": f"forge_{action or 'action'}",
                    "value": f"{project_name}::{action}"[:2000],
                }
                style = BUTTON_STYLE.get(action)
                if style:
                    elem["style"] = style
                elements.append(elem)
        if elements:
            blocks.append({"type": "actions", "elements": elements[:25]})
        return blocks

    # ── 수신 ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.enabled or self._socket is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._socket.socket_mode_request_listeners.append(self._handle)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._socket.connect()
            self._stop_event.wait()
        except Exception as e:
            logger.warning("Slack Socket Mode 연결 실패: %s", e)
        finally:
            try:
                self._socket.disconnect()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop_event.set()
        if self._socket is not None:
            try:
                self._socket.disconnect()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _handle(self, client, req) -> None:
        """Socket Mode 요청 처리. interactive 이벤트 중 내 프로젝트 것만 signal로 변환."""
        from slack_sdk.socket_mode.response import SocketModeResponse

        # 모든 요청은 일단 ACK (Slack이 재전송하지 않도록)
        try:
            client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id)
            )
        except Exception:
            pass

        if req.type != "interactive":
            return

        try:
            actions = req.payload.get("actions", [])
            if not actions:
                return
            value = actions[0].get("value", "")
            if "::" not in value:
                return
            project, action_raw = value.split("::", 1)
            if project != self._project_name:
                return  # ★ 다른 프로젝트의 이벤트 — 필터 통과시키지 않음

            action = action_raw.strip().lower()
            self._apply_signal(action, req.payload)
        except Exception as e:
            logger.warning("Slack interactive 처리 실패: %s", e)

    def _apply_signal(self, action: str, payload: dict) -> None:
        """action 명령어를 signal 파일로 변환. `/status` 같은 조회성 액션은 직접 응답."""
        if action in ("status", "상태"):
            self._send_status_reply(payload)
            return
        if action in ("help", "도움"):
            self._send_help_reply(payload)
            return

        mapping = ACTION_TO_SIGNAL.get(action)
        if not mapping:
            return
        attr_name, content = mapping
        signal_path: Path = getattr(self._paths, attr_name)
        self._paths.ensure_artifacts()
        try:
            signal_path.write_text(f"{content}\n", encoding="utf-8")
        except OSError as e:
            logger.warning("signal 파일 작성 실패 (%s): %s", signal_path, e)
            return

        # /skip의 경우 approval_signal도 함께 써야 wait_for_approval이 바로 풀린다
        if action in ("skip", "스킵", "무시"):
            try:
                self._paths.approval_signal.write_text("skip\n", encoding="utf-8")
            except OSError:
                pass

        # 유저에게 피드백 한 줄 (동일 채널에 스레드 답장)
        self._reply(payload, f"✅ `{action}` 처리됨 — `{self._project_name}`")

    def _send_status_reply(self, payload: dict) -> None:
        from datetime import datetime

        from ...checkpoint import Checkpoint
        from ...cost_tracker import parse_cost_log

        cp = Checkpoint.load(self._paths.checkpoint_file)
        total_mins = parse_cost_log(self._paths.cost_log)
        elapsed_line = ""
        try:
            started = datetime.fromisoformat(cp.timestamp)
            elapsed = (datetime.now() - started).total_seconds() / 60
            if elapsed >= 0:
                elapsed_line = f"현재 단계 경과: {elapsed:.0f}분\n"
        except (ValueError, TypeError):
            pass

        text = (
            f"📊 [{self._project_name}]\n"
            f"Phase: {cp.phase.name}\n"
            f"Sprint: #{self._paths.current_sprint()}\n"
            f"누적 시간: {total_mins:.0f}분\n"
            f"{elapsed_line}"
            f"Detail: {cp.detail}\n"
            f"Updated: {cp.timestamp}"
        )
        self._reply(payload, text)

    def _send_help_reply(self, payload: dict) -> None:
        self._reply(
            payload,
            "📖 사용 가능한 버튼:\n"
            "✅ resume — 다음 단계 진행\n"
            "🔄 eval — Evaluator만 재실행\n"
            "⏹️ stop — 자동 루프 중단\n"
            "⏭️ skip — 현재 단계 건너뜀\n"
            "📊 status — 현재 상태 조회\n"
            "🚪 exit — 즉시 종료",
        )

    def _reply(self, payload: dict, text: str) -> None:
        """Interactive 이벤트의 해당 스레드에 답장. 채널 ID는 payload에서 추출."""
        if self._web is None:
            return
        channel = payload.get("channel", {}).get("id") or self._channel
        thread_ts = payload.get("message", {}).get("ts")
        try:
            self._web.chat_postMessage(
                channel=channel,
                username=self._display_name,
                icon_emoji=self._emoji,
                text=text[:3000],
                thread_ts=thread_ts,
            )
        except Exception as e:
            logger.warning("Slack reply 실패: %s", e)
