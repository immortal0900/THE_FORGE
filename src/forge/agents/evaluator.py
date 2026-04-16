"""Evaluator 에이전트 + Playwright 통합."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess

from ..config import ForgeConfig, ProjectPaths


def _run_claude_agent(
    prompt: str,
    agent: str,
    max_turns: int,
    cwd: Path,
    timeout: int = 1800,
) -> CompletedProcess:
    claude = shutil.which("claude") or "claude"
    return subprocess.run(
        [
            claude,
            "-p",
            "--agent",
            agent,
            "--max-turns",
            str(max_turns),
            "--permission-mode",
            "bypassPermissions",
            prompt,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def run_evaluate(config: ForgeConfig, paths: ProjectPaths) -> CompletedProcess:
    """sprint-contract.md 각 항목을 평가하여 qa-report.md 작성."""
    prompt = (
        "artifacts/sprint-contract.md의 각 항목에 대해 현재 구현을 평가하라. "
        "artifacts/qa-report.md에 보고서를 작성하라. "
        "종합 판정은 PASS 또는 FAIL 중 하나여야 한다."
    )
    result = _run_claude_agent(
        prompt, "evaluator", config.evaluator_max_turns, paths.project_root
    )
    if config.playwright_enabled:
        _append_playwright_results(paths, config.playwright_timeout_seconds)
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
        paths.qa_report.write_text(
            "# QA Report (Playwright only)\n" + section, encoding="utf-8"
        )


def validate_qa_report(paths: ProjectPaths) -> tuple[bool, str]:
    if not paths.qa_report.exists():
        return False, "qa-report.md가 존재하지 않습니다."
    text = paths.qa_report.read_text(encoding="utf-8", errors="replace")
    if "종합 판정:" not in text:
        return False, "qa-report.md에 '종합 판정:' 항목이 없습니다."
    return True, "OK"


def is_pass(paths: ProjectPaths) -> bool:
    if not paths.qa_report.exists():
        return False
    text = paths.qa_report.read_text(encoding="utf-8", errors="replace")
    return "종합 판정: PASS" in text
