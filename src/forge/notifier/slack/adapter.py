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

        # 큰 그림 3: 프로젝트 thread_ts 복원 (있으면 이후 모든 알림이 같은 스레드에 reply).
        # 첫 notify 시 root 메시지로 자동 설정.
        self._thread_ts: Optional[str] = self._load_thread_ts()

        if not self.enabled:
            return

        # WebClient만 미리 초기화 (notify 전송용, 경량).
        # SocketModeClient는 start() 시 생성 — 일회성 명령(forge notify)이 백그라운드 스레드를 띄우지 않도록.
        from slack_sdk import WebClient

        self._web = WebClient(token=config.slack_bot_token)

    def _load_thread_ts(self) -> Optional[str]:
        """paths.slack_thread 파일에서 thread_ts 복원 (있으면)."""
        try:
            if self._paths.slack_thread.exists():
                value = self._paths.slack_thread.read_text(encoding="utf-8").strip()
                return value or None
        except OSError:
            return None
        return None

    def _save_thread_ts(self, ts: str) -> None:
        """thread_ts를 영구 저장. 크래시 후 다음 forge run 시 같은 스레드 유지."""
        try:
            self._paths.slack_thread.parent.mkdir(parents=True, exist_ok=True)
            self._paths.slack_thread.write_text(ts, encoding="utf-8")
        except OSError as e:
            logger.warning("Slack thread_ts 저장 실패 (%s): %s", self._paths.slack_thread, e)

    def _save_answer(self, qid: str, option_id: str) -> None:
        """ASK_USER 응답을 paths.answer_signal_for(qid)에 기록 (큰 그림 1)."""
        try:
            target = self._paths.answer_signal_for(qid)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(option_id.strip(), encoding="utf-8")
        except OSError as e:
            logger.warning("Slack ASK_USER 응답 저장 실패 (qid=%s): %s", qid, e)

    def reset_thread(self) -> None:
        """현재 스레드를 잊고 다음 notify에서 새 root를 만든다.

        사용 시점: 같은 프로젝트에서 *새 작업 세션*을 시작하고 싶을 때
        (예: 이전 sprint 완전 종료 후 완전히 새 프로젝트 단계 진입).
        """
        self._thread_ts = None
        try:
            self._paths.slack_thread.unlink(missing_ok=True)
        except OSError:
            pass

    # ── 큰 그림 1: ASK_USER 옵션 카드 ────────────────────────────────────

    def send_question_card(
        self,
        ask: dict,
        *,
        project_name: str = "",
    ) -> bool:
        """LLM의 ASK_USER JSON을 Slack Block Kit 옵션 카드로 thread에 reply.

        ask 스키마 (scaffold/agents/planner.md 명세, plan 큰 그림 1):
            {"type":"ask_user", "qid":..., "axiom_link":...,
             "situation":..., "options":[{id,label,icon,mechanism,
             expected_metric,side_effect,similar_case}, ...],
             "recommend":..., "recommend_basis":...}

        버튼 클릭 시 receiver가 paths.answer_signal_for(qid) 파일에
        option_id를 기록 → orchestrator on_question 콜백이 폴링.
        """
        if not self.enabled or self._web is None:
            return False

        qid = ask.get("qid", "")
        axiom_link = ask.get("axiom_link") or ""
        situation = ask.get("situation", "")
        options = ask.get("options", []) or []
        recommend = ask.get("recommend", "")
        basis = ask.get("recommend_basis", "")

        if not qid or not options:
            return False

        header_text = "📍 결정 요청"
        if axiom_link:
            header_text += f"   |   axiom {axiom_link}"

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": header_text[:150], "emoji": True},
            }
        ]
        if situation:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*상황*: {situation}"[:2900]},
                }
            )
        blocks.append({"type": "divider"})

        for opt in options:
            oid = str(opt.get("id", "?"))
            icon = opt.get("icon", "")
            label = opt.get("label", "")
            lines = [f"{icon} *{oid}*  {label}".strip()]
            if opt.get("mechanism"):
                lines.append(f"  • *동작*: {opt['mechanism']}")
            if opt.get("expected_metric"):
                lines.append(f"  • *실측 예상*: {opt['expected_metric']}")
            if opt.get("side_effect"):
                lines.append(f"  • *부수 효과*: {opt['side_effect']}")
            if opt.get("similar_case"):
                lines.append(f"  • *유사 사례*: {opt['similar_case']}")
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]},
                }
            )

        blocks.append({"type": "divider"})

        if recommend or basis:
            rec_lines: list[str] = []
            if recommend:
                rec_lines.append(f"💡 *LLM 추천*: {recommend}")
            if basis:
                rec_lines.append(f"   _왜_: {basis}")
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(rec_lines)[:2900]},
                }
            )

        elements: list[dict] = []
        for opt in options:
            oid = str(opt.get("id", "?"))
            icon = opt.get("icon", "")
            display = f"{icon} {oid}".strip()
            elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": display[:75], "emoji": True},
                    "action_id": f"forge_answer_{oid}",
                    # value: project::answer::qid::option_id (4-part)
                    "value": f"{self._project_name}::answer::{qid}::{oid}"[:2000],
                }
            )
        if elements:
            blocks.append({"type": "actions", "elements": elements[:25]})

        display_project = project_name or self._project_name
        fallback = (
            f"📍 [{display_project}] 결정 요청 qid={qid} ({len(options)} 옵션)"
        )

        post_kwargs: dict = {
            "channel": self._channel,
            "username": self._display_name,
            "icon_emoji": self._emoji,
            "text": fallback[:3000],
            "blocks": blocks,
        }
        if self._thread_ts:
            post_kwargs["thread_ts"] = self._thread_ts

        try:
            resp = self._web.chat_postMessage(**post_kwargs)
        except Exception as e:
            logger.warning("Slack send_question_card 실패: %s", e)
            return False

        if not self._thread_ts:
            root_ts = (resp.get("ts") if hasattr(resp, "get") else None) if resp else None
            if root_ts:
                self._thread_ts = root_ts
                self._save_thread_ts(root_ts)

        return True

    # ── 큰 그림 2: Verdict Card 전송 ──────────────────────────────────────

    def send_verdict_card(
        self,
        qa_report_path: Path,
        *,
        recommendation: str = "",
        recommendation_reason: str = "",
        cost_estimate: str = "",
        buttons: Optional[list[list[str]]] = None,
        project_name: str = "",
    ) -> bool:
        """qa-report.md의 Axiom Verdicts 표를 Slack Verdict Card로 렌더.

        반환: 카드 전송 성공 시 True. qa-report에 axiom verdict가 없거나
        Slack 비활성 상태면 False (호출자는 기존 notify로 폴백).
        """
        if not self.enabled or self._web is None:
            return False

        from ...judgment import build_verdict_card_blocks, parse_qa_axiom_verdicts

        verdicts = parse_qa_axiom_verdicts(qa_report_path)
        if not verdicts:
            return False

        card_blocks = build_verdict_card_blocks(
            verdicts,
            recommendation=recommendation,
            recommendation_reason=recommendation_reason,
            cost_estimate=cost_estimate,
        )
        if not card_blocks:
            return False

        if buttons:
            # 기존 _build_blocks가 만든 actions block만 떼서 카드 하단에 붙임
            tmp = self._build_blocks("", "", buttons, self._project_name)
            for b in tmp:
                if b.get("type") == "actions":
                    card_blocks.append(b)
                    break

        display_project = project_name or self._project_name
        fallback_text = (
            f"📋 [{display_project}] Verdict Card ({len(verdicts)} axioms)"
        )

        post_kwargs: dict = {
            "channel": self._channel,
            "username": self._display_name,
            "icon_emoji": self._emoji,
            "text": fallback_text[:3000],
            "blocks": card_blocks,
        }
        if self._thread_ts:
            post_kwargs["thread_ts"] = self._thread_ts

        try:
            resp = self._web.chat_postMessage(**post_kwargs)
        except Exception as e:
            logger.warning("Slack send_verdict_card 실패: %s", e)
            return False

        if not self._thread_ts:
            root_ts = (resp.get("ts") if hasattr(resp, "get") else None) if resp else None
            if root_ts:
                self._thread_ts = root_ts
                self._save_thread_ts(root_ts)

        return True

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

        # 헤더에 보일 이름 (사용자 눈용) — 폴더명/원문 그대로 OK
        display_project = project_name or self._project_name
        title_emoji = EVENT_EMOJI.get(event_type, "🔔")
        title = f"{title_emoji} [{display_project}] {event_type}"
        fallback_text = f"{title}\n\n{message}"

        # 버튼 value 네임스페이스는 반드시 self._project_name (필터 기준과 일치해야 함)
        blocks = self._build_blocks(title, message, buttons, self._project_name)

        # 큰 그림 3: thread_ts가 있으면 reply, 없으면 이 메시지가 root가 된다.
        post_kwargs: dict = {
            "channel": self._channel,
            "username": self._display_name,
            "icon_emoji": self._emoji,
            "text": fallback_text[:3000],
            "blocks": blocks,
        }
        if self._thread_ts:
            post_kwargs["thread_ts"] = self._thread_ts

        try:
            resp = self._web.chat_postMessage(**post_kwargs)
        except Exception as e:
            logger.warning("Slack chat_postMessage 실패: %s", e)
            return False

        # 응답의 ts가 곧 새 root_ts. thread_ts가 비어있었다면 이 메시지를 root로 설정.
        if not self._thread_ts:
            root_ts = (resp.get("ts") if hasattr(resp, "get") else None) if resp else None
            if root_ts:
                self._thread_ts = root_ts
                self._save_thread_ts(root_ts)

        if file_path and Path(file_path).exists():
            upload_kwargs: dict = {
                "channel": self._channel,
                "file": str(file_path),
                "title": Path(file_path).name,
                "initial_comment": f"📎 {Path(file_path).name}",
            }
            if self._thread_ts:
                upload_kwargs["thread_ts"] = self._thread_ts
            try:
                self._web.files_upload_v2(**upload_kwargs)
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
            print(
                f"[Slack] 🔌 Socket Mode 연결 시작 "
                f"(project='{self._project_name}', channel='{self._channel}')",
                flush=True,
            )
            self._socket.connect()
            print("[Slack] ✅ Socket Mode 연결 성공 — 버튼/슬래시 이벤트 수신 대기", flush=True)
            self._stop_event.wait()
        except Exception as e:
            print(f"[Slack] ❌ Socket Mode 연결 실패: {type(e).__name__}: {e}", flush=True)
            logger.warning("Slack Socket Mode 연결 실패: %s", e)
        finally:
            try:
                self._socket.disconnect()
                print("[Slack] 🔌 Socket Mode 연결 종료", flush=True)
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

        print(f"[Slack] ⬇ RECEIVED type={req.type} (project='{self._project_name}')", flush=True)

        # 모든 요청은 일단 ACK (Slack이 재전송하지 않도록)
        try:
            client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id)
            )
        except Exception as e:
            print(f"[Slack] ⚠ ACK 실패: {type(e).__name__}: {e}", flush=True)

        if req.type == "interactive":
            self._handle_interactive(req.payload)
        elif req.type == "slash_commands":
            self._handle_slash_command(req.payload)
        elif req.type == "events_api":
            self._handle_event(req.payload)

    def _handle_event(self, payload: dict) -> None:
        """Events API: 스레드 안 평문 메시지를 whisper queue에 적재 (큰 그림 3 나머지).

        조건:
        - event.type == "message"
        - event.thread_ts == self._thread_ts (우리 프로젝트의 스레드)
        - bot 자체 메시지 아님 (bot_id 없음)
        - subtype 없음 (말풍선 평문)
        """
        try:
            event = payload.get("event", {})
            if event.get("type") != "message":
                return
            thread_ts = event.get("thread_ts")
            if not thread_ts or thread_ts != self._thread_ts:
                return
            if event.get("bot_id") or event.get("subtype"):
                return
            text = (event.get("text") or "").strip()
            if not text:
                return
            self._append_whisper(text)
            print(
                f"[Slack]   💬 whisper 수신 (project='{self._project_name}', "
                f"len={len(text)}): {text[:60]}...",
                flush=True,
            )
        except Exception as e:
            logger.warning("Slack event 처리 실패: %s", e, exc_info=True)

    def _append_whisper(self, text: str) -> None:
        """사용자 평문 의견을 paths.whisper_queue JSONL에 한 줄 append.

        runner의 whisper poller가 매 LLM turn 사이마다 새 라인을 읽고 stdin push.
        """
        import json
        from datetime import datetime

        record = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "text": text,
        }
        try:
            self._paths.whisper_queue.parent.mkdir(parents=True, exist_ok=True)
            with self._paths.whisper_queue.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("Slack whisper 적재 실패: %s", e)

    def _handle_interactive(self, payload: dict) -> None:
        try:
            # view_submission (modal 제출) — revise 흐름 완료 지점
            if payload.get("type") == "view_submission":
                print("[Slack]   ↳ type=view_submission (modal 제출)", flush=True)
                self._handle_view_submission(payload)
                return

            # block_actions (일반 버튼 클릭)
            actions = payload.get("actions", [])
            if not actions:
                print("[Slack]   ⚠ interactive payload에 actions 없음 — 무시", flush=True)
                return
            value = actions[0].get("value", "")
            action_id = actions[0].get("action_id", "")
            if "::" not in value:
                print(
                    f"[Slack]   ⚠ 버튼 value에 '::' 없음 (value='{value}', action_id='{action_id}') "
                    f"— 구버전/외부 버튼으로 간주하고 무시",
                    flush=True,
                )
                return
            project, action_raw = value.split("::", 1)
            if project != self._project_name:
                print(
                    f"[Slack]   🚫 프로젝트 불일치 — 버튼='{project}' vs 현재='{self._project_name}' "
                    f"(action='{action_raw}') — 과거 실행의 버튼을 눌렀거나 다른 forge 인스턴스용",
                    flush=True,
                )
                return  # ★ 다른 프로젝트의 이벤트 — 필터 통과시키지 않음

            # 큰 그림 1: ASK_USER 응답 — `answer::<qid>::<option_id>` 형태.
            # 기존 5개 신호와 충돌 없는 별도 디스패치.
            if action_raw.startswith("answer::"):
                parts = action_raw.split("::")
                if len(parts) >= 3:
                    qid = parts[1]
                    option_id = "::".join(parts[2:])  # option_id에 :: 들어가는 경우 보존
                    self._save_answer(qid, option_id)
                    print(
                        f"[Slack]   ✓ ASK_USER 응답 저장 qid={qid} option={option_id}",
                        flush=True,
                    )
                return

            action = action_raw.strip().lower()
            print(
                f"[Slack]   ✓ 매칭 성공 action='{action}' "
                f"(project='{project}', action_id='{action_id}')",
                flush=True,
            )
            # revise 버튼은 signal 작성이 아니라 modal 열기
            if action in ("revise", "수정"):
                trigger_id = payload.get("trigger_id")
                if trigger_id:
                    print(f"[Slack]   🪟 revise 모달 열기 시도 (trigger_id={trigger_id[:20]}...)", flush=True)
                    self._open_revise_modal(trigger_id)
                else:
                    print(
                        "[Slack]   ❌ trigger_id 없음 — Slack app에서 Interactivity 미활성화 "
                        "또는 payload 형식 이상. 모달 열 수 없음.",
                        flush=True,
                    )
                return

            self._apply_signal(action, payload)
        except Exception as e:
            print(f"[Slack]   ❌ interactive 처리 예외: {type(e).__name__}: {e}", flush=True)
            logger.warning("Slack interactive 처리 실패: %s", e, exc_info=True)

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
            resp = self._web.views_open(trigger_id=trigger_id, view=view)
            print(f"[Slack]   ✅ views_open 성공 (ok={resp.get('ok')})", flush=True)
        except Exception as e:
            # SlackApiError는 .response.data 에 구체적 에러코드 담김
            err_detail = ""
            resp_data = getattr(getattr(e, "response", None), "data", None)
            if resp_data:
                err_detail = f" | response={resp_data}"
            print(
                f"[Slack]   ❌ views_open 실패: {type(e).__name__}: {e}{err_detail}\n"
                f"[Slack]      → 점검: (1) api.slack.com/apps → Interactivity & Shortcuts 토글 ON, "
                f"(2) trigger_id 3초 만료 여부 (버튼 재클릭), "
                f"(3) Bot Token(xoxb-)로 초기화되었는지",
                flush=True,
            )
            logger.warning("Slack views_open 실패: %s", e, exc_info=True)

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
            print("[Slack]   ⚠ _reply 불가: web client 없음", flush=True)
            return
        channel = payload.get("channel", {}).get("id") or self._channel
        thread_ts = payload.get("message", {}).get("ts")
        if not thread_ts:
            print(
                "[Slack]   ⚠ _reply: thread_ts 없음 (payload에 message.ts 부재) "
                "— 메인 채널에 직접 포스트됨",
                flush=True,
            )
        try:
            resp = self._web.chat_postMessage(
                channel=channel,
                username=self._display_name,
                icon_emoji=self._emoji,
                text=text[:3000],
                thread_ts=thread_ts,
            )
            print(
                f"[Slack]   ✉ reply 성공 (ok={resp.get('ok')}, "
                f"thread_ts={thread_ts[:20] if thread_ts else 'None'}...)",
                flush=True,
            )
        except Exception as e:
            resp_data = getattr(getattr(e, "response", None), "data", None)
            err_detail = f" | response={resp_data}" if resp_data else ""
            print(
                f"[Slack]   ❌ reply 실패: {type(e).__name__}: {e}{err_detail}",
                flush=True,
            )
            logger.warning("Slack reply 실패: %s", e, exc_info=True)
