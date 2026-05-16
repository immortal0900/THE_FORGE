"""Evaluator 에이전트 + Playwright 통합.

토대 1 (docs/plan-judgment-velocity.md): subprocess.run batch → 영속 Popen +
stream-json 양방향 마이그레이션. Evaluator는 ASK_USER 정책상 금지
(scaffold/agents/evaluator.md 시스템 프롬프트에 명시) → on_question 콜백 없이 호출.

병렬 분기 (parallel-branches-design.md 단계 6): branch_id="trunk" 기본값으로
회귀 0. branch_id != "trunk" 시 paths.branch_paths(branch_id)로 분기 경로 사용 +
prompt에 trunk 절대 경로 주입 (분기별 qa-report는 .gitignore 영역이라 worktree에
없으므로 generator/evaluator subprocess가 상대 경로로 쓸 수 없다).
"""

from __future__ import annotations

import shutil
import subprocess

from ..config import ForgeConfig, ProjectPaths
from .runner import RunResult, run_agent_sync


def run_evaluate(
    config: ForgeConfig,
    paths: ProjectPaths,
    *,
    notifier=None,
    branch_id: str = "trunk",
) -> RunResult:
    """sprint-contract.md 각 항목을 평가하여 qa-report.md 작성.

    branch_id="trunk" (기본값): 기존 동작 그대로 (artifacts/qa-report.md 작성).
    branch_id != "trunk": 분기 모드. artifacts/branches/{branch_id}/qa-report.md에
    작성. prompt에 trunk 절대 경로를 주입하여 evaluator subprocess가 worktree
    cwd에서도 정확한 위치에 쓰도록 한다.
    """
    if branch_id == "trunk":
        bp = paths
        prompt = (
            "artifacts/sprint-contract.md의 각 항목에 대해 현재 구현을 평가하라. "
            "artifacts/qa-report.md에 보고서를 작성하라. "
            "종합 판정은 PASS 또는 FAIL 중 하나여야 한다."
        )
    else:
        bp = paths.branch_paths(branch_id)
        # branch_paths는 progress_log/qa_report/whisper_queue만 분기별로 override.
        # qa_report는 trunk 절대 경로 (artifacts/branches/{id}/qa-report.md).
        qa_report_abs = bp.qa_report.as_posix()
        prompt = (
            f"너는 분기 {branch_id}의 evaluator다. "
            "artifacts/sprint-contract.md의 각 항목에 대해 현재 구현을 평가하라 "
            f"(특히 분기 {branch_id}의 Parallel Task Graph가 명시한 tasks / files_owned 범위 안에서). "
            f"qa-report는 trunk 절대 경로 **{qa_report_abs}** 에 작성하라 "
            "(자기 cwd의 상대 경로 X — 분기별 qa-report는 trunk 격리 영역). "
            "종합 판정은 PASS 또는 FAIL 중 하나여야 한다."
        )
    result = run_agent_sync(
        "evaluator",
        bp.project_root,
        prompt,
        max_turns=config.evaluator_max_turns,
        whisper_queue_path=bp.whisper_queue,
        notifier=notifier,
    )
    if config.playwright_enabled:
        _append_playwright_results(bp, config.playwright_timeout_seconds)
    return result


def _append_playwright_results(paths: ProjectPaths, timeout: int) -> None:
    """playwright.config.{ts,js,mjs} 존재 시 `playwright test` 실행 후 qa-report.md에 결과 추가."""
    candidates = [
        paths.project_root / "playwright.config.ts",
        paths.project_root / "playwright.config.js",
        paths.project_root / "playwright.config.mjs",
    ]
    if not any(p.exists() for p in candidates):
        return
    try:
        npx = shutil.which("npx") or "npx"
        result = subprocess.run(
            [npx, "playwright", "test"],
            cwd=str(paths.project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        status = "PASS" if result.returncode == 0 else "FAIL"
        output = (result.stdout or "") + "\n" + (result.stderr or "")
    except FileNotFoundError:
        status = "SKIPPED"
        output = "npx/playwright CLI를 찾을 수 없음."
    except subprocess.TimeoutExpired:
        status = "TIMEOUT"
        output = f"Playwright 테스트가 {timeout}초 내에 완료되지 않음."

    section = (
        "\n\n## Playwright E2E 테스트\n"
        f"- 결과: **{status}**\n\n"
        "```\n"
        f"{output.strip()[:4000]}\n"
        "```\n"
    )
    if paths.qa_report.exists():
        existing = paths.qa_report.read_text(encoding="utf-8", errors="replace")
        if "## Playwright E2E 테스트" not in existing:
            paths.qa_report.write_text(existing + section, encoding="utf-8")
    else:
        paths.qa_report.parent.mkdir(parents=True, exist_ok=True)
        paths.qa_report.write_text(
            "# QA Report (Playwright only)\n" + section, encoding="utf-8"
        )


def validate_qa_report(
    paths: ProjectPaths,
    *,
    branch_id: str = "trunk",
) -> tuple[bool, str]:
    """qa-report.md 형식 검증.

    branch_id="trunk": paths.qa_report (artifacts/qa-report.md).
    branch_id != "trunk": paths.branch_paths(branch_id).qa_report.
    """
    target = paths.qa_report if branch_id == "trunk" else paths.branch_paths(branch_id).qa_report
    if not target.exists():
        return False, "qa-report.md가 존재하지 않습니다."
    text = target.read_text(encoding="utf-8", errors="replace")
    if "종합 판정:" not in text:
        return False, "qa-report.md에 '종합 판정:' 항목이 없습니다."
    return True, "OK"


def is_pass(
    paths: ProjectPaths,
    *,
    branch_id: str = "trunk",
) -> bool:
    """qa-report.md 종합 판정이 PASS인지.

    branch_id 라우팅 규칙은 validate_qa_report와 동일.
    """
    target = paths.qa_report if branch_id == "trunk" else paths.branch_paths(branch_id).qa_report
    if not target.exists():
        return False
    text = target.read_text(encoding="utf-8", errors="replace")
    return "종합 판정: PASS" in text
