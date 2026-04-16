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
        "artifacts/spec.md가 이미 존재한다. 리뷰 모드로 동작하여 "
        "artifacts/plan-review.md를 작성하라. "
        "종합 판정은 READY 또는 NEEDS_REVISION 중 하나여야 한다."
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
