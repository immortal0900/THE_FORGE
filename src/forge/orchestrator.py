"""5-Phase 하네스 메인 루프 — v2.3 자동 스프린트 루프."""

from __future__ import annotations

import platform
import re
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console

from ._logging import report_subprocess
from .agents import evaluator as ev
from .agents import planner as pl
from .agents.runner import run_agent_sync
from .checkpoint import Checkpoint, Phase
from .config import ForgeConfig, ProjectPaths
from .cost_tracker import SprintTracer, parse_cost_log
from .notifier import NotifierAdapter, get_notifier

console = Console()


# ── stdin 감지 ──────────────────────────────────────────────────────────────


def _stdin_ready(timeout: float = 2.0) -> bool:
    """크로스 플랫폼 stdin 입력 감지.

    **Enter/Space 키만 resume으로 해석**한다. 아무 키나 resume으로 잡으면
    Slack 중심 워크플로에서 Alt+Tab·포커스 전환 시 실수로 진행되는 사고가
    생긴다(실제 재현됨: Planning 게이트 9초 만에 탈출 사건).

    비활성화: 환경변수 FORGE_DISABLE_STDIN=1 설정 시 항상 False 반환.
    """
    import os
    if os.environ.get("FORGE_DISABLE_STDIN", "").strip() in ("1", "true", "True", "TRUE"):
        return False

    if platform.system() == "Windows":
        import msvcrt

        deadline = time.time() + timeout
        while time.time() < deadline:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                # Enter(\r or \n) 또는 Space(0x20)만 의도적 승인으로 해석
                if key in (b"\r", b"\n", b" "):
                    return True
                # 다른 키는 읽고 버림 (Alt+Tab, 방향키 등 우발적 입력 차단)
                continue
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
    """v2.3+: /resume, /eval, /skip, /stop 시그널 대기.

    반환: resume/eval/skip/stop/timeout
    - skip: FAIL 상태에서 "이 Sprint 완료 처리하고 다음 Sprint로" (강제 아카이브)
    """
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
        if paths.skip_signal.exists():
            return "skip"
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


def _make_on_question(
    notifier: NotifierAdapter,
    paths: ProjectPaths,
    config: ForgeConfig,
):
    """큰 그림 1: ASK_USER 콜백 팩토리.

    LLM이 stdout에 `{"type":"ask_user", ...}` JSON을 출력하면 runner가 이 콜백을
    호출한다. 콜백은:
      1) Slack 옵션 카드를 thread에 reply로 전송 (SlackNotifier일 때만)
      2) paths.answer_signal_for(qid) 파일이 생길 때까지 폴링
      3) 파일 내용(option_id)을 답으로 반환

    토대 1에서는 30분 임시 타임아웃 (응답 없으면 추천안 자동 채택). 큰 그림 1
    후속 8번 todo (무기한 백그라운드 대기 + 6h heartbeat)에서 본격 무기한 대기.
    """
    import asyncio as _asyncio

    async def _on_question(ask: dict) -> str:
        from .notifier.slack.adapter import SlackNotifier

        qid = (ask.get("qid") or "").strip()
        fallback = (ask.get("recommend") or "").strip()
        if not qid:
            return fallback

        if isinstance(notifier, SlackNotifier):
            notifier.send_question_card(ask, project_name=paths.project_name)
        else:
            console.print(
                f"[yellow]ASK_USER qid={qid} — Slack notifier 아님, 추천안 '{fallback}' 자동 채택[/yellow]"
            )
            return fallback

        answer_file = paths.answer_signal_for(qid)
        start = time.time()
        timeout = 1800  # 30분 임시. 토대 8에서 무기한 + heartbeat로 교체.
        while not answer_file.exists():
            if paths.stop_signal.exists() or paths.exit_signal.exists():
                return fallback
            if time.time() - start > timeout:
                console.print(
                    f"[yellow]ASK_USER qid={qid} {timeout}s 타임아웃 — 추천안 '{fallback}' 자동 채택[/yellow]"
                )
                return fallback
            await _asyncio.sleep(2)

        try:
            answer = answer_file.read_text(encoding="utf-8").strip()
            answer_file.unlink(missing_ok=True)
            return answer or fallback
        except OSError:
            return fallback

    return _on_question


def _try_send_verdict_card(
    notifier: NotifierAdapter,
    paths: ProjectPaths,
    *,
    recommendation: str = "",
    recommendation_reason: str = "",
    cost_estimate: str = "",
    buttons: Optional[list[list[str]]] = None,
) -> None:
    """큰 그림 2: Slack notifier일 때만 Verdict Card를 thread에 reply로 첨부.

    qa-report.md에 Axiom Verdicts 표가 없으면 자체 no-op (False 반환).
    Telegram 등 다른 notifier는 기존 첨부 폴백 그대로.
    """
    # 함수 지역 import로 순환 / hook 제거 우회
    from .notifier.slack.adapter import SlackNotifier

    if not isinstance(notifier, SlackNotifier):
        return
    notifier.send_verdict_card(
        paths.qa_report,
        recommendation=recommendation,
        recommendation_reason=recommendation_reason,
        cost_estimate=cost_estimate,
        buttons=buttons,
        project_name=paths.project_name,
    )


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
    # 큰 그림 2: Axiom Verdicts 표가 있으면 Verdict Card도 thread에 reply.
    _try_send_verdict_card(
        notifier,
        paths,
        recommendation="PASS — 다음 sprint 진행",
        recommendation_reason="모든 axiom verdict 통과 (또는 critical PARTIAL 없음)",
        cost_estimate=f"이번 sprint {dur:.0f}분 / 누적 {total_mins:.0f}분",
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
        f"/resume — Generator 재진입 (FAIL 수정)\n"
        f"/eval — Evaluator 재실행\n"
        f"/skip — 이 Sprint 결함 채로 완료 처리 + 다음 Sprint로\n"
        f"/stop — 여기서 중단"
    )
    notifier.notify(
        "qa_fail", msg,
        file_path=paths.qa_report, project_name=paths.project_name,
        buttons=[["/resume", "/eval"], ["/skip", "/stop"]],
    )
    # 큰 그림 2: Axiom Verdicts 표가 있으면 어느 axiom이 깨졌는지 카드로 노출.
    _try_send_verdict_card(
        notifier,
        paths,
        recommendation="FAIL — 위 axiom 행의 recommend_action 참고",
        recommendation_reason="critical axiom PARTIAL/MISSING 또는 점수 미달",
        cost_estimate=f"이번 sprint {dur:.0f}분 / 누적 {total_mins:.0f}분",
        buttons=[["/resume", "/eval"], ["/skip", "/stop"]],
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
        f"마지막 스프린트(Sprint {total_sprints}) qa-report.md를 첨부합니다.\n"
        f"전체 히스토리는 artifacts/sprint-{{N}}-done.md에 아카이브됨.\n\n"
        f"spec.md의 모든 스프린트가 구현 완료되었습니다.\n"
        f"추가 작업이 필요하면 spec.md에 새 스프린트 추가 후 forge run."
    )
    # 마지막 스프린트의 qa-report.md를 첨부 (아직 _archive_sprint로 sprint-N-done.md에 복사되긴 했지만
    # 원본 artifacts/qa-report.md 파일도 그대로 남아있음)
    notifier.notify(
        "project_complete", msg,
        file_path=paths.qa_report if paths.qa_report.exists() else None,
        project_name=paths.project_name,
    )


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
    # Langfuse flush 보장을 위한 현재 활성 tracer 레퍼런스 (중단 시에도 finalize)
    _active_tracers: list = []
    try:
        _invalidate_stale_review(paths)

        # ── Phase 1: Planning (프로젝트당 1회) ──
        if cp.should_run(Phase.PLANNING):
            # 토대 3: 사용자가 제공한 본질(essence_axioms) 로드. 없으면 None → 강제 X.
            # docs/plan-judgment-velocity.md 토대 3 참조.
            from .judgment import inject_essence_into_spec, load_essence_for_project

            essence = load_essence_for_project(
                paths.project_root,
                hint_path=config.essence_source_path or None,
            )
            if essence:
                console.print(
                    f"[cyan]essence 로드: {essence.source} ({len(essence.axioms)} axioms)[/cyan]"
                )

            sprint_num = paths.current_sprint()
            tracer = SprintTracer(config, sprint_num, paths.project_name, paths.cost_log)
            _active_tracers.append(tracer)
            cp.advance(Phase.PLANNING, "planner running")
            cp.save(paths.checkpoint_file)
            # specs/ 변경 감지를 위해 실행 전 목록 기록
            specs_before = set(paths.specs.glob("*.md")) if paths.specs.exists() else set()

            # 큰 그림 1: ASK_USER 콜백 (planner-spec / planner-contract 자유 질문 가능)
            on_question_cb = _make_on_question(notifier, paths, config)

            with tracer.span("planner") as info:
                if not paths.spec.exists():
                    if not request:
                        notifier.notify("error", "spec.md가 없고 요청도 없습니다.", project_name=paths.project_name)
                        return 2
                    info["input"] = f"[planner/generate] user_request:\n{request}"
                    result = pl.run_generate(
                        request, config, paths,
                        essence=essence,
                        on_question=on_question_cb,
                    )
                    info["stdout"] = result.stdout or ""
                    report_subprocess(result, "planner(generate)", console)
                else:
                    info["input"] = "[planner/review] reviewing existing spec.md"
                    result = pl.run_review(
                        config, paths,
                        essence=essence,
                        on_question=on_question_cb,
                    )
                    info["stdout"] = result.stdout or ""
                    report_subprocess(result, "planner(review)", console)

            # 토대 3: planner 종료 후 spec.md frontmatter에 essence 인용 (있을 때만).
            if essence and paths.spec.exists():
                if inject_essence_into_spec(paths.spec, essence):
                    console.print(
                        f"[cyan]spec.md frontmatter에 essence 인용 박음 "
                        f"({len(essence.axioms)} axioms)[/cyan]"
                    )

            cp.note("planner completed, awaiting plan review approval")
            cp.save(paths.checkpoint_file)

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
            # spec.md를 먼저 보내 사용자가 본문을 확인하고 plan-review와 버튼으로 결정하게 한다
            if paths.spec.exists():
                notifier.notify(
                    "spec_detail",
                    "spec.md (Planner가 작성한 기획 본문)",
                    file_path=paths.spec,
                    project_name=paths.project_name,
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
                    cp.note(f"planner Mode D running: {revise_text[:80]}")
                    cp.save(paths.checkpoint_file)
                    # spec.md mtime을 기록해 Mode D가 실제로 수정했는지 검증
                    spec_mtime_before = (
                        paths.spec.stat().st_mtime if paths.spec.exists() else 0
                    )
                    with tracer.span("planner-revise") as info:
                        info["input"] = f"[planner/revise] user_directive:\n{revise_text}"
                        result = pl.run_revise(revise_text, config, paths)
                        info["stdout"] = result.stdout or ""
                        report_subprocess(result, "planner(revise)", console)
                    # Mode D 실제 수정 여부 검증
                    spec_mtime_after = (
                        paths.spec.stat().st_mtime if paths.spec.exists() else 0
                    )
                    if spec_mtime_before != spec_mtime_after:
                        cp.note("revision applied, awaiting re-review approval")
                    else:
                        cp.note("revision skipped (Claude avoided Edit), awaiting user decision")
                    cp.save(paths.checkpoint_file)
                    if spec_mtime_before == spec_mtime_after:
                        console.print(
                            "[red]⚠ Mode D가 spec.md를 수정하지 않고 종료됨 "
                            "— Claude가 '질문 모드'로 회피했을 가능성. "
                            "더 구체적인 지시문으로 /revise 재시도 권장.[/red]"
                        )
                        notifier.notify(
                            "warning",
                            "⚠ Mode D 실행됐으나 spec.md가 변경되지 않았습니다. "
                            "Claude가 추가 지시를 원하거나 지시문이 모호해 회피한 상태. "
                            "더 구체적인 수정 지시로 `/revise`를 다시 눌러주세요.",
                            project_name=paths.project_name,
                        )
                    # 수정 결과 다시 알림 — 수정된 spec.md와 plan-review.md를 둘 다 전송
                    status = pl.plan_review_status(paths)
                    plan_buttons = (
                        [["/resume", "/revise"], ["/exit"]]
                        if status == "READY"
                        else [["/skip", "/resume"], ["/revise", "/exit"]]
                    )
                    if paths.spec.exists():
                        notifier.notify(
                            "spec_detail",
                            "(수정 반영됨) spec.md",
                            file_path=paths.spec,
                            project_name=paths.project_name,
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
            _active_tracers.append(sprint_tracer)

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
                # 토대 3: contract는 sprint마다 반복되므로 essence를 매번 새로 로드 (사용자가
                # docs/essence.md를 sprint 도중 수정했을 수 있음).
                from .judgment import load_essence_for_project as _load_essence

                sprint_essence = _load_essence(
                    paths.project_root,
                    hint_path=config.essence_source_path or None,
                )
                cp.advance(Phase.CONTRACT, f"contract generating (sprint {sprint_num})")
                cp.save(paths.checkpoint_file)
                # 큰 그림 1: contract도 sprint 범위 결정 시 ASK_USER 가능
                sprint_on_question = _make_on_question(notifier, paths, config)
                with sprint_tracer.span("contract") as info:
                    info["input"] = f"[planner/contract] Sprint {sprint_num} contract generation"
                    result = pl.run_contract(
                        sprint_num, config, paths,
                        essence=sprint_essence,
                        on_question=sprint_on_question,
                    )
                    info["stdout"] = result.stdout or ""
                    report_subprocess(result, f"planner(contract sprint-{sprint_num})", console)

                # 첫 Sprint Contract만 승인 대기. revise 요청 시 Mode D로 되돌려 spec 수정 가능
                if sprint_num == 1:
                    cp.note(f"contract generated, awaiting sprint {sprint_num} approval")
                    cp.save(paths.checkpoint_file)
                    notifier.notify(
                        "sprint_contract",
                        f"Sprint {sprint_num} contract 생성됨.",
                        file_path=paths.sprint_contract if paths.sprint_contract.exists() else None,
                        project_name=paths.project_name,
                        buttons=[["/resume", "/revise"], ["/exit"]],
                    )
                    # revise 수용 루프 — Planning 게이트와 동일한 원리
                    while True:
                        signal = wait_for_approval(paths, timeout=config.approval_timeout_seconds)
                        if signal == "exit":
                            return 0
                        if signal == "revise":
                            try:
                                revise_text = paths.revise_signal.read_text(encoding="utf-8").strip()
                            except OSError:
                                revise_text = ""
                            paths.revise_signal.unlink(missing_ok=True)
                            if not revise_text:
                                console.print("[yellow]revise 신호는 있으나 지시문이 비어있음 — 무시[/yellow]")
                                continue
                            console.print(
                                f"[cyan]Contract 게이트에서 Planner Mode D 진입: {revise_text[:120]}[/cyan]"
                            )
                            cp.note(f"Mode D running (from contract gate): {revise_text[:80]}")
                            cp.save(paths.checkpoint_file)
                            spec_mtime_before = (
                                paths.spec.stat().st_mtime if paths.spec.exists() else 0
                            )
                            with sprint_tracer.span("planner-revise") as info:
                                info["input"] = (
                                    f"[planner/revise from contract gate] user_directive:\n{revise_text}"
                                )
                                result = pl.run_revise(revise_text, config, paths)
                                info["stdout"] = result.stdout or ""
                                report_subprocess(result, "planner(revise from contract)", console)
                            spec_mtime_after = (
                                paths.spec.stat().st_mtime if paths.spec.exists() else 0
                            )
                            if spec_mtime_before != spec_mtime_after:
                                # spec 바뀌었으면 기존 sprint-contract.md 폐기하고 Contract 재생성
                                console.print(
                                    "[cyan]spec.md 수정됨 → sprint-contract.md 폐기 후 Contract 재생성[/cyan]"
                                )
                                paths.sprint_contract.unlink(missing_ok=True)
                                cp.note("revision applied, regenerating contract")
                                cp.save(paths.checkpoint_file)
                                # Contract 재생성
                                with sprint_tracer.span("contract") as info:
                                    info["input"] = (
                                        f"[planner/contract] Sprint {sprint_num} contract regen after revise"
                                    )
                                    result = pl.run_contract(sprint_num, config, paths)
                                    info["stdout"] = result.stdout or ""
                                    report_subprocess(
                                        result, f"planner(contract regen sprint-{sprint_num})", console
                                    )
                            else:
                                console.print(
                                    "[red]⚠ Mode D가 spec.md를 수정하지 않음 — Contract 재생성 스킵[/red]"
                                )
                                notifier.notify(
                                    "warning",
                                    "⚠ Mode D 실행됐으나 spec.md 미변경 — 더 구체적인 지시로 /revise 재시도 권장.",
                                    project_name=paths.project_name,
                                )
                            # 새 spec + 새 contract 알림
                            if paths.spec.exists():
                                notifier.notify(
                                    "spec_detail",
                                    "(수정 반영됨) spec.md",
                                    file_path=paths.spec,
                                    project_name=paths.project_name,
                                )
                            notifier.notify(
                                "sprint_contract",
                                f"(revise 반영) Sprint {sprint_num} contract 재생성됨.",
                                file_path=paths.sprint_contract
                                if paths.sprint_contract.exists()
                                else None,
                                project_name=paths.project_name,
                                buttons=[["/resume", "/revise"], ["/exit"]],
                            )
                            continue  # 다시 대기 — 추가 revise 또는 resume
                        # resume / skip / continue / timeout — 루프 탈출
                        break
                else:
                    cp.note(f"contract generated (sprint {sprint_num}), auto-proceeding")
                    cp.save(paths.checkpoint_file)

                cp.advance(Phase.CONTRACT_DONE, f"contract approved (sprint {sprint_num})")
                cp.save(paths.checkpoint_file)

            # Phase 3: Generator (claude -p, 자동 실행)
            if cp.should_run(Phase.GENERATING):
                cp.advance(Phase.GENERATING, f"generator running (sprint {sprint_num})")
                cp.save(paths.checkpoint_file)
                notifier.notify("generator_start", f"Sprint {sprint_num} Generator 세션 시작.", project_name=paths.project_name)
                with sprint_tracer.span("generator", mode="claude-p") as info:
                    try:
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
                        info["input"] = f"[generator/sprint-{sprint_num}] initial_prompt:\n{initial_prompt}"
                        # 토대 1: subprocess.run batch → 영속 Popen + stream-json 양방향.
                        # ASK_USER / whisper 라우팅은 plan의 큰 그림 1 / 큰 그림 3에서 본격 연결.
                        result = run_agent_sync(
                            "generator",
                            paths.project_root,
                            initial_prompt,
                            max_turns=config.generator_max_turns,
                        )
                        info["stdout"] = result.stdout or ""
                        report_subprocess(result, f"generator sprint-{sprint_num}", console)
                    except KeyboardInterrupt:
                        pass
                    except FileNotFoundError:
                        notifier.notify("error", "claude CLI를 찾을 수 없습니다.", project_name=paths.project_name)
                        return 3
                notifier.notify(
                    "generator_end", "Generator 세션 종료.",
                    file_path=paths.progress_log if paths.progress_log.exists() else None,
                    project_name=paths.project_name,
                )
                cp.advance(Phase.GENERATING_DONE, f"generator finished (sprint {sprint_num})")
                cp.save(paths.checkpoint_file)

            # Phase 4: Evaluator
            if cp.should_run(Phase.EVALUATING):
                cp.advance(Phase.EVALUATING, f"evaluator running (sprint {sprint_num})")
                cp.save(paths.checkpoint_file)
                try:
                    with sprint_tracer.span("evaluator") as info:
                        info["input"] = f"[evaluator/sprint-{sprint_num}] evaluating qa-report"
                        result = ev.run_evaluate(config, paths)
                        info["stdout"] = result.stdout or ""
                        report_subprocess(result, f"evaluator sprint-{sprint_num}", console)
                except Exception as e:
                    notifier.notify("error", f"Evaluator 실행 중 예외: {e}", project_name=paths.project_name)
                cp.advance(Phase.EVALUATING_DONE, f"evaluation complete (sprint {sprint_num})")
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
                            info["input"] = f"[evaluator/sprint-{sprint_num}] re-eval after validation fail"
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
                            info["input"] = f"[evaluator/sprint-{sprint_num}] re-eval after FAIL"
                            result = ev.run_evaluate(config, paths)
                            report_subprocess(result, f"evaluator-rerun sprint-{sprint_num}", console)
                            info["stdout"] = result.stdout or ""
                    except Exception as e:
                        notifier.notify("error", f"Evaluator 재실행 중 예외: {e}", project_name=paths.project_name)
                    cp.advance(Phase.EVALUATING_DONE, "re-evaluation complete")
                    cp.save(paths.checkpoint_file)
                    continue  # Phase 5로 돌아가 다시 판정
                elif decision == "skip":
                    # FAIL이지만 강제 완료 처리 + 다음 Sprint 진입
                    console.print(
                        f"[yellow]⚠ /skip — Sprint {sprint_num} FAIL 강제 완료 처리 + 다음 Sprint로[/yellow]"
                    )
                    _archive_sprint(sprint_num, paths)
                    notifier.notify(
                        "sprint_pass_next",
                        f"⚠ Sprint {sprint_num} FAIL 무시 + 완료 처리 (사용자 /skip). 다음 Sprint 진행합니다.",
                        file_path=paths.sprint_done_path(sprint_num)
                        if paths.sprint_done_path(sprint_num).exists()
                        else None,
                        project_name=paths.project_name,
                    )
                    # 다음 스프린트 준비: 체크포인트 리셋 (sprint_pass_next 흐름과 동일)
                    cp.advance(Phase.NONE, f"sprint-{sprint_num} SKIP (FAIL but force-completed), continuing")
                    cp.save(paths.checkpoint_file)
                    # consecutive_fails는 초기화 (사용자가 의도적 skip했으므로)
                    consecutive_fails = 0
                    sprints_run += 1
                    sprint_tracer.finalize(status="skipped")
                    continue
                # "resume": Generator 재진입 (루프 계속 — cp는 CONTRACT_DONE)

            sprints_run += 1
            sprint_tracer.finalize()

    finally:
        # 모든 활성 tracer에 대해 finalize 보장 (예외/중단 시에도 Langfuse flush)
        for tr in _active_tracers:
            try:
                tr.finalize(status="interrupted" if exit_code != 0 else "completed")
            except Exception as e:
                print(
                    f"[Langfuse] ⚠ finally에서 tracer.finalize 실패: {type(e).__name__}: {e}",
                    flush=True,
                )
        notifier.stop()

    return exit_code
