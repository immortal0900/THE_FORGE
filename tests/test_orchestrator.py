from pathlib import Path

from forge import orchestrator
from forge.checkpoint import Checkpoint, Phase
from forge.config import ProjectPaths


def test_invalidate_stale_review(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.plan_review.write_text("old")
    # spec.md를 이후에 생성하여 mtime이 더 늦도록
    import time

    time.sleep(0.05)
    paths.spec.write_text("new")
    orchestrator._invalidate_stale_review(paths)
    assert not paths.plan_review.exists()


def test_stdin_ready_timeout_quick():
    # stdin에 입력 없을 때 timeout 내 False 반환
    assert orchestrator._stdin_ready(timeout=0.1) is False


def test_wait_for_approval_reads_signal(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.approval_signal.write_text("resume\n", encoding="utf-8")
    result = orchestrator.wait_for_approval(paths, timeout=1.0)
    # signal 파일은 wait 시작 시 삭제되므로 stdin timeout 됨
    assert result == "timeout"


def test_wait_for_approval_skip(tmp_path, monkeypatch):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()

    # 시그널을 지운 직후 다시 작성되도록 _stdin_ready를 패치하여 skip 파일 생성
    original = orchestrator._stdin_ready

    def fake_stdin_ready(timeout=2.0):
        paths.skip_signal.write_text("skip\n", encoding="utf-8")
        return False

    monkeypatch.setattr(orchestrator, "_stdin_ready", fake_stdin_ready)
    try:
        result = orchestrator.wait_for_approval(paths, timeout=2.0)
    finally:
        monkeypatch.setattr(orchestrator, "_stdin_ready", original)
    assert result == "skip"


def test_handle_results_pass(tmp_path):
    from forge.config import ForgeConfig

    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.qa_report.write_text("## 종합 판정: PASS\n내용", encoding="utf-8")
    cp = Checkpoint(phase=Phase.EVALUATING_DONE)
    code = orchestrator._handle_results(ForgeConfig(), paths, cp, sprint_num=1)
    assert code == 0
    assert paths.sprint_done_path(1).exists()


def test_handle_results_invalid_report(tmp_path):
    from forge.config import ForgeConfig

    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    # qa-report.md 없음
    cp = Checkpoint(phase=Phase.EVALUATING_DONE)
    code = orchestrator._handle_results(ForgeConfig(), paths, cp, sprint_num=1)
    assert code == 4
