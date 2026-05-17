"""orchestrator의 병렬 finalization/escalation helper 단위 테스트 (단계 8)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from forge import orchestrator as orch
from forge.agents.finalizer import FinalizeResult
from forge.config import ForgeConfig, ProjectPaths
from forge.worktree import BranchWorktree, ScopeViolation


@pytest.fixture
def fake_config():
    return ForgeConfig()


@pytest.fixture
def fake_paths(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    (paths.artifacts / "branches").mkdir(parents=True, exist_ok=True)
    return paths


def _make_qa_report(
    paths: ProjectPaths,
    branch_id: str,
    judgment: str,
    score_text: str = "completeness: 7/10",
) -> None:
    bp = paths.branch_paths(branch_id)
    bp.qa_report.parent.mkdir(parents=True, exist_ok=True)
    bp.qa_report.write_text(
        f"# QA report {branch_id}\n\n{score_text}\n\n종합 판정: {judgment}\n",
        encoding="utf-8",
    )


def _spec(bid: str):
    return SimpleNamespace(id=bid)


def _wt(bid: str, path: Path) -> BranchWorktree:
    return BranchWorktree(branch_id=bid, path=path, git_branch=f"forge/sprint-1-{bid}")


# _collect_branch_summary


def test_collect_branch_summary_normalizes_status(fake_paths):
    _make_qa_report(fake_paths, "branch-1", "PASS", "completeness: 9/10")
    _make_qa_report(fake_paths, "branch-2", "FAIL", "completeness: 4/10")

    branch_states = [
        SimpleNamespace(branch_id="branch-1", status="passed", consecutive_fails=0),
        SimpleNamespace(branch_id="branch-2", status="escalated", consecutive_fails=2),
    ]
    summaries = orch._collect_branch_summary(fake_paths, branch_states)
    by_id = {s["branch_id"]: s for s in summaries}
    assert by_id["branch-1"]["status"] == "PASS"
    assert by_id["branch-2"]["status"] == "FAIL"
    assert by_id["branch-2"]["consecutive_fails"] == 2
    assert "completeness 4/10" in by_id["branch-2"]["score"]


# _notify_fail_with_options 정정: escalation 시점만 알림


def test_notify_fail_skips_when_below_escalate_threshold(fake_config, fake_paths):
    """branch_summaries는 주어졌지만 escalated_branches가 비어있으면 early return."""
    notifier = MagicMock()
    tracer = MagicMock()
    tracer.sprint_totals.return_value = {
        "duration_seconds": 0,
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_cache": 0,
    }

    orch._notify_fail_with_options(
        notifier,
        fake_config,
        tracer,
        sprint_num=1,
        paths=fake_paths,
        consecutive=1,
        branch_summaries=[
            {"branch_id": "branch-1", "status": "FAIL", "consecutive_fails": 1}
        ],
        escalated_branches=[],
    )
    notifier.notify.assert_not_called()


def test_notify_fail_emits_escalation_when_threshold_reached(fake_config, fake_paths):
    notifier = MagicMock()
    tracer = MagicMock()
    tracer.sprint_totals.return_value = {
        "duration_seconds": 60,
        "tokens_input": 100,
        "tokens_output": 50,
        "tokens_cache": 0,
    }

    orch._notify_fail_with_options(
        notifier,
        fake_config,
        tracer,
        sprint_num=2,
        paths=fake_paths,
        consecutive=2,
        branch_summaries=[
            {"branch_id": "branch-1", "status": "PASS", "consecutive_fails": 0},
            {"branch_id": "branch-2", "status": "FAIL", "consecutive_fails": 2},
        ],
        escalated_branches=["branch-2"],
    )
    notifier.notify.assert_called_once()
    args, _ = notifier.notify.call_args
    assert args[0] == "qa_fail"
    msg = args[1]
    assert "ESCALATION" in msg
    assert "branch-2" in msg
    assert "/resume" in msg


def test_notify_fail_single_branch_mode_unchanged(fake_config, fake_paths):
    """기존 단일 분기 경로(branch_summaries=None)는 그대로 동작 (회귀 0)."""
    fake_paths.qa_report.write_text(
        "completeness: 4/10\n\n종합 판정: FAIL\n", encoding="utf-8"
    )
    notifier = MagicMock()
    tracer = MagicMock()
    tracer.sprint_totals.return_value = {
        "duration_seconds": 60,
        "tokens_input": 100,
        "tokens_output": 50,
        "tokens_cache": 0,
    }

    orch._notify_fail_with_options(
        notifier,
        fake_config,
        tracer,
        sprint_num=1,
        paths=fake_paths,
        consecutive=1,
    )
    notifier.notify.assert_called_once()
    msg = notifier.notify.call_args[0][1]
    assert "Sprint 1 FAILED" in msg
    assert "ESCALATION" not in msg


# _handle_parallel_sprint_finalization


def test_finalization_merged_cleans_up_worktrees(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    notifier = MagicMock()
    remove_calls = []
    commit_calls = []

    import forge.agents.finalizer as fin_mod
    import forge.worktree as wt_mod

    monkeypatch.setattr(
        fin_mod,
        "run_finalize",
        lambda *a, **k: FinalizeResult(
            status="merged", merged_refs=["forge/sprint-1-branch-1"]
        ),
    )
    monkeypatch.setattr(
        wt_mod,
        "remove_branch_worktrees",
        lambda root, wts: remove_calls.append((root, wts)),
    )
    monkeypatch.setattr(
        wt_mod,
        "auto_commit_trunk_artifacts",
        lambda root, kind, n: commit_calls.append((root, kind, n)) or None,
    )

    result = orch._handle_parallel_sprint_finalization(
        fake_config,
        fake_paths,
        sprint_num=1,
        branches=[_spec("branch-1")],
        worktrees=[_wt("branch-1", tmp_path / ".wt1")],
        notifier=notifier,
    )

    assert result.status == "merged"
    assert len(remove_calls) == 1
    assert len(commit_calls) == 1
    assert commit_calls[0][1] == "finalizer-merge"


def test_finalization_scope_violation_emits_warning(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    notifier = MagicMock()
    import forge.agents.finalizer as fin_mod

    violation = ScopeViolation(
        violating_files=["artifacts/qa-report.md"],
        expected_conflict_files=["src/x.py"],
        all_changed_files=["src/x.py", "artifacts/qa-report.md"],
    )
    monkeypatch.setattr(
        fin_mod,
        "run_finalize",
        lambda *a, **k: FinalizeResult(
            status="scope_violation",
            violation=violation,
            detail="자동 revert 성공.",
        ),
    )

    result = orch._handle_parallel_sprint_finalization(
        fake_config,
        fake_paths,
        sprint_num=1,
        branches=[_spec("branch-1")],
        worktrees=[_wt("branch-1", tmp_path / ".wt1")],
        notifier=notifier,
    )

    assert result.status == "scope_violation"
    assert any(call.args[0] == "warning" for call in notifier.notify.call_args_list)


# _handle_parallel_sprint_escalation


def test_escalation_partial_merge_pass_branches_only(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    """PASS/FAIL 섞임 -> PASS만 partial 머지, FAIL worktree 보존, 알림 1건."""
    _make_qa_report(fake_paths, "branch-1", "PASS")
    _make_qa_report(fake_paths, "branch-2", "FAIL")

    notifier = MagicMock()

    import forge.agents.finalizer as fin_mod
    import forge.worktree as wt_mod

    finalize_calls = []

    def _stub_run_finalize(config, paths, branches, worktrees, **kwargs):
        finalize_calls.append(
            {
                "branches": [b.id for b in branches],
                "partial": kwargs.get("partial"),
            }
        )
        return FinalizeResult(status="merged_partial", merged_refs=[])

    monkeypatch.setattr(fin_mod, "run_finalize", _stub_run_finalize)

    remove_calls = []
    monkeypatch.setattr(
        wt_mod,
        "remove_branch_worktrees",
        lambda root, wts: remove_calls.append([wt.branch_id for wt in wts]),
    )
    monkeypatch.setattr(
        wt_mod, "auto_commit_trunk_artifacts", lambda *a, **k: None
    )

    monkeypatch.setattr(
        orch, "wait_for_approval_or_stop", lambda paths, timeout: "resume"
    )

    branches = [_spec("branch-1"), _spec("branch-2")]
    worktrees = [
        _wt("branch-1", tmp_path / ".wt1"),
        _wt("branch-2", tmp_path / ".wt2"),
    ]
    branch_states = [
        SimpleNamespace(branch_id="branch-1", status="passed", consecutive_fails=0),
        SimpleNamespace(branch_id="branch-2", status="escalated", consecutive_fails=2),
    ]

    out = orch._handle_parallel_sprint_escalation(
        fake_config,
        fake_paths,
        sprint_num=1,
        branches=branches,
        worktrees=worktrees,
        branch_states=branch_states,
        notifier=notifier,
    )

    assert out["pass_branches"] == ["branch-1"]
    assert out["fail_branches"] == ["branch-2"]
    assert out["partial_merge_status"] == "merged_partial"
    assert out["user_decision"] == "resume"

    assert finalize_calls and finalize_calls[0]["branches"] == ["branch-1"]
    assert finalize_calls[0]["partial"] is True

    # PASS worktree만 정리, FAIL은 보존
    assert remove_calls == [["branch-1"]]

    assert notifier.notify.call_count == 1
    msg = notifier.notify.call_args[0][1]
    assert "ESCALATION" in msg
    assert "branch-2" in msg


def test_escalation_all_fail_skips_partial_merge(
    monkeypatch, fake_config, fake_paths, tmp_path
):
    """모두 FAIL이면 부분 머지 안 함 (pass_branches 비어있음), 알림만."""
    _make_qa_report(fake_paths, "branch-1", "FAIL")
    _make_qa_report(fake_paths, "branch-2", "FAIL")

    notifier = MagicMock()
    import forge.agents.finalizer as fin_mod

    monkeypatch.setattr(
        fin_mod, "run_finalize", lambda *a, **k: pytest.fail("호출되면 안 됨")
    )
    monkeypatch.setattr(
        orch, "wait_for_approval_or_stop", lambda paths, timeout: "stop"
    )

    branches = [_spec("branch-1"), _spec("branch-2")]
    worktrees = [
        _wt("branch-1", tmp_path / ".wt1"),
        _wt("branch-2", tmp_path / ".wt2"),
    ]
    branch_states = [
        SimpleNamespace(branch_id="branch-1", status="failed", consecutive_fails=2),
        SimpleNamespace(branch_id="branch-2", status="failed", consecutive_fails=2),
    ]

    out = orch._handle_parallel_sprint_escalation(
        fake_config,
        fake_paths,
        sprint_num=1,
        branches=branches,
        worktrees=worktrees,
        branch_states=branch_states,
        notifier=notifier,
    )

    assert out["pass_branches"] == []
    assert out["fail_branches"] == ["branch-1", "branch-2"]
    assert out["partial_merge_status"] == "skipped"
    assert out["user_decision"] == "stop"
    notifier.notify.assert_called_once()


# ── _handle_planner_replan_after_escalation (parallel-branches-design.md 단계 8-2 5번째) ──


def _touch_contract(paths: ProjectPaths, content: str = "# sprint-contract\n") -> float:
    paths.sprint_contract.parent.mkdir(parents=True, exist_ok=True)
    paths.sprint_contract.write_text(content, encoding="utf-8")
    return paths.sprint_contract.stat().st_mtime


def test_planner_replan_success_removes_fail_worktrees(fake_config, fake_paths, tmp_path, monkeypatch):
    """Mode E가 contract mtime 갱신 시: FAIL worktree 정리 + status=replanned."""
    _touch_contract(fake_paths, "# old contract\n")

    def fake_run(*args, **kwargs):
        # Mode E가 sprint-contract.md를 새로 쓴 것처럼 mtime 진행
        fake_paths.sprint_contract.write_text("# new contract after replan\n", encoding="utf-8")
        import os
        now = fake_paths.sprint_contract.stat().st_mtime
        os.utime(fake_paths.sprint_contract, (now + 5, now + 5))
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    removed_calls = []
    commit_calls = []

    def fake_remove(root, wts):
        removed_calls.append([wt.branch_id for wt in wts])

    def fake_commit(root, turn_kind, sprint_num):
        commit_calls.append((turn_kind, sprint_num))
        return SimpleNamespace(status="committed", commit_message=turn_kind)

    monkeypatch.setattr(orch.pl, "run_plan_replan", fake_run)
    monkeypatch.setattr("forge.worktree.remove_branch_worktrees", fake_remove)
    monkeypatch.setattr("forge.worktree.auto_commit_trunk_artifacts", fake_commit)

    worktrees = [
        _wt("branch-1", tmp_path / ".worktrees/sprint-1-branch-1"),  # PASS, 정리 X
        _wt("branch-2", tmp_path / ".worktrees/sprint-1-branch-2"),  # FAIL, 정리 O
    ]
    notifier = MagicMock()

    out = orch._handle_planner_replan_after_escalation(
        fake_config, fake_paths,
        sprint_num=1,
        escalated_branch_ids=["branch-2"],
        passed_branch_ids=["branch-1"],
        worktrees=worktrees,
        notifier=notifier,
    )

    assert out["status"] == "replanned"
    assert out["fail_worktrees_removed"] == 1
    assert removed_calls == [["branch-2"]]
    assert ("planner-replan", 1) in commit_calls
    # info 알림 1건 발사
    assert notifier.notify.called


def test_planner_replan_mtime_unchanged_returns_planner_failed(
    fake_config, fake_paths, tmp_path, monkeypatch
):
    """Mode E가 sprint-contract.md mtime을 안 갱신하면 status=planner_failed + 게이트 알림."""
    _touch_contract(fake_paths, "# unchanged contract\n")

    def fake_run(*args, **kwargs):
        # Write 안 함 (mtime 그대로)
        return SimpleNamespace(stdout="text-only", stderr="", returncode=0)

    monkeypatch.setattr(orch.pl, "run_plan_replan", fake_run)
    monkeypatch.setattr("forge.worktree.remove_branch_worktrees", lambda *a, **k: None)
    monkeypatch.setattr("forge.worktree.auto_commit_trunk_artifacts", lambda *a, **k: None)

    worktrees = [_wt("branch-2", tmp_path / ".worktrees/sprint-1-branch-2")]
    notifier = MagicMock()

    out = orch._handle_planner_replan_after_escalation(
        fake_config, fake_paths,
        sprint_num=2,
        escalated_branch_ids=["branch-2"],
        passed_branch_ids=[],
        worktrees=worktrees,
        notifier=notifier,
    )

    assert out["status"] == "planner_failed"
    assert out["fail_worktrees_removed"] == 0
    assert "mtime not updated" in out["detail"]
    notifier.notify.assert_called_once()


def test_planner_replan_exception_returns_planner_failed(
    fake_config, fake_paths, tmp_path, monkeypatch
):
    """Mode E 호출 자체가 예외를 던지면 status=planner_failed + error 알림."""
    _touch_contract(fake_paths)

    def fake_run(*args, **kwargs):
        raise RuntimeError("simulated planner crash")

    monkeypatch.setattr(orch.pl, "run_plan_replan", fake_run)

    notifier = MagicMock()
    out = orch._handle_planner_replan_after_escalation(
        fake_config, fake_paths,
        sprint_num=1,
        escalated_branch_ids=["branch-2"],
        passed_branch_ids=[],
        worktrees=[],
        notifier=notifier,
    )

    assert out["status"] == "planner_failed"
    assert "simulated planner crash" in out["detail"]
    notifier.notify.assert_called_once()


def test_planner_replan_no_escalated_branches_still_works(
    fake_config, fake_paths, tmp_path, monkeypatch
):
    """edge case: escalated_branch_ids 빈 리스트여도 mtime 갱신되면 replanned 반환."""
    _touch_contract(fake_paths, "# old\n")

    def fake_run(*args, **kwargs):
        fake_paths.sprint_contract.write_text("# new\n", encoding="utf-8")
        import os
        now = fake_paths.sprint_contract.stat().st_mtime
        os.utime(fake_paths.sprint_contract, (now + 5, now + 5))
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr(orch.pl, "run_plan_replan", fake_run)
    monkeypatch.setattr("forge.worktree.remove_branch_worktrees", lambda *a, **k: None)
    monkeypatch.setattr("forge.worktree.auto_commit_trunk_artifacts", lambda *a, **k: None)

    notifier = MagicMock()
    out = orch._handle_planner_replan_after_escalation(
        fake_config, fake_paths,
        sprint_num=1,
        escalated_branch_ids=[],
        passed_branch_ids=["branch-1", "branch-2"],
        worktrees=[],
        notifier=notifier,
    )

    assert out["status"] == "replanned"
    assert out["fail_worktrees_removed"] == 0
