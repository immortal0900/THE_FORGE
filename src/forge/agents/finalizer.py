"""Finalizer 에이전트 호출 함수 (parallel-branches-design.md 단계 7).

Finalizer는 병렬 분기 worktree들을 trunk로 머지하는 검수반장이다.
- FAIL 분기 사전 검사 -> needs_escalation 반환
- 모두 PASS면 LLM 세션 호출, 시스템 프롬프트가 머지 + 충돌 해결 수행
- 머지 commit 후 verify_finalizer_merge_scope로 스코프 위반 자동 감지
- 위반 발견 시 git revert + 호출자(orchestrator)가 사용자 게이트 발사
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import ForgeConfig, ProjectPaths
from ..worktree import (
    BranchWorktree,
    MergeResult,
    ScopeViolation,
    merge_into_trunk,
    verify_finalizer_merge_scope,
)
from . import evaluator as ev
from .runner import RunResult, run_agent_sync


@dataclass
class FinalizeResult:
    """run_finalize 호출 결과.

    status:
    - "merged": 모든 분기 trunk로 머지 성공
    - "merged_partial": partial=True 모드에서 PASS 분기만 부분 머지 성공
    - "needs_escalation": FAIL 분기 사전 검사에서 발견, LLM 호출 안 함
    - "merge_conflict": 의미적 충돌, finalizer가 git merge --abort
    - "scope_violation": 머지는 됐는데 스코프 위반 감지 -> 자동 revert 수행함
    - "error": git 명령 자체 실패 또는 LLM 세션 비정상 종료
    """

    status: str
    fail_branches: list[str] = field(default_factory=list)
    merged_refs: list[str] = field(default_factory=list)
    conflict_files: list[str] = field(default_factory=list)
    violation: Optional[ScopeViolation] = None
    sprint_report_path: Optional[Path] = None
    detail: str = ""
    llm_result: Optional[RunResult] = None


def _is_pass_for_branch(paths: ProjectPaths, branch_id: str) -> bool:
    bp = paths.branch_paths(branch_id)
    return ev.is_pass(bp)


def _build_finalize_prompt(
    sprint_num: int,
    branches: list,
    worktrees: list[BranchWorktree],
    *,
    partial: bool,
    round_num: int = 1,
) -> str:
    branch_lines = []
    for spec in branches:
        bid = getattr(spec, "id", None) or getattr(spec, "branch_id", "?")
        ref = next(
            (wt.git_branch for wt in worktrees if wt.branch_id == bid),
            f"forge/sprint-{sprint_num}-{bid}",
        )
        branch_lines.append(f"  - {bid} (ref: {ref})")
    branch_list = "\n".join(branch_lines) or "  (없음)"

    mode_block = (
        f"## 모드: 부분 머지 (round {round_num})\n"
        "이번 라운드는 PASS 분기만 trunk로 머지하고 FAIL 분기는 다음 라운드 "
        "Planner 재호출용으로 worktree에 보존하는 모드.\n"
        f"보고서 파일명: `artifacts/sprint-{sprint_num}-partial-{round_num}.md`.\n"
        if partial
        else f"## 모드: 정상 머지\n보고서 파일명: `artifacts/sprint-{sprint_num}-done.md`.\n"
    )

    return (
        f"Sprint {sprint_num} 머지 작업을 시작하라.\n\n"
        f"{mode_block}\n"
        "## 머지할 분기 (이 순서대로)\n"
        f"{branch_list}\n\n"
        "## 절차 (시스템 프롬프트의 '머지 절차' 참조)\n"
        "1. 각 분기의 qa-report.md 확인\n"
        "2. 각 ref를 `git merge {ref} --no-ff --no-commit`로 차례 머지\n"
        "3. 충돌 발생 시: 단순 충돌이면 마커 범위 안만 Edit으로 정리 + "
        "decision-NNN.md 기록. 의미적 충돌이면 abort + escalation.md 작성 후 종료.\n"
        "4. 머지 commit 후 다음 분기로\n"
        "5. 모든 분기 끝나면 통합 보고서 작성\n\n"
        "## 절대 금지\n"
        "- qa-report.md 수정 금지\n"
        "- 충돌이 나지 않은 파일 수정 금지\n"
        "- 새 기능 추가 금지\n"
        "- decision-NNN.md 누락 금지\n"
    )


def _collect_pre_merge_head(project_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (FileNotFoundError, OSError):
        pass
    return ""


def _collect_branch_touched_files(
    project_root: Path,
    branch_refs: list[str],
    base_ref: str,
) -> set[str]:
    """각 branch_ref가 base_ref 대비 건드린 파일들의 합집합.

    verify_finalizer_merge_scope에 넘길 expected 집합 — `--no-ff` 머지의
    HEAD~1..HEAD diff에는 분기가 가져온 모든 파일이 포함되므로 expected를
    "분기들이 합법적으로 가져올 수 있는 파일 합집합"으로 확장한다.
    """
    touched: set[str] = set()
    for ref in branch_refs:
        try:
            proc = subprocess.run(
                [
                    "git",
                    "-C",
                    str(project_root),
                    "diff",
                    "--name-only",
                    f"{base_ref}...{ref}",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except (FileNotFoundError, OSError):
            continue
        if proc.returncode != 0:
            continue
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line:
                touched.add(line)
    return touched


def _check_merge_in_progress(project_root: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--verify", "MERGE_HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.returncode == 0
    except (FileNotFoundError, OSError):
        return False


def _abort_merge(project_root: Path) -> None:
    try:
        subprocess.run(
            ["git", "-C", str(project_root), "merge", "--abort"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (FileNotFoundError, OSError):
        pass


def _revert_last_commit(project_root: Path) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "revert", "--no-edit", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.returncode == 0
    except (FileNotFoundError, OSError):
        return False


def run_finalize(
    config: ForgeConfig,
    paths: ProjectPaths,
    branches: list,
    worktrees: list[BranchWorktree],
    *,
    partial: bool = False,
    round_num: int = 1,
    sprint_num: Optional[int] = None,
    notifier=None,
) -> FinalizeResult:
    """Finalizer 호출 (parallel-branches-design.md 단계 7).

    1. FAIL 분기 사전 검사 -> needs_escalation 반환
    2. merge_into_trunk 호출 -> 충돌 시 finalizer LLM 세션
    3. 머지 commit 후 verify_finalizer_merge_scope 호출
    4. 위반 시 git revert + 사용자 게이트
    """
    if sprint_num is None:
        sprint_num = paths.current_sprint()

    fail_branches: list[str] = []
    for spec in branches:
        bid = getattr(spec, "id", None) or getattr(spec, "branch_id", "")
        if not bid:
            continue
        if not _is_pass_for_branch(paths, bid):
            fail_branches.append(bid)

    if fail_branches and not partial:
        return FinalizeResult(
            status="needs_escalation",
            fail_branches=fail_branches,
            detail=f"FAIL 분기 {len(fail_branches)}개 발견: {', '.join(fail_branches)}",
        )

    if partial and fail_branches:
        return FinalizeResult(
            status="needs_escalation",
            fail_branches=fail_branches,
            detail="partial=True 인데 FAIL 분기가 분기 목록에 섞여 있음. 호출자 정정 필요.",
        )

    trunk = paths.trunk_root
    pre_merge_head = _collect_pre_merge_head(trunk)
    pre_merge_head_ref = pre_merge_head or "HEAD"

    branch_refs = [
        next(
            (wt.git_branch for wt in worktrees if wt.branch_id == bid),
            f"forge/sprint-{sprint_num}-{bid}",
        )
        for spec in branches
        for bid in [getattr(spec, "id", None) or getattr(spec, "branch_id", "")]
        if bid
    ]
    merge_pre: MergeResult = merge_into_trunk(trunk, branch_refs, strategy="no-ff")

    if merge_pre.status == "error":
        return FinalizeResult(
            status="error",
            merged_refs=merge_pre.merged_refs,
            detail=f"git merge 자체 실패: {merge_pre.stderr or merge_pre.stdout}",
        )

    expected_conflict_files: set[str] = _collect_branch_touched_files(
        trunk, branch_refs, pre_merge_head_ref
    )
    llm_result: Optional[RunResult] = None

    if merge_pre.status == "conflict":
        expected_conflict_files |= set(merge_pre.conflict_files)

        prompt = _build_finalize_prompt(
            sprint_num, branches, worktrees, partial=partial, round_num=round_num
        )
        llm_result = run_agent_sync(
            "finalizer",
            trunk,
            prompt,
            max_turns=80,
            whisper_queue_path=paths.whisper_queue,
            notifier=notifier,
        )

        if _check_merge_in_progress(trunk):
            _abort_merge(trunk)
            return FinalizeResult(
                status="merge_conflict",
                merged_refs=merge_pre.merged_refs,
                conflict_files=list(expected_conflict_files),
                detail=(
                    "finalizer LLM 세션이 머지 commit / abort 어느 쪽도 완료하지 못한 채 "
                    "종료됨. 강제 abort 수행."
                ),
                llm_result=llm_result,
            )

        post_head = _collect_pre_merge_head(trunk)
        if pre_merge_head and post_head == pre_merge_head:
            return FinalizeResult(
                status="merge_conflict",
                merged_refs=merge_pre.merged_refs,
                conflict_files=list(expected_conflict_files),
                detail="finalizer LLM이 의미적 충돌로 판정, git merge --abort.",
                llm_result=llm_result,
            )

    elif merge_pre.status == "merged":
        diff_proc = subprocess.run(
            ["git", "-C", str(trunk), "diff", "--cached", "--quiet"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if diff_proc.returncode != 0:
            commit_msg = (
                f"forge: finalizer-merge sprint-{sprint_num}"
                f"{' (partial round ' + str(round_num) + ')' if partial else ''}"
            )
            subprocess.run(
                ["git", "-C", str(trunk), "commit", "-m", commit_msg],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

    violation: Optional[ScopeViolation] = None
    if merge_pre.status == "conflict" and expected_conflict_files:
        violation = verify_finalizer_merge_scope(trunk, expected_conflict_files)

    if violation is not None:
        reverted = _revert_last_commit(trunk)
        return FinalizeResult(
            status="scope_violation",
            merged_refs=merge_pre.merged_refs,
            conflict_files=list(expected_conflict_files),
            violation=violation,
            detail=(
                f"스코프 위반 감지 ({len(violation.violating_files)} 파일). "
                f"자동 revert {'성공' if reverted else '실패 - 수동 점검 필요'}."
            ),
            llm_result=llm_result,
        )

    if partial:
        report_path = paths.artifacts / f"sprint-{sprint_num}-partial-{round_num}.md"
    else:
        report_path = paths.sprint_done_path(sprint_num)

    return FinalizeResult(
        status="merged_partial" if partial else "merged",
        merged_refs=merge_pre.merged_refs or branch_refs,
        sprint_report_path=report_path if report_path.exists() else None,
        detail=(
            f"머지 완료 ({len(merge_pre.merged_refs or branch_refs)} 분기). "
            f"산출물: {report_path.name}{' (생성 안 됨)' if not report_path.exists() else ''}."
        ),
        llm_result=llm_result,
    )
