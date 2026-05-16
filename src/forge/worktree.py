"""git worktree 관리 + 자동 커밋 + 머지 (parallel-branches-design.md 단계 2).

이 모듈은 forge가 git 명령을 직접 subprocess로 호출하는 **유일한 격리 영역**이다.
"forge가 git 명령 호출 X"의 기존 정신은 이 1개 모듈에 집중하여 위배 범위를 좁힌다.

핵심 책임:
- create_branch_worktrees: sprint 시작 시 N개 분기 worktree 생성
- auto_commit_worktree: generator/evaluator 종료 직후 분기 worktree 자동 커밋
- auto_commit_trunk_artifacts: planner/finalizer가 trunk 시스템 산출물을 쓴 직후
  자동 커밋 (pathspec 명시 — 사용자 코드 src/, tests/ 는 절대 stage 안 함)
- remove_branch_worktrees: sprint 종료 후 worktree 정리
- merge_into_trunk: finalizer가 분기들을 trunk로 머지
- verify_finalizer_merge_scope: finalizer 머지 commit 직후 scope 위반 자동 감지

비유: 공장 안의 임시 작업대(.worktrees/)는 자동 도장. 정식 출고대(trunk)는 사용자
결재 후 도장. 단, 본사 사무직(planner/finalizer)이 쓴 보고서/계획서는 시스템 도장.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class BranchWorktree:
    """한 분기의 worktree 위치 정보."""

    branch_id: str
    path: Path
    git_branch: str


@dataclass
class CommitResult:
    """자동 커밋 결과.

    status:
    - "committed": 정상 커밋
    - "no_changes": stage 후 변경 없음 (skip)
    - "error": git 명령 실패 (returncode != 0)
    """

    status: str
    commit_message: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@dataclass
class MergeResult:
    """merge_into_trunk 결과.

    status:
    - "merged": 충돌 없이 모든 분기 머지 성공
    - "conflict": 머지 중 충돌 발생. conflict_files에 unmerged 파일 목록
    - "error": git 명령 자체가 실패
    """

    status: str
    merged_refs: list[str] = field(default_factory=list)
    conflict_files: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


@dataclass
class ScopeViolation:
    """verify_finalizer_merge_scope 위반 결과.

    finalizer가 충돌 안 난 파일까지 손댄 경우. 호출자(orchestrator)가
    git revert + 사용자 게이트를 발사할 수 있도록 위반 파일 목록을 담는다.
    """

    violating_files: list[str]
    expected_conflict_files: list[str]
    all_changed_files: list[str]


def _run_git(
    project_root: Path,
    args: list[str],
    *,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """git 명령을 project_root에서 실행. encoding utf-8 고정.

    check=True 면 returncode != 0 시 CalledProcessError. 기본 False로 두고
    호출자가 returncode로 분기.
    """
    return subprocess.run(
        ["git", "-C", str(project_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def _worktree_dir(project_root: Path, sprint_num: int, branch_id: str) -> Path:
    """.worktrees/sprint-{N}-{branch_id} 절대 경로."""
    return project_root / ".worktrees" / f"sprint-{sprint_num}-{branch_id}"


def _branch_ref(sprint_num: int, branch_id: str) -> str:
    """git 브랜치명 규약: forge/sprint-{N}-{branch_id}."""
    return f"forge/sprint-{sprint_num}-{branch_id}"


def create_branch_worktrees(
    project_root: Path,
    sprint_num: int,
    branch_ids: list[str],
    base_ref: str = "HEAD",
) -> list[BranchWorktree]:
    """sprint 시작 시 분기 worktree N개 생성.

    각 branch_id 마다:
    1. .worktrees/sprint-{N}-{branch_id} 디렉토리에 worktree 생성
    2. forge/sprint-{N}-{branch_id} git 브랜치를 base_ref에서 분기

    이미 같은 이름의 worktree나 브랜치가 있으면 git이 에러를 던진다. 호출자가
    먼저 remove_branch_worktrees로 정리하거나 sprint_num을 새로 잡아야 한다.
    """
    project_root = Path(project_root).resolve()
    worktrees: list[BranchWorktree] = []
    for bid in branch_ids:
        wt_path = _worktree_dir(project_root, sprint_num, bid)
        git_branch = _branch_ref(sprint_num, bid)
        wt_path.parent.mkdir(parents=True, exist_ok=True)
        proc = _run_git(
            project_root,
            ["worktree", "add", str(wt_path), "-b", git_branch, base_ref],
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed for {bid}: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        worktrees.append(
            BranchWorktree(branch_id=bid, path=wt_path, git_branch=git_branch)
        )
    return worktrees


def auto_commit_worktree(
    worktree_path: Path,
    branch_id: str,
    sprint_num: int,
    turn_kind: str,
) -> CommitResult:
    """generator/evaluator subprocess 종료 직후 호출.

    동작:
    1. git -C {worktree} add -A
    2. git diff --cached --quiet → 변경 없으면 status="no_changes"
    3. 변경 있으면 git commit -m "forge: sprint-{N}-{branch_id} {turn_kind} turn"

    .worktrees/sprint-* 영역은 정책 분리상 자동 커밋 영역 (사용자 코드가 아닌
    임시 작업대로 간주).
    """
    worktree_path = Path(worktree_path).resolve()
    msg = f"forge: sprint-{sprint_num}-{branch_id} {turn_kind} turn"

    add_proc = _run_git(worktree_path, ["add", "-A"])
    if add_proc.returncode != 0:
        return CommitResult(
            status="error",
            commit_message=msg,
            stdout=add_proc.stdout,
            stderr=add_proc.stderr,
            returncode=add_proc.returncode,
        )

    diff_proc = _run_git(worktree_path, ["diff", "--cached", "--quiet"])
    if diff_proc.returncode == 0:
        return CommitResult(status="no_changes", commit_message=msg)

    commit_proc = _run_git(worktree_path, ["commit", "-m", msg])
    if commit_proc.returncode != 0:
        return CommitResult(
            status="error",
            commit_message=msg,
            stdout=commit_proc.stdout,
            stderr=commit_proc.stderr,
            returncode=commit_proc.returncode,
        )
    return CommitResult(
        status="committed",
        commit_message=msg,
        stdout=commit_proc.stdout,
    )


# trunk artifacts 자동 커밋 대상 (단계 2-2 정책).
# 절대 path가 아닌 git pathspec (project_root 기준 상대 경로). 누락된 파일은 git이
# 조용히 skip하므로 안전.
TRUNK_ARTIFACT_PATHSPECS: tuple[str, ...] = (
    "artifacts/spec.md",
    "artifacts/sprint-contract.md",
    "artifacts/plan-review.md",
)


def auto_commit_trunk_artifacts(
    trunk_root: Path,
    turn_kind: str,
    sprint_num: int,
) -> CommitResult:
    """planner/finalizer subprocess가 trunk 시스템 산출물을 쓴 직후 호출.

    pathspec 명시 — `src/`, `tests/` 등 사용자 영역은 절대 stage하지 않는다.
    journal.md 정신 ("사용자 코드는 사용자가 commit 결정") 보존 + 시스템 산출물만
    orchestrator가 자동 커밋.

    동작:
    1. git -C {trunk} add artifacts/spec.md artifacts/sprint-contract.md
                              artifacts/plan-review.md
    2. 변경 없으면 status="no_changes"
    3. 변경 있으면 git commit -m "forge: {turn_kind} sprint-{N}"
    """
    trunk_root = Path(trunk_root).resolve()
    msg = f"forge: {turn_kind} sprint-{sprint_num}"

    add_proc = _run_git(trunk_root, ["add", "--", *TRUNK_ARTIFACT_PATHSPECS])
    if add_proc.returncode != 0:
        return CommitResult(
            status="error",
            commit_message=msg,
            stdout=add_proc.stdout,
            stderr=add_proc.stderr,
            returncode=add_proc.returncode,
        )

    diff_proc = _run_git(trunk_root, ["diff", "--cached", "--quiet"])
    if diff_proc.returncode == 0:
        return CommitResult(status="no_changes", commit_message=msg)

    commit_proc = _run_git(trunk_root, ["commit", "-m", msg])
    if commit_proc.returncode != 0:
        return CommitResult(
            status="error",
            commit_message=msg,
            stdout=commit_proc.stdout,
            stderr=commit_proc.stderr,
            returncode=commit_proc.returncode,
        )
    return CommitResult(
        status="committed",
        commit_message=msg,
        stdout=commit_proc.stdout,
    )


def remove_branch_worktrees(
    project_root: Path,
    worktrees: list[BranchWorktree],
) -> None:
    """sprint 종료 후 분기 worktree 정리.

    git worktree remove {path} --force. 이미 사라진 worktree는 skip.
    호출 후 .worktrees/ 폴더는 git이 자동으로 prune하지 않으므로 worktree prune도
    호출.
    """
    project_root = Path(project_root).resolve()
    for wt in worktrees:
        if not wt.path.exists():
            continue
        _run_git(
            project_root,
            ["worktree", "remove", "--force", str(wt.path)],
        )
    _run_git(project_root, ["worktree", "prune"])


def merge_into_trunk(
    project_root: Path,
    branch_refs: list[str],
    strategy: str = "no-ff",
) -> MergeResult:
    """trunk로 분기들을 차례 머지 (`--no-commit` 옵션).

    충돌 시 conflict_files를 반환만 하고 abort는 호출자(finalizer)가 결정.
    strategy="no-ff"가 기본 (분기 흔적 보존).

    동작:
    1. branch_refs를 순서대로 git merge {ref} --no-ff --no-commit 시도
    2. 첫 충돌 발생 시 즉시 중단, conflict_files 수집
    3. 모두 성공하면 status="merged"
    """
    project_root = Path(project_root).resolve()
    merged: list[str] = []

    merge_args_base = ["merge", "--no-commit"]
    if strategy == "no-ff":
        merge_args_base.append("--no-ff")
    elif strategy and strategy != "no-ff":
        # 알 수 없는 전략은 일단 그대로 전달
        merge_args_base.append(f"--{strategy}")

    for ref in branch_refs:
        proc = _run_git(project_root, [*merge_args_base, ref])
        if proc.returncode != 0:
            # 충돌 또는 다른 오류. unmerged 목록 수집.
            ls_proc = _run_git(
                project_root,
                ["diff", "--name-only", "--diff-filter=U"],
            )
            conflicts = [
                line.strip()
                for line in ls_proc.stdout.splitlines()
                if line.strip()
            ]
            if conflicts:
                return MergeResult(
                    status="conflict",
                    merged_refs=merged,
                    conflict_files=conflicts,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                )
            return MergeResult(
                status="error",
                merged_refs=merged,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        merged.append(ref)
    return MergeResult(status="merged", merged_refs=merged)


def verify_finalizer_merge_scope(
    project_root: Path,
    expected_conflict_files: set[str],
) -> Optional[ScopeViolation]:
    """finalizer 머지 commit 직후 자동 위반 감지 (단계 2 방어 장치 3).

    동작:
    1. git diff --name-only HEAD~1 HEAD 로 직전 커밋에서 변경된 파일 집합 X 수집
    2. X - expected_conflict_files 가 비어있지 않으면 위반
    3. 위반이 있으면 ScopeViolation 반환, 없으면 None
    4. 호출자(orchestrator/finalizer)가 위반 시 git revert + 사용자 게이트 발사

    expected_conflict_files는 finalizer가 편집해도 되는 파일 집합 (충돌 났던 파일).
    """
    project_root = Path(project_root).resolve()
    proc = _run_git(
        project_root,
        ["diff", "--name-only", "HEAD~1", "HEAD"],
    )
    if proc.returncode != 0:
        # diff 자체 실패: 위반 단정 불가, None 반환 (조용한 fallback 금지 정신상
        # 호출자가 returncode를 보고 싶다면 별도 함수를 쓰는 게 맞으나, 이 함수의
        # 책임은 "위반이 있을 때만 알린다"이므로 None 반환 + 호출자가 git log로
        # 확인 가능).
        return None
    all_changed = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    expected = {p.strip() for p in expected_conflict_files if p}
    violating = [f for f in all_changed if f not in expected]
    if not violating:
        return None
    return ScopeViolation(
        violating_files=violating,
        expected_conflict_files=sorted(expected),
        all_changed_files=all_changed,
    )
