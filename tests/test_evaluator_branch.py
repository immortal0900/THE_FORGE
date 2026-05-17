"""evaluator.run_evaluate / is_pass / validate_qa_report branch_id 분기 테스트.

회귀 보호:
- branch_id="trunk" (기본값) → 기존 paths.qa_report 사용 (회귀 0)
- branch_id != "trunk" → paths.branch_paths(branch_id).qa_report 사용

LLM 호출(run_agent_sync)은 monkeypatch로 차단해 prompt/경로 인자 검증만 수행.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.agents import evaluator as ev
from forge.agents.runner import RunResult
from forge.config import ForgeConfig, ProjectPaths


@pytest.fixture
def fake_config() -> ForgeConfig:
    # 환경변수 정화 후 기본값으로 로드.
    import os

    for key in (
        "FORGE_MAX_PARALLEL_BRANCHES",
        "FORGE_BRANCH_FAIL_ESCALATE_THRESHOLD",
        "FORGE_EVALUATOR_MAX_TURNS",
    ):
        os.environ.pop(key, None)
    cfg = ForgeConfig()
    # playwright 끄기 (테스트 환경에 playwright.config 가 없도록 보장).
    cfg.playwright_enabled = False
    return cfg


@pytest.fixture
def project(tmp_path: Path) -> ProjectPaths:
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    return paths


# ── validate_qa_report 분기 ─────────────────────────────────────────────────


def test_validate_qa_report_trunk_default(project: ProjectPaths):
    """기본 branch_id='trunk' → paths.qa_report 사용 (회귀 0)."""
    project.qa_report.write_text("# QA\n\n종합 판정: PASS\n", encoding="utf-8")
    ok, msg = ev.validate_qa_report(project)
    assert ok
    assert msg == "OK"


def test_validate_qa_report_branch_uses_branch_path(project: ProjectPaths):
    """branch_id='branch-1' → artifacts/branches/branch-1/qa-report.md 사용."""
    project.ensure_branch_artifacts("branch-1")
    bp = project.branch_paths("branch-1")
    bp.qa_report.write_text("# QA branch-1\n종합 판정: PASS\n", encoding="utf-8")

    ok, msg = ev.validate_qa_report(project, branch_id="branch-1")
    assert ok
    assert msg == "OK"

    # trunk qa-report는 비어있어야 함 (branch-1 경로만 봤다는 증거).
    assert not project.qa_report.exists()


def test_validate_qa_report_branch_missing_file(project: ProjectPaths):
    ok, msg = ev.validate_qa_report(project, branch_id="branch-2")
    assert not ok
    assert "존재하지 않" in msg


def test_validate_qa_report_branch_missing_verdict(project: ProjectPaths):
    project.ensure_branch_artifacts("branch-3")
    bp = project.branch_paths("branch-3")
    bp.qa_report.write_text("# Empty header only\n", encoding="utf-8")
    ok, msg = ev.validate_qa_report(project, branch_id="branch-3")
    assert not ok
    assert "종합 판정" in msg


# ── is_pass 분기 ────────────────────────────────────────────────────────────


def test_is_pass_trunk_default_pass(project: ProjectPaths):
    project.qa_report.write_text("종합 판정: PASS\n", encoding="utf-8")
    assert ev.is_pass(project) is True


def test_is_pass_trunk_default_fail(project: ProjectPaths):
    project.qa_report.write_text("종합 판정: FAIL\n", encoding="utf-8")
    assert ev.is_pass(project) is False


def test_is_pass_branch_pass(project: ProjectPaths):
    project.ensure_branch_artifacts("branch-1")
    project.branch_paths("branch-1").qa_report.write_text(
        "종합 판정: PASS\n", encoding="utf-8"
    )
    assert ev.is_pass(project, branch_id="branch-1") is True


def test_is_pass_branch_isolation(project: ProjectPaths):
    """branch-1 PASS, branch-2 FAIL — 라우팅 분리 확인."""
    project.ensure_branch_artifacts("branch-1")
    project.ensure_branch_artifacts("branch-2")
    project.branch_paths("branch-1").qa_report.write_text(
        "종합 판정: PASS\n", encoding="utf-8"
    )
    project.branch_paths("branch-2").qa_report.write_text(
        "종합 판정: FAIL\n", encoding="utf-8"
    )
    assert ev.is_pass(project, branch_id="branch-1") is True
    assert ev.is_pass(project, branch_id="branch-2") is False
    # trunk는 파일이 없어 False.
    assert ev.is_pass(project) is False


# ── run_evaluate prompt + paths 라우팅 검증 ─────────────────────────────────


class _RunCall:
    """run_agent_sync 호출 캡처용."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, agent, cwd, prompt, **kwargs):
        self.calls.append(
            {"agent": agent, "cwd": cwd, "prompt": prompt, **kwargs}
        )
        return RunResult(returncode=0, stdout="OK", stderr="")


def test_run_evaluate_trunk_default_prompt(
    project: ProjectPaths, fake_config: ForgeConfig, monkeypatch: pytest.MonkeyPatch
):
    """branch_id='trunk' (기본) → 기존 trunk 프롬프트 + paths.qa_report 라우팅."""
    captured = _RunCall()
    monkeypatch.setattr(ev, "run_agent_sync", captured)

    result = ev.run_evaluate(fake_config, project)
    assert result.returncode == 0
    assert len(captured.calls) == 1
    call = captured.calls[0]
    assert call["agent"] == "evaluator"
    assert call["cwd"] == project.project_root
    # trunk 모드: 기존 프롬프트 그대로 (artifacts/qa-report.md 상대 경로 텍스트).
    assert "artifacts/qa-report.md" in call["prompt"]
    assert "분기" not in call["prompt"][:30]  # "너는 분기 ..." 프롬프트 아님
    assert call["whisper_queue_path"] == project.whisper_queue


def test_run_evaluate_branch_uses_branch_paths(
    project: ProjectPaths, fake_config: ForgeConfig, monkeypatch: pytest.MonkeyPatch
):
    """branch_id='branch-1' → 분기 경로 + trunk 절대 qa-report 경로 prompt 주입."""
    captured = _RunCall()
    monkeypatch.setattr(ev, "run_agent_sync", captured)

    result = ev.run_evaluate(fake_config, project, branch_id="branch-1")
    assert result.returncode == 0
    assert len(captured.calls) == 1
    call = captured.calls[0]
    assert call["agent"] == "evaluator"
    # cwd는 branch_paths.project_root (= 현재 self.project_root, in_worktree=False).
    assert call["cwd"] == project.branch_paths("branch-1").project_root
    # prompt에 trunk 절대 qa-report 경로가 들어가야 함.
    qa_abs = project.branch_paths("branch-1").qa_report.as_posix()
    assert qa_abs in call["prompt"]
    assert "branch-1" in call["prompt"]
    # whisper_queue도 분기별 경로.
    assert call["whisper_queue_path"] == project.branch_paths("branch-1").whisper_queue
