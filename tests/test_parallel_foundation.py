"""parallel-branches-design.md 단계 0/1/3 단위 테스트 (세션 A 산출물).

worktree.py 의 git subprocess 호출은 test_worktree.py 에서 모킹 검증.
"""

from __future__ import annotations

import json

import pytest

from forge.checkpoint import BranchState, Checkpoint, Phase
from forge.config import ForgeConfig, ProjectPaths


# ── 단계 0: ForgeConfig 새 필드 + clamp 검증 ─────────────────────────────────


def test_parallel_defaults(tmp_path, monkeypatch):
    """기본값: max_parallel_branches=1 (회귀 0), threshold=2."""
    for v in (
        "FORGE_MAX_PARALLEL_BRANCHES",
        "FORGE_BRANCH_FAIL_ESCALATE_THRESHOLD",
    ):
        monkeypatch.delenv(v, raising=False)
    cfg = ForgeConfig.load(tmp_path)
    assert cfg.max_parallel_branches == 1
    assert cfg.branch_fail_escalate_threshold == 2


def test_max_parallel_branches_clamp_high(tmp_path, monkeypatch):
    """5 → 4 로 clamp (1 <= N <= 4)."""
    monkeypatch.setenv("FORGE_MAX_PARALLEL_BRANCHES", "5")
    cfg = ForgeConfig.load(tmp_path)
    assert cfg.max_parallel_branches == 4


def test_max_parallel_branches_clamp_low(tmp_path, monkeypatch):
    """0 → 1 로 clamp."""
    monkeypatch.setenv("FORGE_MAX_PARALLEL_BRANCHES", "0")
    cfg = ForgeConfig.load(tmp_path)
    assert cfg.max_parallel_branches == 1


def test_branch_fail_escalate_threshold_env(tmp_path, monkeypatch):
    """환경변수에서 정상 값(3) 로드."""
    monkeypatch.setenv("FORGE_BRANCH_FAIL_ESCALATE_THRESHOLD", "3")
    cfg = ForgeConfig.load(tmp_path)
    assert cfg.branch_fail_escalate_threshold == 3


def test_branch_fail_escalate_threshold_clamp(tmp_path, monkeypatch):
    """음수 → 1 로 clamp."""
    monkeypatch.setenv("FORGE_BRANCH_FAIL_ESCALATE_THRESHOLD", "-3")
    cfg = ForgeConfig.load(tmp_path)
    assert cfg.branch_fail_escalate_threshold == 1


# ── 단계 1: BranchState round-trip + Checkpoint v1 호환 ──────────────────────


def test_branch_state_defaults():
    bs = BranchState(branch_id="branch-1")
    assert bs.branch_id == "branch-1"
    assert bs.phase == Phase.NONE
    assert bs.consecutive_fails == 0
    assert bs.status == "active"
    assert bs.timestamp


def test_checkpoint_branches_default_empty():
    """기본 Checkpoint.branches 는 빈 리스트 (단일 분기 모드 = 회귀 0)."""
    cp = Checkpoint()
    assert cp.branches == []


def test_checkpoint_round_trip_with_branches(tmp_path):
    """BranchState 가 든 Checkpoint 저장/로드 round-trip."""
    cp = Checkpoint(
        phase=Phase.GENERATING,
        detail="parallel mid",
        branches=[
            BranchState(
                branch_id="branch-1",
                phase=Phase.GENERATING,
                sprint=2,
                consecutive_fails=1,
                worktree_path=".worktrees/sprint-2-branch-1",
                git_branch="forge/sprint-2-branch-1",
                status="active",
                detail="generator running",
            ),
            BranchState(
                branch_id="branch-2",
                phase=Phase.EVALUATING_DONE,
                sprint=2,
                status="passed",
            ),
        ],
    )
    path = tmp_path / ".harness-checkpoint"
    cp.save(path)
    loaded = Checkpoint.load(path)
    assert loaded.phase == Phase.GENERATING
    assert loaded.detail == "parallel mid"
    assert len(loaded.branches) == 2
    assert loaded.branches[0].branch_id == "branch-1"
    assert loaded.branches[0].phase == Phase.GENERATING
    assert loaded.branches[0].consecutive_fails == 1
    assert loaded.branches[0].worktree_path == ".worktrees/sprint-2-branch-1"
    assert loaded.branches[0].git_branch == "forge/sprint-2-branch-1"
    assert loaded.branches[1].status == "passed"
    assert loaded.branches[1].sprint == 2


def test_checkpoint_v1_load_compat(tmp_path):
    """옛 .harness-checkpoint (branches 키 없음) 로드 → 빈 리스트로 폴백, 회귀 0."""
    path = tmp_path / ".harness-checkpoint"
    legacy = {
        "phase": int(Phase.GENERATING),
        "phase_name": "GENERATING",
        "detail": "legacy",
        "timestamp": "2026-05-01T10:00:00",
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    loaded = Checkpoint.load(path)
    assert loaded.phase == Phase.GENERATING
    assert loaded.detail == "legacy"
    assert loaded.timestamp == "2026-05-01T10:00:00"
    assert loaded.branches == []


def test_checkpoint_save_persists_branches_key(tmp_path):
    """save 후 JSON 에 branches 키가 항상 존재 (단일 분기여도 빈 리스트)."""
    cp = Checkpoint(phase=Phase.PLANNING)
    path = tmp_path / ".harness-checkpoint"
    cp.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["branches"] == []
    assert data["phase"] == int(Phase.PLANNING)


# ── 단계 3: ProjectPaths.branch_paths + trunk_root ──────────────────────────


def test_branch_paths_trunk_returns_self(tmp_path):
    """branch_id='trunk' 면 self 그대로 반환 (회귀 0 보호)."""
    paths = ProjectPaths(tmp_path)
    bp = paths.branch_paths("trunk")
    assert bp is paths


def test_branch_paths_non_trunk_overrides_branch_dirs(tmp_path):
    """branch_id != 'trunk' 일 때 progress_log/qa_report/whisper_queue 가 분기 격리 경로."""
    paths = ProjectPaths(tmp_path)
    bp = paths.branch_paths("branch-1")

    # 분기별 격리 경로
    expected_branch_dir = paths.trunk_root / "artifacts" / "branches" / "branch-1"
    assert bp.progress_log == expected_branch_dir / "progress-log.md"
    assert bp.qa_report == expected_branch_dir / "qa-report.md"
    assert bp.whisper_queue == expected_branch_dir / "whisper-queue.jsonl"

    # 공유 SSoT는 그대로 (in_worktree=False 기본)
    assert bp.spec == paths.spec
    assert bp.sprint_contract == paths.sprint_contract
    assert bp.plan_review == paths.plan_review


def test_branch_paths_in_worktree_keeps_spec_relative(tmp_path):
    """in_worktree=True 모드: spec/contract 는 self.project_root 기준 (= worktree 카피)."""
    worktree_cwd = tmp_path / ".worktrees" / "sprint-1-branch-1"
    worktree_cwd.mkdir(parents=True, exist_ok=True)
    paths = ProjectPaths(worktree_cwd)
    bp = paths.branch_paths("branch-1", in_worktree=True)
    assert bp.project_root == worktree_cwd.resolve()
    assert bp.spec == worktree_cwd.resolve() / "artifacts" / "spec.md"


def test_trunk_root_outside_git_falls_back(tmp_path):
    """git not-a-repo 위치에서 trunk_root 는 project_root 로 fallback (안전)."""
    paths = ProjectPaths(tmp_path)
    # tmp_path 는 git 리포지토리가 아니므로 trunk_root 가 그대로 반환되어야 한다.
    assert paths.trunk_root == tmp_path.resolve()


def test_ensure_branch_artifacts_creates_dir(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_branch_artifacts("branch-2")
    assert (tmp_path / "artifacts" / "branches" / "branch-2").is_dir()


def test_ensure_branch_artifacts_trunk_noop(tmp_path):
    """branch_id='trunk' 면 디렉토리 생성 안 함."""
    paths = ProjectPaths(tmp_path)
    paths.ensure_branch_artifacts("trunk")
    assert not (tmp_path / "artifacts" / "branches").exists()


# ── 회귀 시나리오 1번 보호: N=1 기본값에서 단일 분기 흐름 ────────────────────


def test_regression_n1_default_no_parallel_state(tmp_path, monkeypatch):
    """회귀 시나리오 1번: FORGE_MAX_PARALLEL_BRANCHES 미설정 (= 기본 1).

    이 상태에서는 다음이 모두 단일 분기(trunk) 흐름과 동일해야 한다:
    - max_parallel_branches == 1
    - Checkpoint.branches == [] (빈 리스트 = 직렬 모드)
    - branch_paths("trunk") is paths (self 반환, 새 객체 X)
    - ensure_branch_artifacts("trunk")는 디렉토리 생성 안 함
    """
    for v in (
        "FORGE_MAX_PARALLEL_BRANCHES",
        "FORGE_BRANCH_FAIL_ESCALATE_THRESHOLD",
    ):
        monkeypatch.delenv(v, raising=False)
    cfg = ForgeConfig.load(tmp_path)
    assert cfg.max_parallel_branches == 1

    cp = Checkpoint()
    assert cp.branches == []

    paths = ProjectPaths(tmp_path)
    assert paths.branch_paths("trunk") is paths

    paths.ensure_branch_artifacts("trunk")
    assert not (tmp_path / "artifacts" / "branches").exists()


def test_regression_gitignore_entries_idempotent(tmp_path):
    """`_ensure_gitignore` 호출 후 같은 항목 중복 추가 없음 + 새 항목 누락 없음."""
    from forge.cli import _ensure_gitignore

    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    _ensure_gitignore(paths)
    first = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    _ensure_gitignore(paths)
    second = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert first == second  # 멱등

    # 신규 항목 4개 모두 포함
    for entry in (".worktrees/", "artifacts/branches/", "artifacts/sprint-*-done.md", "artifacts/.merge-decisions/"):
        assert entry in first, f"missing gitignore entry: {entry}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
