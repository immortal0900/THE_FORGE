"""Journal 에이전트 — claude -p --agent journal subprocess 래퍼.

docs/journal.md 생성/갱신. 수동 `forge journal` 실행 전용.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from typing import Optional

from ..config import ForgeConfig, ProjectPaths


def _run_claude_agent(
    prompt: str,
    max_turns: int,
    cwd: Path,
    timeout: int = 1800,
) -> CompletedProcess:
    claude = shutil.which("claude") or "claude"
    return subprocess.run(
        [
            claude,
            "-p",
            "--agent", "journal",
            "--max-turns", str(max_turns),
            "--permission-mode", "bypassPermissions",
            prompt,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def run_journal(
    config: ForgeConfig,
    paths: ProjectPaths,
    sprints: Optional[list[int]] = None,
    since: Optional[str] = None,
) -> CompletedProcess:
    """docs/journal.md에 새 엔트리 작성.

    scope 우선순위: sprints > since > 자동(파일 마지막 엔트리 이후).
    """
    if sprints:
        nums = sorted(set(sprints))
        is_contiguous = len(nums) > 1 and all(nums[i] + 1 == nums[i + 1] for i in range(len(nums) - 1))
        if len(nums) == 1:
            range_label = f"Sprint {nums[0]}"
        elif is_contiguous:
            range_label = f"Sprint {nums[0]}~{nums[-1]}"
        else:
            range_label = "Sprint " + ", ".join(str(n) for n in nums)
        files_hint = ", ".join(f"sprint-{n}-done.md" for n in nums)
        scope_line = (
            f"범위: {range_label}. "
            f"artifacts/{{{files_hint}}} 중 존재하는 파일들을 주요 자료로 사용하고, "
            f"없는 파일은 현재 artifacts/*에서 해당 스프린트 관련 내용을 추출하라. "
            f"엔트리 헤더의 범위 표기는 정확히 `{range_label}`."
        )
    elif since:
        scope_line = (
            f"범위: {since} 이후 변경사항. "
            f"git log --since={since} --oneline --no-merges 로 커밋 범위 파악 후, "
            f"해당 기간에 걸친 artifacts 변화를 요약하라. "
            f"엔트리 헤더의 범위 표기는 `since {since}`."
        )
    else:
        scope_line = (
            "범위: 자동. docs/journal.md 최상단 엔트리의 날짜 이후의 새 변경사항만 정리. "
            "파일이 없거나 비어있으면 전체 이력을 대상으로 한다. "
            "자동 모드에서는 엔트리 헤더 범위 표기를 생략한다."
        )

    prompt = (
        f"프로젝트명: {paths.project_name}\n"
        f"{scope_line}\n\n"
        f"네 역할은 agents/journal.md에 정의된 대로 docs/journal.md에 사람이 읽을 "
        f"엔지니어링 저널 엔트리를 작성하는 것이다. "
        f"엔트리 헤더는 반드시 `## YYYY-MM-DD — {paths.project_name} — <범위>` 형식을 지켜라 "
        f"(범위: `Sprint N` / `since YYYY-MM-DD` / 자동이면 생략). "
        f"모든 파일/함수 참조는 반드시 마크다운 링크 형식 `[라벨](상대경로#Lline)`으로 작성하라. "
        f"docs/journal.md 이외의 파일은 절대 수정하지 마라."
    )

    return _run_claude_agent(
        prompt,
        max_turns=config.journal_max_turns,
        cwd=paths.project_root,
    )
