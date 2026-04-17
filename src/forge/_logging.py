"""Subprocess 결과 진단 로깅.

플러그인/서브에이전트/Task 도구 실패를 조용히 삼키지 않고 즉시 가시화한다.
"""

from __future__ import annotations

import re
from subprocess import CompletedProcess
from typing import Optional

# 서브에이전트 / 플러그인 관련 힌트 키워드.
# stderr에 이 패턴 있으면 성공 리턴이어도 경고 출력.
_SUBAGENT_HINTS = re.compile(
    r"(subagent|Task tool|plugin|marketplace|MCP server)",
    re.IGNORECASE,
)

# 스텁 서브에이전트 호출 실패 패턴 (이름 매칭 실패 등)
_SUBAGENT_FAIL = re.compile(
    r"(unknown subagent|agent not found|plugin not enabled|MCP .* failed)",
    re.IGNORECASE,
)


def report_subprocess(
    result: CompletedProcess,
    agent_name: str,
    console,
    stderr_tail: int = 1500,
    stdout_tail: int = 800,
) -> None:
    """subprocess 결과 검사 후 필요 시 tail 출력.

    동작:
    - returncode != 0 → 빨간색 실패 메시지 + stderr/stdout tail
    - stderr에 명확한 실패 패턴 있으면 → 노란색 경고 + stderr tail
    - stderr에 힌트 키워드만 있으면 → dim 회색 참고 안내 (성공이긴 해도 주목)
    - 나머지는 조용히 패스
    """
    returncode = getattr(result, "returncode", 0) or 0
    stderr = (getattr(result, "stderr", "") or "")
    stdout = (getattr(result, "stdout", "") or "")

    if returncode != 0:
        console.print(f"[red]■ {agent_name} subprocess 실패 (exit={returncode})[/red]")
        _print_tails(console, stderr, stdout, stderr_tail, stdout_tail)
        return

    if stderr and _SUBAGENT_FAIL.search(stderr):
        console.print(f"[yellow]⚠ {agent_name}: subagent/plugin 호출 실패 흔적[/yellow]")
        _print_tails(console, stderr, None, stderr_tail, 0)
        return

    if stderr and _SUBAGENT_HINTS.search(stderr):
        console.print(f"[dim]· {agent_name}: stderr에 subagent/plugin 관련 메시지[/dim]")
        _print_tails(console, stderr, None, min(stderr_tail, 600), 0)


def _print_tails(
    console,
    stderr: str,
    stdout: Optional[str],
    stderr_tail: int,
    stdout_tail: int,
) -> None:
    if stderr and stderr_tail > 0:
        console.print("[dim]--- stderr tail ---[/dim]")
        console.print(stderr[-stderr_tail:])
    if stdout and stdout_tail > 0:
        console.print("[dim]--- stdout tail ---[/dim]")
        console.print(stdout[-stdout_tail:])
