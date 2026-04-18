"""5-Phase 하네스 메인 루프 — v2.3 자동 스프린트 루프."""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console

from ._logging import report_subprocess
from .agents import evaluator as ev
from .agents import planner as pl
from .checkpoint import Checkpoint, Phase
from .config import ForgeConfig, ProjectPaths
from .cost_tracker import SprintTracer, parse_cost_log
from .notifier import NotifierAdapter, get_notifier

console = Console()


# ── stdin 감지 ──────────────────────────────────────────────────────────────


def _stdin_ready(timeout: float = 2.0) -> bool:
    """크로스 플랫폼 stdin 입력 감지."""
    if platform.system() == "Windows":
        import msvcrt

        deadline = time.time() + timeout
        while time.time() < deadline:
            if msvcrt.kbhit():
                msvcrt.getch()
                return True
            time.sleep(0.1)
        return False
    import select

    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if ready:
        sys.stdin.readline()
        return True
    return False


# ── 승인 대기 ───────────────────────────────────────────────────────────────


def wait_for_approval(paths: ProjectPaths, timeout: float = 600.0) -> str:
    """알림 백엔드 신호 또는 stdin 입력 대기. 반환: resume/skip/exit/continue/revise/timeout.

    revise인 경우 .revise-signal 파일에 수정 지시문이 저장됨 (읽기는 호출부에서).
    """
    for sig in (
        paths.approval_signal,
        paths.skip_signal,
        paths.exit_signal,
        paths.continue_signal,
        paths.revise_signal,
    ):
        sig.unlink(missing_ok=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if paths.exit_signal.exists():
            return "exit"
        if paths.skip_signal.exists():
            return "skip"
        if paths.revise_signal.exists():
            return "revise"
        if paths.approval_signal.exists():
            content = paths.approval_signal.read_text(encoding="utf-8").strip()
            return content or "resume"
        if paths.continue_signal.exists():
            return "continue"
        if _stdin_ready(timeout=1.0):
            return "resume"
        time.sleep(0.3)
    return "timeout"


def wait_for_approval_or_stop(paths: ProjectPaths, timeout: float = 1800.0) -> str:
    """v2.3: /resume, /eval, /stop 시그널 대기. 반환: resume/eval/stop/timeout."""
    for sig in (
        paths.approval_signal,
        paths.skip_signal,
        paths.exit_signal,
        paths.continue_signal,
        paths.eval_signal,
        paths.stop_signal,
    ):
        sig.unlink(missing_ok=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if paths.stop_signal.exists():
            return "stop"
        if paths.exit_signal.exists():
            return "stop"
        if paths.eval_signal.exists():
            return "eval"
        if paths.approval_signal.exists():
            return "resume"
        if _stdin_ready(timeout=1.0):
            return "resume"
        time.sleep(0.3)
    return "timeout"


# ── 유틸리티 ────────────────────────────────────────────────────────────────


def _invalidate_stale_review(paths: ProjectPaths) -> None:
    """spec.md가 plan-review.md보다 새로우면 리뷰 무효화."""
    if paths.spec.exists() and paths.plan_review.exists():
        if paths.spec.stat().st_mtime > paths.plan_review.stat().st_mtime:
            paths.plan_review.unlink(missing_ok=True)


def _parse_frontmatter(paths: ProjectPaths) -> dict:
    """sprint-contract.md YAML frontmatter를 dict로 파싱."""
    if not paths.sprint_contract.exists():
        return {}
    text = paths.sprint_contract.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    fm: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


def _parse_has_next_sprint(paths: ProjectPaths) -> bool:
    """sprint-contract.md YAML frontmatter에서 has_next_sprint 읽기."""
    fm = _parse_frontmatter(paths)
    if not fm:
        return True  # frontmatter 없으면 다음 스프린트 있다고 가정
    return fm.get("has_next_sprint", "true").lower() != "false"


def _archive_sprint(sprint_num: int, paths: ProjectPaths) -> None:
    """sprint-N-done.md 아카이브 생성."""
    archive = paths.sprint_done_path(sprint_num)
    try:
        qa_content = (
            paths.qa_report.read_text(encoding="utf-8", errors="replace")
            if paths.qa_report.exists()
            else ""
        )
        archive.write_text(
            f"# Sprint {sprint_num} — DONE\n\n## qa-report.md\n\n{qa_content}",
            encoding="utf-8",
        )
    except OSError:
        pass


def _extract_checked_items(paths: ProjectPaths) -> list[str]:
    """sprint-contract.md에서 [x] 체크된 항목 목록 추출."""
    if not paths.sprint_contract.exists():
        return []
    text = paths.sprint_contract.read_text(encoding="utf-8", errors="replace")
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- [x]") or stripped.startswith("- [X]"):
            items.append(stripped[5:].strip().split("—")[0].strip())
    return items


def _extract_next_sprint_preview(paths: ProjectPaths) -> str:
    """sprint-contract.md frontmatter에서 next_sprint_preview 추출."""
    if not paths.sprint_contract.exists():
        return ""
    text = paths.sprint_contract.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return ""
    fm_text = m.group(1)
    # next_sprint_preview: | 형식이거나 한 줄 형식
    preview_match = re.search(r"next_sprint_preview:\s*\|?\s*\n((?:\s+.+\n?)*)", fm_text)
    if preview_match:
        return preview_match.group(1).strip()
    # 한 줄 형식
    preview_match = re.search(r"next_sprint_preview:\s*(.+)", fm_text)
    if preview_match:
        val = preview_match.group(1).strip().strip('"').strip("'")
        return val
    return ""


def _build_sprint_history(paths: ProjectPaths) -> str:
    """sprint-N-done.md 목록에서 스프린트별 히스토리 문자열 생성."""
    if not paths.artifacts.exists():
        return ""
    pattern = re.compile(r"sprint-(\d+)-done\.md")
    done_files = sorted(
        [p for p in paths.artifacts.iterdir() if pattern.match(p.name)],
        key=lambda p: int(pattern.match(p.name).group(1)),
    )
    if not done_files:
        return ""
    lines = []
    for f in done_files:
        num = pattern.match(f.name).group(1)
        lines.append(f"  ✅ Sprint {num} PASS")
    return "\n".join(lines)


_SCORE_RE = re.compile(r"([\w\s가-힣]+):\s*(\d+)/10")


def _extract_scores_from_qa_report(paths: ProjectPaths) -> dict[str, int]:
    """qa-report.md에서 'X: N/10' 패턴 추출."""
    scores: dict[str, int] = {}
    if not paths.qa_report.exists():
        return scores
    text = paths.qa_report.read_text(encoding="utf-8", errors="replace")
    for m in _SCORE_RE.finditer(text):
        scores[m.group(1).strip()] = int(m.group(2))
    return scores


# ── 알림 헬퍼 (v2.3) ───────────────────────────────────────────────────────


def _notify_pass_with_next(
    notifier: NotifierAdapter,
    tracer: SprintTracer,
    sprint_num: int,
    paths: ProjectPaths,
) -> None:
    """PASS + 다음 스프린트 알림 (완료 내용 + 다음 계획 포함)."""
    scores = _extract_scores_from_qa_report(paths)
    totals = tracer.sprint_totals()
    total_mins = parse_cost_log(paths.cost_log)
    score_lines = "\n".join(f"• {k}: {v}/10" for k, v in scores.items())
    dur = totals["duration_seconds"] / 60

    # 완료 내용 (체크박스)
    checked = _extract_checked_items(paths)
    completed_section = ""
    if checked:
        completed_lines = "\n".join(f"• {item}" for item in checked)
        completed_section = f"\n완료 내용:\n{completed_lines}\n"

    # 다음 스프린트 정보 (frontmatter)
    fm = _parse_frontmatter(paths)
    next_preview = _extract_next_sprint_preview(paths)
    estimated = fm.get("estimated_remaining_sprints", "?")
    next_section = ""
    if next_preview:
        next_section = (
            f"\n📋 Sprint {sprint_num + 1} 계획\n\n"
            f"예정 작업:\n{next_preview}\n\n"
            f"남은 스프린트: {estimated}개\n"
        )

    msg = (
        f"Sprint {sprint_num} 완료\n\n"
        f"점수:\n{score_lines}\n"
        f"{completed_section}\n"
        f"─────────────────\n\n"
        f"📊 비용\n"
        f"• 이번 스프린트: {dur:.0f}분 | in {totals['tokens_input']:,} / out {totals['tokens_output']:,}\n"
        f"• 누적: {total_mins:.0f}분\n\n"
        f"─────────────────\n"
        f"{next_section}\n"
        f"/resume — 계속 진행\n"
        f"/stop — 여기서 중단\n"
        f"/status — 상세 상태"
    )
    notifier.notify(
        "sprint_pass_next", msg,
        file_path=paths.qa_report, project_name=paths.project_name,
        buttons=[["/resume", "/stop"], ["/status"]],
    )


def _notify_fail_with_options(
    notifier: NotifierAdapter,
    config: ForgeConfig,
    tracer: SprintTracer,
    sprint_num: int,
    paths: ProjectPaths,
    consecutive: int,
) -> None:
    """FAIL + 선택지 알림."""
    scores = _extract_scores_from_qa_report(paths)
    totals = tracer.sprint_totals()
    total_mins = parse_cost_log(paths.cost_log)
    score_lines = "\n".join(f"• {k}: {v}/10" for k, v in scores.items())
    dur = totals["duration_seconds"] / 60
    consecutive_line = (
        f"⚠️ 연속 FAIL: {consecutive}/{config.max_consecutive_fails}"
        if config.max_consecutive_fails > 0
        else f"⚠️ 연속 FAIL: {consecutive}회 (자동 중단 임계 없음 — 수동 /stop 필요)"
    )
    msg = (
        f"Sprint {sprint_num} FAILED\n\n"
        f"점수:\n{score_lines}\n\n"
        f"─────────────────\n\n"
        f"📊 비용\n"
        f"• 이번 스프린트: {dur:.0f}분 | in {totals['tokens_input']:,} / out {totals['tokens_output']:,}\n"
        f"• 누적: {total_mins:.0f}분\n\n"
        f"{consecutive_line}\n\n"
        f"─────────────────\n\n"
        f"/resume — Generator 재진입\n"
        f"/eval — Evaluator 재실행\n"
        f"/stop — 여기서 중단"
    )
    notifier.notify(
        "qa_fail", msg,
        file_path=paths.qa_report, project_name=paths.project_name,
        buttons=[["/resume", "/eval"], ["/stop"]],
    )


def _notify_project_complete(
    notifier: NotifierAdapter,
    tracer: SprintTracer,
    paths: ProjectPaths,
    total_sprints: int,
) -> None:
    """프로젝트 완료 알림 (스프린트별 히스토리 + 캐시 히트 포함)."""
    totals = tracer.sprint_totals()
    total_mins = parse_cost_log(paths.cost_log)

    # 스프린트별 히스토리
    history = _build_sprint_history(paths)
    history_section = f"\n전체 결과:\n{history}\n" if history else ""

    msg = (
        f"프로젝트 완료!\n\n"
        f"총 스프린트: {total_sprints}개\n"
        f"{history_section}\n"
        f"📊 전체 비용\n"
        f"• 총 소요 시간: {total_mins:.0f}분\n"
        f"• 총 사용 토큰:\n"
        f"  - 입력: {totals['tokens_input']:,}\n"
        f"  - 출력: {totals['tokens_output']:,}\n"
        f"  - 캐시 히트: {totals['tokens_cache']:,}\n\n"
        f"spec.md의 모든 스프린트가 구현 완료되었습니다.\n"
        f"추가 작업이 필요하면 spec.md에 새 스프린트 추가 후 forge run."
    )
    notifier.notify("project_complete", msg, project_name=paths.project_name)


# ── 메인 사이클 ─────────────────────────────────────────────────────────────


def run_cycle(
    request: Optional[str] = None,
    plan_file: Optional[Path] = None,
    config: Optional[ForgeConfig] = None,
    project_root: Optional[Path] = None,
    from_phase: Optional[Phase] = None,
    single_sprint: bool = False,
    max_sprints: Optional[int] = None,
) -> int:
    """자동 스프린트 루프.

    기본 동작 (single_sprint=False): 프로젝트 완료까지 스프린트 자동 진행.
    v2.2 호환 (single_sprint=True): 1 스프린트만 실행 후 종료.
    """
    project_root = Path(project_root or Path.cwd()).resolve()
    config = config or ForgeConfig.load(project_root)
    paths = ProjectPaths(project_root)
    paths.ensure_artifacts()

    if plan_file and not paths.spec.exists():
        plan = Path(plan_file)
        if plan.exists():
            paths.spec.write_text(
                plan.read_text(encoding="utf-8"), encoding="utf-8"
            )

    cp = Checkpoint.load(paths.checkpoint_file)

    # v2.2: --from 처리
    if from_phase is not None:
        target_prev = Phase(from_phase - 1) if from_phase > Phase.NONE else Phase.NONE
        cp = Checkpoint(phase=target_prev, detail=f"forced from {from_phase.name}")
        cp.save(paths.checkpoint_file)

    notifier = get_notifier(config, paths)
    notifier.start()

    exit_code = 0
    try:
        _invalidate_stale_review(paths)

        # ── Phase 1: Planning (프로젝트당 1회) ──
        if cp.should_run(Phase.PLANNING):
            sprint_num = paths.current_sprint()
            tracer = SprintTracer(config, sprint_num, paths.project_name, paths.cost_log)
            cp.advance(Phase.PLANNING, "planner running")
            cp.save(paths.checkpoint_file)
            # specs/ 변경 감지를 위해 실행 전 목록 기록
            specs_before = set(paths.specs.glob("*.md")) if paths.specs.exists() else set()

            with tracer.span("planner") as info:
                if not paths.spec.exists():
                    if not request:
                        notifier.notify("error", "spec.md가 없고 요청도 없습니다.", project_name=paths.project_name)
                        return 2
                    result = pl.run_generate(request, config, paths)
                    info["stdout"] = result.stdout or ""
                    report_subprocess(result, "planner(generate)", console)
                else:
                    result = pl.run_review(config, paths)
                    info["stdout"] = result.stdout or ""
                    report_subprocess(result, "planner(review)", console)

            # Planner가 생성한 새 specs/*.md 감지 + Telegram 전송
            specs_after = set(paths.specs.glob("*.md")) if paths.specs.exists() else set()
            new_specs = specs_after - specs_before
            for spec_file in sorted(new_specs):
                notifier.notify(
                    "spec_detail",
                    f"도메인 상세 스펙: {spec_file.name}",
                    file_path=spec_file, project_name=paths.project_name,
                )

            status = pl.plan_review_status(paths)
            plan_buttons = (
                [["/resume", "/revise"], ["/exit"]]
                if status == "READY"
                else [["/skip", "/resume"], ["/revise", "/exit"]]
            )
            notifier.notify(
                "planner_done" if status == "READY" else "plan_revision",
                f"plan-review.md 상태: {status}",
                file_path=paths.plan_review if paths.plan_review.exists() else paths.spec,
                project_name=paths.project_name,
                buttons=plan_buttons,
            )

            # Planner 승인/수정 대기 — revise 요청이 오면 수정 모드로 재진입
            while True:
                signal = wait_for_approval(paths, timeout=config.approval_timeout_seconds)
                if signal == "exit":
                    cp.advance(Phase.PLANNING, "halted by user after planning")
                    cp.save(paths.checkpoint_file)
                    return 0
                if signal == "revise":
                    # 사용자 수정 지시를 읽고 Planner Mode D 호출
                    try:
                        revise_text = paths.revise_signal.read_text(encoding="utf-8").strip()
                    except OSError:
                        revise_text = ""
                    paths.revise_signal.unlink(missing_ok=True)
                    if not revise_text:
                        console.print("[yellow]revise 신호는 있으나 지시문이 비어있음 — 무시[/yellow]")
                        continue
                    console.print(f"[cyan]Planner 수정 모드 진입: {revise_text[:120]}[/cyan]")
                    with tracer.span("planner-revise") as info:
                        result = pl.run_revise(revise_text, config, paths)
                        info["stdout"] = result.stdout or ""
                        report_subprocess(result, "planner(revise)", console)
                    # 수정 결과 다시 알림
                    status = pl.plan_review_status(paths)
                    plan_buttons = (
                        [["/resume", "/revise"], ["/exit"]]
                        if status == "READY"
                        else [["/skip", "/resume"], ["/revise", "/exit"]]
                    )
                    notifier.notify(
                        "planner_done" if status == "READY" else "plan_revision",
                        f"(수정 반영됨) plan-review.md 상태: {status}",
                        file_path=paths.plan_review if paths.plan_review.exists() else paths.spec,
                        project_name=paths.project_name,
                        buttons=plan_buttons,
                    )
                    continue  # 다시 대기 — 사용자가 추가 revise 또는 resume/exit 선택
                # resume / skip / continue / timeout — 루프 탈출
                break

            # resume/skip: 진행. timeout/continue: 진행하지 않고 이번 사이클 종료.
            if signal not in ("resume", "skip"):
                return 0

            cp.advance(Phase.PLANNING_DONE, "planning approved")
            cp.save(paths.checkpoint_file)
            tracer.finalize()

        # ── 스프린트 자동 루프 (v2.3 핵심) ──
        sprints_run = 0
        consecutive_fails = 0

        while True:
            sprint_num = paths.current_sprint()
            sprint_tracer = SprintTracer(config, sprint_num, paths.project_name, paths.cost_log)

            # 안전장치 체크
            effective_max = max_sprints if max_sprints is not None else config.max_total_sprints
            if sprints_run >= effective_max:
                notifier.notify("auto_stop", f"최대 스프린트 수 {effective_max} 도달 — 자동 중단", project_name=paths.project_name)
                break

            if config.max_consecutive_fails > 0 and consecutive_fails >= config.max_consecutive_fails:
                notifier.notify("auto_stop", f"{config.max_consecutive_fails}회 연속 FAIL — 자동 중단", file_path=paths.qa_report, project_name=paths.project_name)
                break

            total_mins = parse_cost_log(paths.cost_log)
            if total_mins > config.max_total_minutes:
                notifier.notify("budget_exceeded", f"누적 {total_mins:.0f}분 > {config.max_total_minutes}분 — 자동 중단", file_path=paths.cost_log, project_name=paths.project_name)
                break

            # Phase 2: Sprint Contract
            if cp.should_run(Phase.CONTRACT):
                cp.advance(Phase.CONTRACT, "contract generating")
                cp.save(paths.checkpoint_file)
                with sprint_tracer.span("contract") as info:
                    result = pl.run_contract(sprint_num, config, paths)
                    info["stdout"] = result.stdout or ""
                    report_subprocess(result, f"planner(contract sprint-{sprint_num})", console)

                # 첫 Sprint Contract만 승인 대기
                if sprint_num == 1:
                    notifier.notify(
                        "sprint_contract",
                        f"Sprint {sprint_num} contract 생성됨.",
                        file_path=paths.sprint_contract if paths.sprint_contract.exists() else None,
                        project_name=paths.project_name,
                        buttons=[["/resume", "/exit"]],
                    )
                    signal = wait_for_approval(paths, timeout=config.approval_timeout_seconds)
                    if signal == "exit":
                        return 0

                cp.advance(Phase.CONTRACT_DONE, "contract approved")
                cp.save(paths.checkpoint_file)

            # Phase 3: Generator (claude -p, 자동 실행)
            if cp.should_run(Phase.GENERATING):
                cp.advance(Phase.GENERATING, "generator running")
                cp.save(paths.checkpoint_file)
                notifier.notify("generator_start", f"Sprint {sprint_num} Generator 세션 시작.", project_name=paths.project_name)
                with sprint_tracer.span("generator", mode="claude-p") as info:
                    try:
                        claude_cli = shutil.which("claude") or "claude"
                        initial_prompt = (
                            f"Sprint {sprint_num} 세션을 시작하라. "
                            f"CLAUDE.md의 세션 시작 절차를 따르되, "
                            f"artifacts/qa-report.md가 존재하면 FAIL 항목부터 우선 수정하라. "
                            f"그 외에는 artifacts/sprint-contract.md 체크박스 순서대로 구현하고, "
                            f"각 기능 완성 시 커밋 + 체크박스 `[x]`. "
                            f"커밋 메시지는 짧고 직관적인 영어로, prefix는 `feat:` / `fix:` / `refactor:` 세 가지만. "
                            f"예: `feat: add watcher debounce`. Co-Authored-By 서명 금지. "
                            f"중요 결정은 artifacts/decisions/decision-NNN.md, "
                            f"세션 종료 시 artifacts/progress-log.md 최상단에 결과 블록 추가."
                        )
                        result = subprocess.run(
                            [claude_cli, "-p",
                             "--agent", "generator",
                             "--max-turns", str(config.generator_max_turns),
                             "--permission-mode", "bypassPermissions",
                             initial_prompt],
                            cwd=str(paths.project_root),
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            timeout=config.max_generator_minutes * 60,
                        )
                        info["stdout"] = result.stdout or ""
                        report_subprocess(result, f"generator sprint-{sprint_num}", console)
                    except KeyboardInterrupt:
                        pass
                    except subprocess.TimeoutExpired:
                        notifier.notify("warning", f"Generator 시간 초과 ({config.max_generator_minutes}분).", project_name=paths.project_name)
                    except FileNotFoundError:
                        notifier.notify("error", "claude CLI를 찾을 수 없습니다.", project_name=paths.project_name)
                        return 3
                notifier.notify(
                    "generator_end", "Generator 세션 종료.",
                    file_path=paths.progress_log if paths.progress_log.exists() else None,
                    project_name=paths.project_name,
                )
                cp.advance(Phase.GENERATING_DONE, "generator finished")
                cp.save(paths.checkpoint_file)

            # Phase 4: Evaluator
            if cp.should_run(Phase.EVALUATING):
                cp.advance(Phase.EVALUATING, "evaluator running")
                cp.save(paths.checkpoint_file)
                try:
                    with sprint_tracer.span("evaluator") as info:
                        result = ev.run_evaluate(config, paths)
                        info["stdout"] = result.stdout or ""
                        report_subprocess(result, f"evaluator sprint-{sprint_num}", console)
                except Exception as e:
                    notifier.notify("error", f"Evaluator 실행 중 예외: {e}", project_name=paths.project_name)
                cp.advance(Phase.EVALUATING_DONE, "evaluation complete")
                cp.save(paths.checkpoint_file)

            # Phase 5: 결과 판단 — qa-report.md 유효성 검증
            while True:
                ok, reason = ev.validate_qa_report(paths)
                if ok:
                    break
                # 무효한 qa-report (파일 없음 또는 "종합 판정:" 누락)
                # 사용자가 /eval로 재실행하거나 /stop으로 중단할 수 있게 알림
                notifier.notify(
                    "warning",
                    f"qa-report.md 검증 실패: {reason}\n\n"
                    f"Evaluator가 판정을 완성하지 못했습니다.\n"
                    f"/eval — Evaluator 재실행 (예: FORGE_EVALUATOR_MAX_TURNS 증가 후)\n"
                    f"/stop — 여기서 중단",
                    file_path=paths.qa_report if paths.qa_report.exists() else None,
                    project_name=paths.project_name,
                    buttons=[["/eval", "/stop"]],
                )
                decision = wait_for_approval_or_stop(paths, timeout=config.approval_timeout_seconds)
                if decision in ("stop", "timeout"):
                    exit_code = 4
                    break
                if decision == "eval":
                    cp.advance(Phase.EVALUATING, "re-evaluating after validation fail")
                    cp.save(paths.checkpoint_file)
                    try:
                        with sprint_tracer.span("evaluator-rerun") as info:
                            result = ev.run_evaluate(config, paths)
                            info["stdout"] = result.stdout or ""
                            report_subprocess(result, f"evaluator-rerun sprint-{sprint_num}", console)
                    except Exception as e:
                        notifier.notify("error", f"Evaluator 재실행 중 예외: {e}", project_name=paths.project_name)
                    cp.advance(Phase.EVALUATING_DONE, "re-evaluation complete")
                    cp.save(paths.checkpoint_file)
                    continue  # 다시 검증
                # resume/skip 등 기타 — 이번 사이클 종료
                exit_code = 4
                break
            if exit_code == 4:
                break

            if ev.is_pass(paths):
                consecutive_fails = 0
                _archive_sprint(sprint_num, paths)
                has_next = _parse_has_next_sprint(paths)

                if not has_next:
                    _notify_project_complete(notifier, sprint_tracer, paths, sprint_num)
                    cp.advance(Phase.NONE, f"project complete at sprint-{sprint_num}")
                    cp.save(paths.checkpoint_file)
                    break

                _notify_pass_with_next(notifier, sprint_tracer, sprint_num, paths)

                if single_sprint:
                    cp.advance(Phase.NONE, f"sprint-{sprint_num} done (single-sprint mode)")
                    cp.save(paths.checkpoint_file)
                    break

                decision = wait_for_approval_or_stop(paths, timeout=config.approval_timeout_seconds)
                if decision == "stop":
                    break

                # 다음 스프린트 준비: 체크포인트 리셋
                cp.advance(Phase.NONE, f"sprint-{sprint_num} done, continuing")
                cp.save(paths.checkpoint_file)
                # Checkpoint 리로드
                cp = Checkpoint.load(paths.checkpoint_file)

            else:  # FAIL
                consecutive_fails += 1

                # v2.2: 체크포인트 CONTRACT_DONE으로 되돌림
                cp = Checkpoint(phase=Phase.CONTRACT_DONE, detail=f"sprint-{sprint_num} FAIL, reset to contract_done")
                cp.save(paths.checkpoint_file)

                _notify_fail_with_options(notifier, config, sprint_tracer, sprint_num, paths, consecutive_fails)

                if single_sprint:
                    exit_code = 1
                    break

                decision = wait_for_approval_or_stop(paths, timeout=config.approval_timeout_seconds)
                if decision == "stop":
                    break
                elif decision == "eval":
                    # Evaluator만 재실행
                    cp.advance(Phase.EVALUATING, "re-evaluating after FAIL")
                    cp.save(paths.checkpoint_file)
                    try:
                        with sprint_tracer.span("evaluator-rerun") as info:
                            result = ev.run_evaluate(config, paths)
                            report_subprocess(result, f"evaluator-rerun sprint-{sprint_num}", console)
                            info["stdout"] = result.stdout or ""
                    except Exception as e:
                        notifier.notify("error", f"Evaluator 재실행 중 예외: {e}", project_name=paths.project_name)
                    cp.advance(Phase.EVALUATING_DONE, "re-evaluation complete")
                    cp.save(paths.checkpoint_file)
                    continue  # Phase 5로 돌아가 다시 판정
                # "resume": Generator 재진입 (루프 계속 — cp는 CONTRACT_DONE)

            sprints_run += 1
            sprint_tracer.finalize()

    finally:
        notifier.stop()

    return exit_code
