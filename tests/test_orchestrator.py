import time
from pathlib import Path

from forge import orchestrator
from forge.checkpoint import Checkpoint, Phase
from forge.config import ForgeConfig, ProjectPaths


def test_invalidate_stale_review(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.plan_review.write_text("old")
    time.sleep(0.05)
    paths.spec.write_text("new")
    orchestrator._invalidate_stale_review(paths)
    assert not paths.plan_review.exists()


def test_stdin_ready_timeout_quick():
    assert orchestrator._stdin_ready(timeout=0.1) is False


def test_wait_for_approval_reads_signal(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.approval_signal.write_text("resume\n", encoding="utf-8")
    result = orchestrator.wait_for_approval(paths, timeout=1.0)
    assert result == "timeout"


def test_wait_for_approval_skip(tmp_path, monkeypatch):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()

    def fake_stdin_ready(timeout=2.0):
        paths.skip_signal.write_text("skip\n", encoding="utf-8")
        return False

    monkeypatch.setattr(orchestrator, "_stdin_ready", fake_stdin_ready)
    result = orchestrator.wait_for_approval(paths, timeout=2.0)
    assert result == "skip"


# ── v2.3 신규 테스트 ──


def test_parse_has_next_sprint_true(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.sprint_contract.write_text(
        "---\nsprint_number: 1\nhas_next_sprint: true\n---\n# Sprint 1",
        encoding="utf-8",
    )
    assert orchestrator._parse_has_next_sprint(paths) is True


def test_parse_has_next_sprint_false(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.sprint_contract.write_text(
        "---\nsprint_number: 3\nhas_next_sprint: false\n---\n# Sprint 3",
        encoding="utf-8",
    )
    assert orchestrator._parse_has_next_sprint(paths) is False


def test_parse_has_next_sprint_no_frontmatter(tmp_path):
    """frontmatter 없으면 True 가정."""
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.sprint_contract.write_text("# Sprint 1\n내용", encoding="utf-8")
    assert orchestrator._parse_has_next_sprint(paths) is True


def test_archive_sprint(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.qa_report.write_text("## 종합 판정: PASS\n점수: 9/10", encoding="utf-8")
    orchestrator._archive_sprint(1, paths)
    archive = paths.sprint_done_path(1)
    assert archive.exists()
    assert "Sprint 1" in archive.read_text(encoding="utf-8")
    assert "PASS" in archive.read_text(encoding="utf-8")


def test_extract_scores_from_qa_report(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.qa_report.write_text(
        "## 종합 판정: FAIL\n"
        "## 점수\n"
        "• 기능 완성도: 7/10\n"
        "• 코드 품질: 8/10\n"
        "• 테스트 커버리지: 5/10\n"
        "• 명세 충실도: 6/10\n",
        encoding="utf-8",
    )
    scores = orchestrator._extract_scores_from_qa_report(paths)
    assert scores["기능 완성도"] == 7
    assert scores["코드 품질"] == 8
    assert scores["테스트 커버리지"] == 5
    assert scores["명세 충실도"] == 6


def test_extract_checked_items(tmp_path):
    """완료된 체크박스 항목 추출."""
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.sprint_contract.write_text(
        "---\nsprint_number: 1\nhas_next_sprint: true\n---\n"
        "# Sprint 1\n"
        "- [x] API 엔드포인트 구현 — 검증: pytest\n"
        "- [ ] DB 스키마 설계 — 검증: migration\n"
        "- [X] 인증 모듈 — 검증: 토큰 발급\n",
        encoding="utf-8",
    )
    items = orchestrator._extract_checked_items(paths)
    assert len(items) == 2
    assert "API 엔드포인트 구현" in items[0]
    assert "인증 모듈" in items[1]


def test_extract_next_sprint_preview(tmp_path):
    """frontmatter에서 next_sprint_preview 추출."""
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.sprint_contract.write_text(
        '---\nsprint_number: 1\nhas_next_sprint: true\n'
        'estimated_remaining_sprints: 2\n'
        'next_sprint_preview: "DB 스키마 설계 및 마이그레이션"\n---\n# Sprint 1',
        encoding="utf-8",
    )
    preview = orchestrator._extract_next_sprint_preview(paths)
    assert "DB 스키마" in preview


def test_build_sprint_history(tmp_path):
    """스프린트 히스토리 문자열 생성."""
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    (paths.artifacts / "sprint-1-done.md").write_text("done")
    (paths.artifacts / "sprint-2-done.md").write_text("done")
    history = orchestrator._build_sprint_history(paths)
    assert "Sprint 1 PASS" in history
    assert "Sprint 2 PASS" in history


def test_parse_frontmatter(tmp_path):
    """frontmatter dict 파싱."""
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.sprint_contract.write_text(
        "---\nsprint_number: 3\nhas_next_sprint: false\nestimated_remaining_sprints: 0\n---\n",
        encoding="utf-8",
    )
    fm = orchestrator._parse_frontmatter(paths)
    assert fm["sprint_number"] == "3"
    assert fm["has_next_sprint"] == "false"
    assert fm["estimated_remaining_sprints"] == "0"


def test_wait_for_approval_or_stop_eval(tmp_path, monkeypatch):
    """v2.3: /eval 시그널 감지."""
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()

    def fake_stdin_ready(timeout=2.0):
        paths.eval_signal.write_text("eval\n", encoding="utf-8")
        return False

    monkeypatch.setattr(orchestrator, "_stdin_ready", fake_stdin_ready)
    result = orchestrator.wait_for_approval_or_stop(paths, timeout=2.0)
    assert result == "eval"


def test_wait_for_approval_or_stop_stop(tmp_path, monkeypatch):
    """v2.3: /stop 시그널 감지."""
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()

    def fake_stdin_ready(timeout=2.0):
        paths.stop_signal.write_text("stop\n", encoding="utf-8")
        return False

    monkeypatch.setattr(orchestrator, "_stdin_ready", fake_stdin_ready)
    result = orchestrator.wait_for_approval_or_stop(paths, timeout=2.0)
    assert result == "stop"
