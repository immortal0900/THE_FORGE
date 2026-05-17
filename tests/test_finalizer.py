"""finalizer.py 단위 테스트 (parallel-branches-design.md 단계 7).

LLM 호출(run_agent_sync)과 git 명령(subprocess.run, merge_into_trunk,
verify_finalizer_merge_scope)을 모킹하여 분기 로직 검증.

검증 시나리오 매핑:
- 4 (자체 해결): conflict -> LLM resolves -> commit -> scope 위반 없음 -> "merged"
- 4-2 (의미적 충돌): conflict -> LLM aborts -> HEAD 변동 없음 -> "merge_conflict"
- 4-3 (스코프 위반): conflict -> LLM commits but touches forbidden file -> scope_violation + revert
- 5 (self-rationalization 방어): FAIL 분기 존재 -> LLM 호출 안 함 -> needs_escalation
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge.agents import finalizer as fin_mod
from forge.agents.finalizer import run_finalize
from forge.config import ForgeConfig, ProjectPaths
from forge.worktree import BranchWorktree, MergeResult, ScopeViolation


@pytest.fixture
def fake_config():
    return ForgeConfig()


@pytest.fixture
def fake_paths(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    (paths.artifacts / "branches").mkdir(parents=True, exist_ok=True)
    return paths


def _make_qa_report(paths: ProjectPaths, branch_id: str, judgment: str) -> None:
    bp = paths.branch_paths(branch_id)
    bp.qa_report.parent.mkdir(parents=True, exist_ok=True)
    bp.qa_report.write_text(
        f"# QA report for {branch_id}\n\n종합 판정: {judgment}\n",
        encoding="utf-8",
    )


def _spec(bid: str):
    return SimpleNamespace(id=bid)


def _wt(bid: str, path: Path) -> BranchWorktree:
    return BranchWorktree(
        branch_id=bid, path=path, git_branch=f"forge/sprint-1-{bid}"
    )


# 시나리오 5: FAIL 사전 검사 -> needs_escalation


def test_run_finalize_fail_branch_returns_needs_escalation(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    _make_qa_report(fake_paths, "branch-1", "PASS")
    _make_qa_report(fake_paths, "branch-2", "FAIL")

    monkeypatch.setattr(
        fin_mod, "run_agent_sync", lambda *a, **k: pytest.fail("LLM 호출되면 안 됨")
    )
    monkeypatch.setattr(
        fin_mod,
        "merge_into_trunk",
        lambda *a, **k: pytest.fail("merge_into_trunk 호출되면 안 됨"),
    )

    branches = [_spec("branch-1"), _spec("branch-2")]
    worktrees = [_wt("branch-1", tmp_path / ".wt1"), _wt("branch-2", tmp_path / ".wt2")]

    result = run_finalize(fake_config, fake_paths, branches, worktrees, sprint_num=1)

    assert result.status == "needs_escalation"
    assert "branch-2" in result.fail_branches
    assert "branch-1" not in result.fail_branches


# 시나리오 4: 머지 충돌 자체 해결 -> merged


def test_run_finalize_resolves_simple_conflict(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    _make_qa_report(fake_paths, "branch-1", "PASS")
    _make_qa_report(fake_paths, "branch-2", "PASS")

    monkeypatch.setattr(
        fin_mod,
        "merge_into_trunk",
        lambda *a, **k: MergeResult(
            status="conflict", merged_refs=[], conflict_files=["src/x.py"]
        ),
    )
    monkeypatch.setattr(
        fin_mod, "_collect_branch_touched_files", lambda *a, **k: {"src/x.py"}
    )
    monkeypatch.setattr(
        fin_mod,
        "run_agent_sync",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="resolved", stderr=""),
    )
    monkeypatch.setattr(fin_mod, "_check_merge_in_progress", lambda p: False)
    head_values = iter(["aaa111", "bbb222"])
    monkeypatch.setattr(
        fin_mod, "_collect_pre_merge_head", lambda p: next(head_values)
    )
    monkeypatch.setattr(
        fin_mod, "verify_finalizer_merge_scope", lambda *a, **k: None
    )

    branches = [_spec("branch-1"), _spec("branch-2")]
    worktrees = [_wt("branch-1", tmp_path / ".wt1"), _wt("branch-2", tmp_path / ".wt2")]

    result = run_finalize(fake_config, fake_paths, branches, worktrees, sprint_num=1)
    assert result.status == "merged"
    assert result.violation is None


# 시나리오 4-2: 의미적 충돌 abort -> merge_conflict


def test_run_finalize_semantic_conflict_aborts(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    _make_qa_report(fake_paths, "branch-1", "PASS")
    _make_qa_report(fake_paths, "branch-2", "PASS")

    monkeypatch.setattr(
        fin_mod,
        "merge_into_trunk",
        lambda *a, **k: MergeResult(
            status="conflict", merged_refs=[], conflict_files=["src/auth.py"]
        ),
    )
    monkeypatch.setattr(
        fin_mod, "_collect_branch_touched_files", lambda *a, **k: {"src/auth.py"}
    )
    monkeypatch.setattr(
        fin_mod,
        "run_agent_sync",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="aborted", stderr=""),
    )
    monkeypatch.setattr(fin_mod, "_check_merge_in_progress", lambda p: False)
    # pre == post (abort라 HEAD 변동 없음)
    monkeypatch.setattr(fin_mod, "_collect_pre_merge_head", lambda p: "ccc333")

    branches = [_spec("branch-1"), _spec("branch-2")]
    worktrees = [_wt("branch-1", tmp_path / ".wt1"), _wt("branch-2", tmp_path / ".wt2")]

    result = run_finalize(fake_config, fake_paths, branches, worktrees, sprint_num=1)
    assert result.status == "merge_conflict"
    assert "src/auth.py" in result.conflict_files


# 시나리오 4-3: scope 위반 감지 -> 자동 revert


def test_run_finalize_scope_violation_triggers_revert(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    _make_qa_report(fake_paths, "branch-1", "PASS")

    monkeypatch.setattr(
        fin_mod,
        "merge_into_trunk",
        lambda *a, **k: MergeResult(
            status="conflict", merged_refs=[], conflict_files=["src/x.py"]
        ),
    )
    monkeypatch.setattr(
        fin_mod, "_collect_branch_touched_files", lambda *a, **k: {"src/x.py"}
    )
    monkeypatch.setattr(
        fin_mod,
        "run_agent_sync",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="rogue", stderr=""),
    )
    monkeypatch.setattr(fin_mod, "_check_merge_in_progress", lambda p: False)
    head_values = iter(["pre", "post"])
    monkeypatch.setattr(
        fin_mod, "_collect_pre_merge_head", lambda p: next(head_values)
    )

    violation = ScopeViolation(
        violating_files=["artifacts/qa-report.md"],
        expected_conflict_files=["src/x.py"],
        all_changed_files=["src/x.py", "artifacts/qa-report.md"],
    )
    monkeypatch.setattr(
        fin_mod, "verify_finalizer_merge_scope", lambda *a, **k: violation
    )

    revert_calls = []
    monkeypatch.setattr(
        fin_mod, "_revert_last_commit", lambda p: revert_calls.append(p) or True
    )

    branches = [_spec("branch-1")]
    worktrees = [_wt("branch-1", tmp_path / ".wt1")]

    result = run_finalize(fake_config, fake_paths, branches, worktrees, sprint_num=1)
    assert result.status == "scope_violation"
    assert result.violation is not None
    assert "artifacts/qa-report.md" in result.violation.violating_files
    assert len(revert_calls) == 1


# 머지 진행 중 잔존 -> 강제 abort + merge_conflict


def test_run_finalize_merge_in_progress_forces_abort(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    _make_qa_report(fake_paths, "branch-1", "PASS")

    monkeypatch.setattr(
        fin_mod,
        "merge_into_trunk",
        lambda *a, **k: MergeResult(
            status="conflict", merged_refs=[], conflict_files=["src/x.py"]
        ),
    )
    monkeypatch.setattr(
        fin_mod, "_collect_branch_touched_files", lambda *a, **k: {"src/x.py"}
    )
    monkeypatch.setattr(
        fin_mod,
        "run_agent_sync",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    # MERGE_HEAD 존재 (LLM이 마무리 못함)
    monkeypatch.setattr(fin_mod, "_check_merge_in_progress", lambda p: True)
    monkeypatch.setattr(fin_mod, "_collect_pre_merge_head", lambda p: "x")

    abort_calls = []
    monkeypatch.setattr(
        fin_mod, "_abort_merge", lambda p: abort_calls.append(p) or None
    )

    branches = [_spec("branch-1")]
    worktrees = [_wt("branch-1", tmp_path / ".wt1")]

    result = run_finalize(fake_config, fake_paths, branches, worktrees, sprint_num=1)
    assert result.status == "merge_conflict"
    assert len(abort_calls) == 1


# 충돌 없는 정상 머지 -> LLM 호출 안 함


def test_run_finalize_clean_merge_skips_llm(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    _make_qa_report(fake_paths, "branch-1", "PASS")
    _make_qa_report(fake_paths, "branch-2", "PASS")

    monkeypatch.setattr(
        fin_mod,
        "merge_into_trunk",
        lambda *a, **k: MergeResult(
            status="merged",
            merged_refs=["forge/sprint-1-branch-1", "forge/sprint-1-branch-2"],
        ),
    )
    monkeypatch.setattr(
        fin_mod, "_collect_branch_touched_files", lambda *a, **k: {"src/x.py"}
    )
    monkeypatch.setattr(
        fin_mod, "run_agent_sync", lambda *a, **k: pytest.fail("LLM 호출되면 안 됨")
    )
    # subprocess.run을 통째로 stub: clean merge 케이스에서 staged diff 검사용.
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode=0, stdout="", stderr=""),
    )

    branches = [_spec("branch-1"), _spec("branch-2")]
    worktrees = [_wt("branch-1", tmp_path / ".wt1"), _wt("branch-2", tmp_path / ".wt2")]

    result = run_finalize(fake_config, fake_paths, branches, worktrees, sprint_num=1)
    assert result.status == "merged"


# 부분 머지 모드: FAIL이 섞여 있으면 needs_escalation


def test_run_finalize_partial_mode_rejects_mixed_fail(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    _make_qa_report(fake_paths, "branch-1", "PASS")
    _make_qa_report(fake_paths, "branch-2", "FAIL")

    monkeypatch.setattr(
        fin_mod, "merge_into_trunk", lambda *a, **k: pytest.fail("호출되면 안 됨")
    )

    branches = [_spec("branch-1"), _spec("branch-2")]
    worktrees = [_wt("branch-1", tmp_path / ".wt1"), _wt("branch-2", tmp_path / ".wt2")]
    result = run_finalize(
        fake_config, fake_paths, branches, worktrees, partial=True, sprint_num=1
    )
    assert result.status == "needs_escalation"
