"""worktree.py 단위 테스트 (parallel-branches-design.md 단계 2).

git subprocess 호출은 monkeypatch 로 모킹하여 인자 검증 위주.
실제 git 호출이 있는 통합 시나리오는 회귀 테스트(시나리오 1번)에서 별도 확인.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from forge import worktree
from forge.worktree import (
    BranchWorktree,
    TRUNK_ARTIFACT_PATHSPECS,
    auto_commit_trunk_artifacts,
    auto_commit_worktree,
    create_branch_worktrees,
    merge_into_trunk,
    remove_branch_worktrees,
    verify_finalizer_merge_scope,
)


# ── 헬퍼: subprocess.run 모킹 ───────────────────────────────────────────────


@dataclass
class _FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class _GitCallRecorder:
    """subprocess.run 호출을 가로채 인자를 기록하고 사전 정의된 응답을 돌려준다."""

    def __init__(self, responses=None):
        self.calls: list[list[str]] = []
        self.responses = list(responses or [])
        self.default = _FakeProc()

    def __call__(self, args, **kwargs):
        # 사용자 코드가 항상 ["git", "-C", root, ...] 형태로 호출하는지 확인 가능
        self.calls.append(list(args))
        if self.responses:
            r = self.responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return subprocess.CompletedProcess(
                args, r.returncode, stdout=r.stdout, stderr=r.stderr
            )
        return subprocess.CompletedProcess(
            args, self.default.returncode, stdout=self.default.stdout, stderr=self.default.stderr
        )


@pytest.fixture
def patch_run(monkeypatch):
    def _set(recorder: _GitCallRecorder):
        monkeypatch.setattr(worktree.subprocess, "run", recorder)
        return recorder

    return _set


# ── create_branch_worktrees ────────────────────────────────────────────────


def test_create_branch_worktrees_calls_git(tmp_path, patch_run):
    rec = patch_run(_GitCallRecorder())
    wts = create_branch_worktrees(
        tmp_path,
        sprint_num=1,
        branch_ids=["branch-1", "branch-2"],
        base_ref="HEAD",
    )
    assert len(wts) == 2
    # 두 번 호출 (각 분기 1번씩)
    assert len(rec.calls) == 2
    # 첫 호출 인자 검증
    first = rec.calls[0]
    assert first[0] == "git"
    assert first[1] == "-C"
    assert Path(first[2]) == tmp_path.resolve()
    assert first[3:6] == ["worktree", "add", str(tmp_path.resolve() / ".worktrees" / "sprint-1-branch-1")]
    assert first[6] == "-b"
    assert first[7] == "forge/sprint-1-branch-1"
    assert first[8] == "HEAD"
    # BranchWorktree 필드
    assert wts[0].branch_id == "branch-1"
    assert wts[0].git_branch == "forge/sprint-1-branch-1"
    assert wts[1].branch_id == "branch-2"


def test_create_branch_worktrees_propagates_failure(tmp_path, patch_run):
    patch_run(_GitCallRecorder(responses=[_FakeProc(returncode=128, stderr="fatal: branch exists")]))
    with pytest.raises(RuntimeError) as ei:
        create_branch_worktrees(tmp_path, 1, ["branch-1"])
    assert "branch exists" in str(ei.value)


# ── auto_commit_worktree ──────────────────────────────────────────────────


def test_auto_commit_worktree_commits_when_changes(tmp_path, patch_run):
    rec = patch_run(
        _GitCallRecorder(
            responses=[
                _FakeProc(returncode=0),  # add -A
                _FakeProc(returncode=1),  # diff --cached --quiet (변경 있음 → 1)
                _FakeProc(returncode=0, stdout="[main abc] forge..."),  # commit
            ]
        )
    )
    res = auto_commit_worktree(tmp_path, "branch-1", 2, "generator")
    assert res.status == "committed"
    assert res.commit_message == "forge: sprint-2-branch-1 generator turn"

    # 마지막 호출이 commit 인지
    last = rec.calls[-1]
    assert last[3:5] == ["commit", "-m"]
    assert last[5] == "forge: sprint-2-branch-1 generator turn"


def test_auto_commit_worktree_no_changes(tmp_path, patch_run):
    rec = patch_run(
        _GitCallRecorder(
            responses=[
                _FakeProc(returncode=0),  # add -A
                _FakeProc(returncode=0),  # diff --cached --quiet (변경 없음 → 0)
            ]
        )
    )
    res = auto_commit_worktree(tmp_path, "branch-1", 1, "evaluator")
    assert res.status == "no_changes"
    # commit 호출은 일어나지 않아야 함
    assert all("commit" not in c for c in (call[3:4] for call in rec.calls))


def test_auto_commit_worktree_add_failure_returns_error(tmp_path, patch_run):
    patch_run(
        _GitCallRecorder(
            responses=[
                _FakeProc(returncode=1, stderr="add boom"),
            ]
        )
    )
    res = auto_commit_worktree(tmp_path, "branch-1", 1, "generator")
    assert res.status == "error"
    assert "add boom" in res.stderr


# ── auto_commit_trunk_artifacts ───────────────────────────────────────────


def test_auto_commit_trunk_artifacts_pathspec_safety(tmp_path, patch_run):
    """pathspec 으로 src/, tests/ 를 절대 stage 하지 않는다 (단계 2-2 정책)."""
    rec = patch_run(
        _GitCallRecorder(
            responses=[
                _FakeProc(returncode=0),  # add
                _FakeProc(returncode=1),  # diff (변경 있음)
                _FakeProc(returncode=0),  # commit
            ]
        )
    )
    res = auto_commit_trunk_artifacts(tmp_path, "planner-contract", 3)
    assert res.status == "committed"
    assert res.commit_message == "forge: planner-contract sprint-3"

    # add 호출에 명시된 pathspec 확인
    add_call = rec.calls[0]
    assert add_call[3] == "add"
    assert add_call[4] == "--"
    add_pathspecs = add_call[5:]
    assert tuple(add_pathspecs) == TRUNK_ARTIFACT_PATHSPECS
    # 절대로 src/ 또는 tests/ 가 pathspec 에 포함되면 안 됨
    for p in add_pathspecs:
        assert not p.startswith("src/")
        assert not p.startswith("tests/")
        assert "-A" not in p


def test_auto_commit_trunk_artifacts_no_changes(tmp_path, patch_run):
    patch_run(
        _GitCallRecorder(
            responses=[
                _FakeProc(returncode=0),
                _FakeProc(returncode=0),  # diff no changes
            ]
        )
    )
    res = auto_commit_trunk_artifacts(tmp_path, "finalizer-merge", 1)
    assert res.status == "no_changes"


# ── remove_branch_worktrees ───────────────────────────────────────────────


def test_remove_branch_worktrees_invokes_remove_and_prune(tmp_path, patch_run):
    rec = patch_run(_GitCallRecorder())
    wt_dir = tmp_path / ".worktrees" / "sprint-1-branch-1"
    wt_dir.mkdir(parents=True)
    remove_branch_worktrees(
        tmp_path,
        [BranchWorktree(branch_id="branch-1", path=wt_dir, git_branch="forge/sprint-1-branch-1")],
    )
    # 첫 호출 worktree remove --force {path}, 마지막 호출 worktree prune
    assert rec.calls[0][3:6] == ["worktree", "remove", "--force"]
    assert rec.calls[-1][3:5] == ["worktree", "prune"]


def test_remove_branch_worktrees_skips_missing(tmp_path, patch_run):
    rec = patch_run(_GitCallRecorder())
    missing = tmp_path / ".worktrees" / "gone"
    remove_branch_worktrees(
        tmp_path,
        [BranchWorktree(branch_id="branch-x", path=missing, git_branch="forge/x")],
    )
    # 존재하지 않으면 remove 는 skip, prune 만 호출
    for call in rec.calls:
        assert "remove" not in call


# ── merge_into_trunk ──────────────────────────────────────────────────────


def test_merge_into_trunk_success(tmp_path, patch_run):
    rec = patch_run(
        _GitCallRecorder(
            responses=[
                _FakeProc(returncode=0),  # merge branch-1
                _FakeProc(returncode=0),  # merge branch-2
            ]
        )
    )
    res = merge_into_trunk(
        tmp_path,
        ["forge/sprint-1-branch-1", "forge/sprint-1-branch-2"],
    )
    assert res.status == "merged"
    assert res.merged_refs == ["forge/sprint-1-branch-1", "forge/sprint-1-branch-2"]
    # --no-commit, --no-ff 가 명령에 포함됐는지
    first_merge = rec.calls[0][3:]
    assert "merge" in first_merge
    assert "--no-commit" in first_merge
    assert "--no-ff" in first_merge


def test_merge_into_trunk_conflict(tmp_path, patch_run):
    rec = patch_run(
        _GitCallRecorder(
            responses=[
                _FakeProc(returncode=0),  # merge branch-1 OK
                _FakeProc(returncode=1, stdout="CONFLICT"),  # merge branch-2 conflict
                _FakeProc(returncode=0, stdout="src/auth.py\nsrc/db.py\n"),  # diff --name-only --diff-filter=U
            ]
        )
    )
    res = merge_into_trunk(
        tmp_path,
        ["forge/sprint-1-branch-1", "forge/sprint-1-branch-2"],
    )
    assert res.status == "conflict"
    assert res.merged_refs == ["forge/sprint-1-branch-1"]
    assert res.conflict_files == ["src/auth.py", "src/db.py"]


# ── verify_finalizer_merge_scope ──────────────────────────────────────────


def test_verify_scope_no_violation(tmp_path, patch_run):
    """변경 파일이 모두 expected 안에 있으면 None."""
    patch_run(
        _GitCallRecorder(
            responses=[
                _FakeProc(returncode=0, stdout="src/auth.py\n"),  # diff --name-only HEAD~1 HEAD
            ]
        )
    )
    violation = verify_finalizer_merge_scope(tmp_path, {"src/auth.py"})
    assert violation is None


def test_verify_scope_detects_violation(tmp_path, patch_run):
    """expected 밖 파일 변경 발견 → ScopeViolation."""
    patch_run(
        _GitCallRecorder(
            responses=[
                _FakeProc(returncode=0, stdout="src/auth.py\nartifacts/qa-report.md\n"),
            ]
        )
    )
    violation = verify_finalizer_merge_scope(tmp_path, {"src/auth.py"})
    assert violation is not None
    assert violation.violating_files == ["artifacts/qa-report.md"]
    assert "src/auth.py" in violation.expected_conflict_files


def test_verify_scope_git_failure_returns_none(tmp_path, patch_run):
    """git diff 자체 실패 시 None (조용히 무위반 처리, 호출자가 별도 검증 책임)."""
    patch_run(
        _GitCallRecorder(
            responses=[_FakeProc(returncode=128, stderr="bad rev")]
        )
    )
    assert verify_finalizer_merge_scope(tmp_path, {"x"}) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
