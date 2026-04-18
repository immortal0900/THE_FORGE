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
    "revise": "✏️", "수정": "✏️",
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

        # WebClient만 미리 초기화 (notify 전송용, 경량).
        # SocketModeClient는 start() 시 생성 — 일회성 명령(forge notify)이 백그라운드 스레드를 띄우지 않도록.
        from slack_sdk import WebClient

        self._web = WebClient(token=config.slack_bot_token)

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
        if not self.enabled or self._web is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return

        # SocketModeClient를 lazy 초기화 (start에서만 WebSocket 연결 대비 스레드 생성)
        if self._socket is None:
            from slack_sdk.socket_mode import SocketModeClient

            self._socket = SocketModeClient(
                app_token=self._config.slack_app_token,
                web_client=self._web,
            )

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
        """Socket Mode 요청 처리. interactive / slash_commands 중 내 프로젝트 것만 처리."""
        from slack_sdk.socket_mode.response import SocketModeResponse

        # 모든 요청은 일단 ACK (Slack이 재전송하지 않도록)
        try:
            client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id)
            )
        except Exception:
            pass

        if req.type == "interactive":
            self._handle_interactive(req.payload)
        elif req.type == "slash_commands":
            self._handle_slash_command(req.payload)

    def _handle_interactive(self, payload: dict) -> None:
        try:
            # view_submission (modal 제출) — revise 흐름 완료 지점
            if payload.get("type") == "view_submission":
                self._handle_view_submission(payload)
                return

            # block_actions (일반 버튼 클릭)
            actions = payload.get("actions", [])
            if not actions:
                return
            value = actions[0].get("value", "")
            if "::" not in value:
                return
            project, action_raw = value.split("::", 1)
            if project != self._project_name:
                return  # ★ 다른 프로젝트의 이벤트 — 필터 통과시키지 않음

            action = action_raw.strip().lower()
            # revise 버튼은 signal 작성이 아니라 modal 열기
            if action in ("revise", "수정"):
                trigger_id = payload.get("trigger_id")
                if trigger_id:
                    self._open_revise_modal(trigger_id)
                return

            self._apply_signal(action, payload)
        except Exception as e:
            logger.warning("Slack interactive 처리 실패: %s", e)

    def _open_revise_modal(self, trigger_id: str) -> None:
        """revise 버튼 클릭 시 사용자에게 수정 지시 입력받는 modal을 연다."""
        if self._web is None:
            return
        view = {
            "type": "modal",
            "callback_id": "forge_revise_submit",
            "private_metadata": self._project_name,  # 제출 시 이 값으로 프로젝트 매칭
            "title": {"type": "plain_text", "text": f"✏️ {self._display_name}"[:24]},
            "submit": {"type": "plain_text", "text": "제출"},
            "close": {"type": "plain_text", "text": "취소"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{self._project_name}* 의 spec.md를 어떻게 수정할까요?",
                    },
                },
                {
                    "type": "input",
                    "block_id": "revise_input_block",
                    "label": {"type": "plain_text", "text": "수정 지시"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "revise_text",
                        "multiline": True,
                        "placeholder": {
                            "type": "plain_text",
                            "text": "예: 데이터베이스를 PostgreSQL에서 SQLite로 변경하고 비동기 처리 제거",
                        },
                        "max_length": 2000,
                    },
                },
            ],
        }
        try:
            self._web.views_open(trigger_id=trigger_id, view=view)
        except Exception as e:
            logger.warning("Slack views_open 실패: %s", e)

    def _handle_view_submission(self, payload: dict) -> None:
        """revise modal 제출 처리. private_metadata로 프로젝트 필터."""
        view = payload.get("view", {})
        if view.get("callback_id") != "forge_revise_submit":
            return
        project = view.get("private_metadata", "")
        if project != self._project_name:
            return  # ★ 다른 프로젝트 modal — 무시

        values = view.get("state", {}).get("values", {})
        block = values.get("revise_input_block", {})
        text = (block.get("revise_text", {}) or {}).get("value", "") or ""
        text = text.strip()
        if not text:
            return

        self._paths.ensure_artifacts()
        try:
            self._paths.revise_signal.write_text(text, encoding="utf-8")
        except OSError as e:
            logger.warning("revise_signal 작성 실패: %s", e)
            return

        # 채널에 피드백 한 줄
        try:
            self._web.chat_postMessage(
                channel=self._channel,
                username=self._display_name,
                icon_emoji=self._emoji,
                text=f"✏️ `{self._project_name}` 수정 지시 접수됨 — Planner 재실행 중…\n> {text[:300]}",
            )
        except Exception as e:
            logger.warning("Slack revise 피드백 실패: %s", e)

    def _handle_slash_command(self, payload: dict) -> None:
        """`/forge-status [project_name]` 처리.

        Slack Socket Mode는 여러 연결 중 하나에만 이벤트를 전달하므로 여기서는 필터만 하고,
        다른 프로젝트용 커맨드라면 조용히 무시한다. 같은 앱을 쓰는 모든 forge 프로세스가
        같은 이벤트를 받을 수도 있는데 그 경우 각자 필터를 거쳐 자기 것만 응답한다.
        """
        try:
            command = (payload.get("command") or "").strip().lower()
            if command != "/forge-status":
                return
            arg = (payload.get("text") or "").strip().lower()
            # 인자 없으면 모든 프로세스가 각자 응답, 있으면 일치하는 것만 응답
            if arg and arg != self._project_name:
                return
            channel = payload.get("channel_id") or self._channel
            self._post_status(channel)
        except Exception as e:
            logger.warning("Slack slash_command 처리 실패: %s", e)

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

    def _build_status_text(self) -> str:
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

        return (
            f"📊 [{self._project_name}]\n"
            f"Phase: {cp.phase.name}\n"
            f"Sprint: #{self._paths.current_sprint()}\n"
            f"누적 시간: {total_mins:.0f}분\n"
            f"{elapsed_line}"
            f"Detail: {cp.detail}\n"
            f"Updated: {cp.timestamp}"
        )

    def _send_status_reply(self, payload: dict) -> None:
        self._reply(payload, self._build_status_text())

    def _post_status(self, channel: str) -> None:
        """지정 채널에 상태를 새 메시지로 게시 (slash command 응답용)."""
        if self._web is None:
            return
        try:
            self._web.chat_postMessage(
                channel=channel,
                username=self._display_name,
                icon_emoji=self._emoji,
                text=self._build_status_text()[:3000],
            )
        except Exception as e:
            logger.warning("Slack status post 실패: %s", e)

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
