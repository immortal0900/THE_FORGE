"""Planner 에이전트 — claude -p --agent planner subprocess 래퍼."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess

from ..config import ForgeConfig, ProjectPaths


def _run_claude_agent(
    prompt: str,
    agent: str,
    max_turns: int,
    cwd: Path,
    timeout: int = 1800,
) -> CompletedProcess:
    claude = shutil.which("claude") or "claude"
    return subprocess.run(
        [
            claude,
            "-p",
            "--agent",
            agent,
            "--max-turns",
            str(max_turns),
            "--permission-mode",
            "bypassPermissions",
            prompt,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def run_generate(
    request: str,
    config: ForgeConfig,
    paths: ProjectPaths,
) -> CompletedProcess:
    """모드 A — spec.md 생성."""
    prompt = (
        f"사용자 요청: {request}\n\n"
        f"artifacts/spec.md가 없거나 사용자가 재생성을 요청했다. "
        f"생성 모드로 동작하여 artifacts/spec.md를 작성하라."
    )
    return _run_claude_agent(
        prompt, "planner", config.planner_max_turns, paths.project_root
    )


def run_review(config: ForgeConfig, paths: ProjectPaths) -> CompletedProcess:
    """모드 B — 기존 spec.md 검토."""
    prompt = (
        "artifacts/spec.md가 이미 존재한다. **반드시 Mode B(리뷰 모드)로 동작**하라. "
        "생성 모드로 전환하지 말 것. "
        "최우선 작업: artifacts/plan-review.md를 작성하라 "
        "(종합 판정은 READY 또는 NEEDS_REVISION 중 하나). "
        "plan-review.md 작성 완료 후에만, specs/ 에 누락된 도메인 스펙이 있으면 추가로 보강하라."
    )
    return _run_claude_agent(
        prompt, "planner", config.planner_review_max_turns, paths.project_root
    )


def run_contract(
    sprint_num: int,
    config: ForgeConfig,
    paths: ProjectPaths,
) -> CompletedProcess:
    """모드 C — Sprint Contract 생성."""
    prompt = (
        f"Sprint {sprint_num}의 sprint-contract.md를 생성하라. "
        f"templates/sprint-contract-template.md 형식을 따르고, "
        f"spec.md / specs/ / progress-log.md / sprint-*-done.md를 반영하라."
    )
    return _run_claude_agent(
        prompt, "planner", config.contract_max_turns, paths.project_root
    )


def run_revise(
    revise_text: str,
    config: ForgeConfig,
    paths: ProjectPaths,
) -> CompletedProcess:
    """모드 D — 사용자 지시에 따라 기존 spec.md를 수정.

    Planner는 통상 spec.md를 직접 수정할 수 없지만, 이 모드에서만 예외적으로 Edit 허용.
    """
    prompt = (
        f"**반드시 Mode D(수정 모드)로 동작하라.**\n\n"
        f"사용자의 수정 요구: {revise_text}\n\n"
        f"작업:\n"
        f"1. artifacts/spec.md를 Read한다.\n"
        f"2. artifacts/plan-review.md가 있다면 Read한다.\n"
        f"3. 사용자 요구를 반영해 artifacts/spec.md를 **Edit 도구로 직접 수정**한다 "
        f"(수정 모드에서만 허용되는 예외).\n"
        f"4. 관련 artifacts/specs/*.md도 일관성을 위해 보강한다.\n"
        f"5. artifacts/plan-review.md를 갱신하되, 맨 위에 다음 섹션을 추가하라:\n"
        f"   ## 수정 이력 — {{현재 타임스탬프}}\n"
        f"   - 사용자 지시: {revise_text}\n"
        f"   - 변경 요약: (spec.md의 어느 섹션이 어떻게 바뀌었는지)\n"
        f"6. 종합 판정 라인 (READY / NEEDS_REVISION)을 다시 기록하라.\n\n"
        f"원칙: 기존 spec.md의 구조/용어는 최대한 유지. 사용자가 지정한 부분만 국소 교체. "
        f"artifacts/ 바깥 파일은 여전히 건드리지 마라."
    )
    return _run_claude_agent(
        prompt, "planner", config.planner_review_max_turns, paths.project_root
    )


def plan_review_status(paths: ProjectPaths) -> str:
    """plan-review.md에서 'READY' / 'NEEDS_REVISION' 추출."""
    if not paths.plan_review.exists():
        return "MISSING"
    text = paths.plan_review.read_text(encoding="utf-8", errors="replace")
    if "NEEDS_REVISION" in text:
        return "NEEDS_REVISION"
    if "READY" in text:
        return "READY"
    return "UNKNOWN"
