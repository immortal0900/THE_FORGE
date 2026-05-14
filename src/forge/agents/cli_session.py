"""Claude CLI를 영속 Popen 세션으로 띄우는 클라이언트.

토대 1 (docs/plan-judgment-velocity.md): 양방향 stream-json으로 LLM 작업 도중
사용자 의사소통(ASK_USER, whisper)을 가능하게 한다.

세션 수명: 1 Popen = 1 session. 1 sprint 당 보통 3-5 세션 (planner-spec,
planner-contract, generator, evaluator). 도구 호출마다 새 세션 X.

인증: claude CLI가 OS 키체인의 OAuth 토큰을 자동 사용 (Max Plan 그대로).
단 자식 env에서 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN 명시 제거
(issue #37686 청구 사고 방지).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from asyncio.subprocess import PIPE
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional


class ClaudeCliSessionError(RuntimeError):
    pass


@dataclass
class SessionEvent:
    """stream-json 이벤트 1건. claude CLI가 stdout에 한 줄씩 흘려보내는 JSON."""

    type: str
    data: dict


_REMOVED_ENV_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def build_child_env(base: Optional[dict] = None) -> dict:
    """API 키 환경변수를 제거한 자식 env.

    claude CLI는 자식 env에 API 키가 있으면 OS 키체인의 OAuth보다 그것을 우선
    사용한다. Max Plan을 쓰는데 의도치 않게 사용량 과금이 발생하는 사고를
    원천 차단하기 위해 명시적으로 제거한다 (issue #37686, $1,800 청구 사례).
    """
    source = os.environ if base is None else base
    return {k: v for k, v in source.items() if k not in _REMOVED_ENV_KEYS}


class ClaudeCliSession:
    """`claude` CLI를 영속 subprocess로 띄워 stream-json 양방향 멀티턴.

    flag 묶음 (공식, https://code.claude.com/docs/en/sdk-headless):
        claude -p --agent <name>
               --input-format stream-json --output-format stream-json --verbose
               --permission-mode dontAsk
               (--session-id <uuid> | --resume <uuid>)
    """

    def __init__(
        self,
        agent: str,
        cwd: Path,
        *,
        session_id: Optional[str] = None,
        resume: bool = False,
        max_turns: Optional[int] = None,
        claude_bin: Optional[str] = None,
    ) -> None:
        self.agent = agent
        self.cwd = Path(cwd)
        self.session_id = session_id or str(uuid.uuid4())
        self.resume = resume
        self.max_turns = max_turns
        self._claude_bin = claude_bin
        self.proc: Optional[asyncio.subprocess.Process] = None

    async def start(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            raise ClaudeCliSessionError("이미 세션이 시작되어 있다.")

        claude = self._claude_bin or shutil.which("claude") or "claude"
        args: list[str] = [
            claude,
            "-p",
            "--agent",
            self.agent,
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk",
        ]
        if self.max_turns is not None:
            args.extend(["--max-turns", str(self.max_turns)])
        if self.resume:
            args.extend(["--resume", self.session_id])
        else:
            args.extend(["--session-id", self.session_id])

        self.proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(self.cwd),
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            env=build_child_env(),
        )

    async def send_user_message(self, text: str) -> None:
        """user message를 stream-json 한 줄로 stdin에 push."""
        self._require_running()
        payload = {
            "type": "user",
            "message": {"role": "user", "content": text},
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(line.encode("utf-8"))
        await self.proc.stdin.drain()

    async def iter_events(self) -> AsyncIterator[SessionEvent]:
        """stdout JSONL을 한 줄씩 yield. 비-JSON 라인은 무시."""
        self._require_running()
        assert self.proc is not None and self.proc.stdout is not None
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                return
            try:
                data = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            yield SessionEvent(type=data.get("type", "unknown"), data=data)

    async def close(self, timeout: float = 10.0) -> int:
        """stdin 닫고 정상 종료 대기. 타임아웃이면 terminate → 그래도 안 죽으면 kill."""
        if self.proc is None:
            return 0
        if self.proc.returncode is not None:
            return self.proc.returncode

        if self.proc.stdin is not None and not self.proc.stdin.is_closing():
            self.proc.stdin.close()
        try:
            return await asyncio.wait_for(self.proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.proc.terminate()
            try:
                return await asyncio.wait_for(self.proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.proc.kill()
                return await self.proc.wait()

    async def collect_stderr(self, timeout: float = 30.0) -> str:
        """stderr 전체 수집 (디버깅용). 타임아웃 시 부분만 반환."""
        if self.proc is None or self.proc.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(self.proc.stderr.read(), timeout=timeout)
            return data.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            return "<stderr read timeout>"

    def _require_running(self) -> None:
        if self.proc is None:
            raise ClaudeCliSessionError("세션이 아직 시작되지 않았다 (start() 필요).")
        if self.proc.returncode is not None:
            raise ClaudeCliSessionError(
                f"세션이 이미 종료됨 (returncode={self.proc.returncode})."
            )
