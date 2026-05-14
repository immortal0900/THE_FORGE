"""ForgeAgentRunner: ClaudeCliSession 위에 LLM 한 라운드 실행 wrapper.

토대 1 (docs/plan-judgment-velocity.md): subprocess.run batch 호출을 영속 Popen
양방향 streaming 호출로 대체하면서, 호출처(planner.py / evaluator.py /
orchestrator.py)가 사용하는 CompletedProcess 인터페이스(returncode / stdout / stderr)는
그대로 유지한다.

ASK_USER / whisper 라우팅은 plan의 큰 그림 1 / 큰 그림 3에서 본격 구현. 이번
토대 1에서는 on_question 콜백 hook만 노출하고, 콜백 미설정 시 batch처럼 LLM
종료까지 흘려보낸다.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .cli_session import ClaudeCliSession, SessionEvent


@dataclass
class RunResult:
    """subprocess.CompletedProcess 호환 인터페이스 (returncode/stdout/stderr).

    호출처(`_logging.report_subprocess`, orchestrator)는 이 세 속성만 본다.
    추가 메타(session_id, events)는 ASK_USER 라우팅 / 디버깅 / 학습 로그용.
    """

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    session_id: str = ""
    events: list[SessionEvent] = field(default_factory=list)


AskUserCallback = Callable[[dict], Awaitable[str]]


class ForgeAgentRunner:
    """1 Popen 세션에서 1 LLM 라운드 실행."""

    def __init__(
        self,
        session: ClaudeCliSession,
        *,
        on_question: Optional[AskUserCallback] = None,
        whisper_queue_path: Optional[Path] = None,
    ) -> None:
        self.session = session
        self.on_question = on_question
        self.whisper_queue_path = whisper_queue_path
        self._whisper_cursor = 0   # 이미 push 한 라인 수

    async def run(self, initial_prompt: str) -> RunResult:
        await self.session.start()

        # 큰 그림 3 나머지: 시작 직전 whisper queue 위치 초기화 (이전 sprint 잔여 무시).
        if self.whisper_queue_path and self.whisper_queue_path.exists():
            try:
                self._whisper_cursor = sum(
                    1 for _ in self.whisper_queue_path.open(
                        "r", encoding="utf-8", errors="replace"
                    )
                )
            except OSError:
                self._whisper_cursor = 0

        await self.session.send_user_message(initial_prompt)

        events: list[SessionEvent] = []
        stdout_parts: list[str] = []
        error_payload = ""

        async for ev in self.session.iter_events():
            # 매 이벤트 사이마다 사용자 whisper 큐 확인 → LLM stdin에 push
            await self._drain_whispers()

            events.append(ev)

            if ev.type == "assistant":
                text = self._extract_assistant_text(ev.data)
                if text:
                    stdout_parts.append(text)
                if self.on_question:
                    ask = self._parse_ask_user(text)
                    if ask:
                        answer = await self.on_question(ask)
                        await self.session.send_user_message(answer)

            elif ev.type == "result":
                final = ev.data.get("result") or ev.data.get("text")
                if isinstance(final, str) and final not in stdout_parts:
                    stdout_parts.append(final)
                break

            elif ev.type == "error":
                error_payload = json.dumps(ev.data, ensure_ascii=False)
                break

        stderr_text = await self.session.collect_stderr(timeout=5.0)
        returncode = await self.session.close()
        if error_payload and not stderr_text:
            stderr_text = error_payload

        return RunResult(
            returncode=returncode,
            stdout="\n".join(stdout_parts),
            stderr=stderr_text,
            session_id=self.session.session_id,
            events=events,
        )

    async def _drain_whispers(self) -> None:
        """whisper_queue JSONL의 새 라인을 LLM stdin에 user message로 push.

        Slack receiver(_append_whisper)가 사용자 평문 메시지를 한 줄씩 append.
        runner는 _whisper_cursor 이후의 새 라인만 읽어 LLM에 전달 (중복 push 방지).
        """
        if self.whisper_queue_path is None or not self.whisper_queue_path.exists():
            return
        try:
            lines = self.whisper_queue_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            return
        if len(lines) <= self._whisper_cursor:
            return
        new_lines = lines[self._whisper_cursor:]
        self._whisper_cursor = len(lines)
        for raw in new_lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
                text = (record.get("text") or "").strip()
            except json.JSONDecodeError:
                text = raw
            if not text:
                continue
            try:
                await self.session.send_user_message(f"[사용자 의견] {text}")
            except Exception:
                # 세션이 이미 종료됐을 수 있음 — 조용히 무시
                return

    @staticmethod
    def _extract_assistant_text(event_data: dict) -> str:
        """stream-json assistant 이벤트에서 텍스트 추출.

        claude의 일반 형식: `{"message": {"role": "assistant",
        "content": [{"type": "text", "text": "..."}, ...]}}`.
        단순 string content도 허용.
        """
        msg = event_data.get("message", {})
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "".join(parts)
        return ""

    @staticmethod
    def _parse_ask_user(text: str) -> Optional[dict]:
        """텍스트에서 `{"type":"ask_user", ...}` JSON 한 줄 감지.

        본격 ASK_USER 라우팅은 plan의 큰 그림 1 단계에서. 여기는 골격만.
        """
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("type") == "ask_user":
                return obj
        return None


def run_agent_sync(
    agent: str,
    cwd: Path,
    initial_prompt: str,
    *,
    max_turns: Optional[int] = None,
    session_id: Optional[str] = None,
    resume: bool = False,
    on_question: Optional[AskUserCallback] = None,
    whisper_queue_path: Optional[Path] = None,
) -> RunResult:
    """동기 호출자(planner.py / evaluator.py / orchestrator.py)용 진입점.

    내부에서 asyncio.run으로 영속 Popen + streaming 처리.
    whisper_queue_path가 주어지면 사용자 평문 의견을 LLM에 자동 push (큰 그림 3).
    """
    session = ClaudeCliSession(
        agent=agent,
        cwd=cwd,
        session_id=session_id,
        resume=resume,
        max_turns=max_turns,
    )
    runner = ForgeAgentRunner(
        session,
        on_question=on_question,
        whisper_queue_path=whisper_queue_path,
    )
    return asyncio.run(runner.run(initial_prompt))
