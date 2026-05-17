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


_HEARTBEAT_SECONDS = 6 * 3600   # 6시간


def _reply_llm_tail(
    notifier: NotifierAdapter,
    paths: ProjectPaths,
    agent_label: str,
    stdout: str,
    *,
    tail_chars: int = 1500,
) -> None:
    """LLM stdout의 마지막 N자를 Slack 스레드 reply로 전송.

    LLM은 직접 Slack에 메시지를 못 보낸다 (notifier는 orchestrator 도구).
    그래서 사용자가 평문 의견을 던졌을 때 LLM이 stdout에 답을 써도 사용자가
    못 본다. 이걸 메우려고 매 LLM 라운드 종료 후 stdout 꼬리를 자동 reply.

    너무 길면 노이즈이므로 tail_chars로 제한. 비어있으면 no-op.
    """
    if not stdout or not stdout.strip():
        return
    tail = stdout.strip()
    if len(tail) > tail_chars:
        tail = "...(이전 생략)\n" + tail[-tail_chars:]
    notifier.notify(
        "info",
        f"💭 {agent_label} LLM 응답 (마지막 {min(tail_chars, len(tail))}자):\n```\n{tail}\n```",
        project_name=paths.project_name,
    )


def _make_on_question(
    notifier: NotifierAdapter,
    paths: ProjectPaths,
    config: ForgeConfig,
):
    """큰 그림 1: ASK_USER 콜백 팩토리.

    LLM이 stdout에 `{"type":"ask_user", ...}` JSON을 출력하면 runner가 이 콜백을
    호출한다. 콜백은:
      1) Slack 옵션 카드를 thread에 reply로 전송 (SlackNotifier일 때만)
      2) paths.answer_signal_for(qid) 파일이 생길 때까지 **무기한** 폴링
      3) 6시간마다 heartbeat 알림 ("아직 대기 중 + qid")
      4) /stop / /exit 신호 발생 시 추천안 자동 채택 후 즉시 종료
      5) 파일 내용(option_id)을 답으로 반환

    자동 채택 타임아웃은 폐기 (사용자 요청). 응답이 24시간 후에 와도 정상 대기.
    """
    import asyncio as _asyncio

    async def _on_question(ask: dict) -> str:
        from .notifier.slack.adapter import SlackNotifier

        qid = (ask.get("qid") or "").strip()
        fallback = (ask.get("recommend") or "").strip()
        situation = (ask.get("situation") or "").strip()
        axiom_link = (ask.get("axiom_link") or "").strip()
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
        last_heartbeat = start
        console.print(
            f"[cyan]ASK_USER qid={qid} — 사용자 응답 대기 중 (Slack 옵션 카드 전송)[/cyan]"
        )
        while not answer_file.exists():
            if paths.stop_signal.exists() or paths.exit_signal.exists():
                console.print(
                    f"[yellow]ASK_USER qid={qid} — /stop or /exit 감지, 추천안 '{fallback}' 자동 채택 후 종료[/yellow]"
                )
                return fallback
            now = time.time()
            if now - last_heartbeat >= _HEARTBEAT_SECONDS:
                elapsed_h = int((now - start) / 3600)
                heartbeat_msg = (
                    f"⏳ ASK_USER 응답 대기 중 ({elapsed_h}h 경과)\n"
                    f"qid: {qid}\n"
                    f"axiom: {axiom_link or '(없음)'}\n"
                    f"질문: {situation[:200]}\n"
                    f"\n위 스레드의 옵션 카드에서 버튼을 눌러 답해주세요."
                )
                try:
                    notifier.notify(
                        "info", heartbeat_msg,
                        project_name=paths.project_name,
                    )
                except Exception:
                    pass
                last_heartbeat = now
            await _asyncio.sleep(2)

        try:
            answer = answer_file.read_text(encoding="utf-8").strip()
            answer_file.unlink(missing_ok=True)
            console.print(
                f"[green]ASK_USER qid={qid} — 응답 수신: '{answer}' (대기 {int(time.time() - start)}s)[/green]"
            )
            return answer or fallback
        except OSError:
            return fallback

    return _on_question


def _try_send_verdict_card(
    notifier: NotifierAdapter,
    paths: ProjectPaths,
    *,
    source: Optional[Path] = None,
    recommendation: str = "",
    recommendation_reason: str = "",
    cost_estimate: str = "",
    buttons: Optional[list[list[str]]] = None,
) -> None:
    """큰 그림 2: Slack notifier일 때만 Verdict Card를 thread에 reply로 첨부.

    source가 명시되지 않으면 qa-report.md(기존 동작). 명시되면 그 파일(plan-review.md 등).
    파일에 Axiom Verdicts 표가 없으면 자체 no-op.
    Telegram 등 다른 notifier는 기존 첨부 폴백 그대로.
    """
    # 함수 지역 import로 순환 / hook 제거 우회
    from .notifier.slack.adapter import SlackNotifier

    if not isinstance(notifier, SlackNotifier):
        return
    notifier.send_verdict_card(
        source if source is not None else paths.qa_report,
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
    *,
    branch_summaries: Optional[list[dict]] = None,
    escalated_branches: Optional[list[str]] = None,
) -> None:
    """FAIL + 선택지 알림 (parallel-branches-design.md 단계 8).

    단일 분기 모드(기존 호출 경로): branch_summaries/escalated_branches 미지정 →
    이전 메시지 형식 그대로 (회귀 0).

    병렬 모드(신규):
    - branch_summaries=[{"branch_id":..., "status":"PASS"/"FAIL", "score":...,
                          "consecutive_fails":int}].
    - escalated_branches 비어있지 않으면 1 sprint = 1 알림 (escalation 시점만).
    - escalated_branches 비어있으면 임계점 미만 자동 재시도 -> 알림 발사 X (early return).
    """
    is_parallel = branch_summaries is not None
    if is_parallel and (not escalated_branches):
        # 임계점 미만 자동 재시도. 1 sprint = 1 알림 원칙 — early return.
        return

    totals = tracer.sprint_totals()
    total_mins = parse_cost_log(paths.cost_log)
    dur = totals["duration_seconds"] / 60

    if is_parallel:
        # ── 병렬 모드: ESCALATION 일괄 통보 ──
        score_lines = []
        for s in branch_summaries or []:
            bid = s.get("branch_id", "?")
            status = s.get("status", "?")
            score = s.get("score") or ""
            cf = s.get("consecutive_fails")
            score_part = f" ({score})" if score else ""
            cf_part = (
                f" — {cf}/{config.branch_fail_escalate_threshold} escalated"
                if status == "FAIL" and cf is not None
                else ""
            )
            score_lines.append(f"• {bid}: {status}{score_part}{cf_part}")
        scores_block = "\n".join(score_lines) or "• (분기 정보 없음)"

        escalated_str = ", ".join(escalated_branches or []) or "(없음)"
        msg = (
            f"Sprint {sprint_num} ESCALATION\n\n"
            f"분기별 점수:\n{scores_block}\n\n"
            f"escalation 분기: {escalated_str}\n"
            f"─────────────────\n\n"
            f"📊 비용\n"
            f"• 이번 스프린트: {dur:.0f}분 | in {totals['tokens_input']:,} / out {totals['tokens_output']:,}\n"
            f"• 누적: {total_mins:.0f}분\n\n"
            f"─────────────────\n\n"
            f"→ Planner 재호출 예정. 게이트:\n"
            f"/resume — Planner 재호출 진행 (기본)\n"
            f"/skip — 이대로 다음 sprint 진입\n"
            f"/stop — 여기서 중단"
        )
        notifier.notify(
            "qa_fail", msg,
            file_path=paths.qa_report if paths.qa_report.exists() else None,
            project_name=paths.project_name,
            buttons=[["/resume", "/skip"], ["/stop"]],
        )
        return

    # ── 단일 분기 모드 (기존 동작, 회귀 0) ──
    scores = _extract_scores_from_qa_report(paths)
    score_lines = "\n".join(f"• {k}: {v}/10" for k, v in scores.items())
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


# ── 다중 분기 스프린트 (parallel-branches-design.md 단계 6) ─────────────────


def _build_generator_prompt(
    spec: BranchSpec,
    branch_paths: ProjectPaths,
    sprint_num: int,
) -> str:
    """다중 분기 모드 generator prompt.

    핵심: trunk 절대 경로를 prompt에 주입 (분기별 progress-log는 .gitignore 영역이라
    worktree의 상대 경로로는 쓸 수 없음).
    """
    progress_abs = branch_paths.progress_log.as_posix()
    files_section = ""
    if spec.files_owned:
        owned_lines = "\n".join(f"  - {p}" for p in spec.files_owned)
        files_section = (
            f"\n자기 작업 영역 (files_owned):\n{owned_lines}\n"
            f"이 영역 외 파일은 절대 수정하지 마라. 다른 분기가 동시에 다른 영역에서 작업 중이다.\n"
        )
    tasks_section = ""
    if spec.tasks:
        task_lines = "\n".join(f"  - {t}" for t in spec.tasks)
        tasks_section = f"\n분기 {spec.id} 작업 요약:\n{task_lines}\n"
    return (
        f"너는 Sprint {sprint_num}의 분기 {spec.id} ({spec.title}) generator다. "
        f"artifacts/sprint-contract.md의 `## Parallel Task Graph (YAML)` 섹션에서 "
        f"id={spec.id} 항목을 찾아 자기 책임 범위를 확인하라. "
        f"체크박스 순서대로 구현하고, 각 기능 완성 시 커밋 + 체크박스 `[x]`. "
        f"커밋 메시지는 짧고 직관적인 영어로, prefix는 `feat:` / `fix:` / `refactor:` 세 가지만. "
        f"예: `feat: add watcher debounce`. Co-Authored-By 서명 금지. "
        f"중요 결정은 artifacts/decisions/decision-NNN.md, "
        f"진행 로그는 **trunk 절대 경로 {progress_abs}** 에 작성하라 "
        f"(자기 cwd의 상대 경로 X — 분기별 progress-log는 trunk 격리 영역)."
        f"{tasks_section}{files_section}"
    )


def _run_multi_branch_sprint(
    branch_specs: list[BranchSpec],
    config: ForgeConfig,
    paths: ProjectPaths,
    cp: Checkpoint,
    sprint_num: int,
    sprint_tracer: SprintTracer,
    notifier: NotifierAdapter,
) -> None:
    """단계 6의 다중 분기 흐름.

    동작 (단계 6 명세 그대로):
    1. auto_commit_trunk_artifacts("planner-contract") — worktree 생성 전 trunk
       sprint-contract를 git에 반영해야 신규 contract가 worktree로 sync됨.
    2. create_branch_worktrees — 분기당 .worktrees/sprint-{N}-{id} 폴더 + 브랜치.
    3. cp.branches 갱신 + 체크포인트 저장.
    4. run_agents_parallel("generator", ...) — N개 동시.
    5. auto_commit_worktree per branch (generator turn).
    6. cp.advance(GENERATING_DONE).
    7. run_agents_parallel("evaluator", ...) — N개 동시.
    8. auto_commit_worktree per branch (evaluator turn).
    9. cp.advance(EVALUATING_DONE).

    세션 C 위임 지점:
    - 단계 7 finalizer 호출 (호출자가 _run_multi_branch_sprint 호출 직후 추가)
    - 단계 8 FAIL 격상 + PASS 부분 머지 (호출자가 evaluator 결과를 모아 처리)
    """
    branch_ids = [s.id for s in branch_specs]

    notifier.notify(
        "generator_start",
        f"Sprint {sprint_num} 다중 분기 모드 — {len(branch_ids)}개 동시 실행: "
        + ", ".join(branch_ids),
        project_name=paths.project_name,
    )

    # 1. trunk artifacts 자동 커밋 (sprint-contract.md를 worktree로 전파해야 함).
    commit_res = auto_commit_trunk_artifacts(
        paths.project_root, "planner-contract", sprint_num
    )
    if commit_res.status == "error":
        notifier.notify(
            "warning",
            f"⚠ trunk artifacts 자동 커밋 실패: {commit_res.stderr.strip()[:300]}",
            project_name=paths.project_name,
        )

    # 2. 분기별 worktree 생성.
    try:
        worktrees = create_branch_worktrees(
            paths.project_root, sprint_num, branch_ids
        )
    except RuntimeError as exc:
        notifier.notify(
            "error",
            f"⚠ git worktree 생성 실패: {exc}",
            project_name=paths.project_name,
        )
        raise

    # 분기별 artifacts/branches/{id}/ 디렉터리 보장 (progress-log/qa-report 쓰기용).
    for spec in branch_specs:
        paths.ensure_branch_artifacts(spec.id)

    # 3. cp.branches 갱신.
    cp.branches = [
        BranchState(
            branch_id=spec.id,
            phase=Phase.GENERATING,
            sprint=sprint_num,
            worktree_path=str(wt.path),
            git_branch=wt.git_branch,
            status="active",
        )
        for spec, wt in zip(branch_specs, worktrees)
    ]
    cp.advance(Phase.GENERATING, f"parallel generators running (sprint {sprint_num})")
    cp.save(paths.checkpoint_file)

    # 4. N개 generator 동시 실행.
    gen_tasks: list[ParallelBranchTask] = []
    for spec, wt in zip(branch_specs, worktrees):
        bp = paths.branch_paths(spec.id)
        gen_tasks.append(
            ParallelBranchTask(
                branch_id=spec.id,
                cwd=wt.path,
                initial_prompt=_build_generator_prompt(spec, bp, sprint_num),
                whisper_queue_path=bp.whisper_queue,
                max_turns=config.generator_max_turns,
                notifier=notifier,
            )
        )
    with sprint_tracer.span("generator-parallel", mode="claude-p") as info:
        info["input"] = (
            f"[generator/sprint-{sprint_num}] {len(branch_ids)} branches: "
            + ", ".join(branch_ids)
        )
        gen_results = run_agents_parallel(
            gen_tasks, "generator", max_parallel=config.max_parallel_branches
        )
        info["stdout"] = "\n\n".join(
            f"[{bid}]\n{(r.stdout or '')[:1000]}" for bid, r in gen_results.items()
        )
    for bid, result in gen_results.items():
        report_subprocess(result, f"generator sprint-{sprint_num}-{bid}", console)

    # 5. worktree 자동 커밋 (generator turn).
    for spec, wt in zip(branch_specs, worktrees):
        commit_res = auto_commit_worktree(wt.path, spec.id, sprint_num, "generator")
        if commit_res.status == "error":
            notifier.notify(
                "warning",
                f"⚠ worktree 자동 커밋 실패 ({spec.id}): "
                f"{commit_res.stderr.strip()[:300]}",
                project_name=paths.project_name,
            )

    # 6. checkpoint 갱신.
    for bs in cp.branches:
        bs.phase = Phase.GENERATING_DONE
    cp.advance(Phase.GENERATING_DONE, f"parallel generators finished (sprint {sprint_num})")
    cp.save(paths.checkpoint_file)
    notifier.notify(
        "generator_end",
        f"Sprint {sprint_num} 다중 분기 generator 종료 ({len(branch_ids)}개).",
        project_name=paths.project_name,
    )

    # 7. N개 evaluator 동시 실행.
    for bs in cp.branches:
        bs.phase = Phase.EVALUATING
    cp.advance(Phase.EVALUATING, f"parallel evaluators running (sprint {sprint_num})")
    cp.save(paths.checkpoint_file)

    eval_tasks: list[ParallelBranchTask] = []
    for spec, wt in zip(branch_specs, worktrees):
        bp = paths.branch_paths(spec.id)
        qa_abs = bp.qa_report.as_posix()
        prompt = (
            f"너는 Sprint {sprint_num}의 분기 {spec.id} ({spec.title}) evaluator다. "
            "artifacts/sprint-contract.md의 각 항목 중 자기 분기에 해당하는 부분을 평가하라. "
            f"qa-report는 **trunk 절대 경로 {qa_abs}** 에 작성하라 "
            "(자기 cwd의 상대 경로 X — 분기별 qa-report는 trunk 격리 영역). "
            "종합 판정은 PASS 또는 FAIL 중 하나여야 한다."
        )
        eval_tasks.append(
            ParallelBranchTask(
                branch_id=spec.id,
                cwd=wt.path,
                initial_prompt=prompt,
                whisper_queue_path=bp.whisper_queue,
                max_turns=config.evaluator_max_turns,
                notifier=notifier,
            )
        )
    with sprint_tracer.span("evaluator-parallel") as info:
        info["input"] = (
            f"[evaluator/sprint-{sprint_num}] {len(branch_ids)} branches: "
            + ", ".join(branch_ids)
        )
        try:
            eval_results = run_agents_parallel(
                eval_tasks, "evaluator", max_parallel=config.max_parallel_branches
            )
        except Exception as exc:
            notifier.notify(
                "error",
                f"Parallel Evaluator 실행 중 예외: {exc}",
                project_name=paths.project_name,
            )
            eval_results = {}
        info["stdout"] = "\n\n".join(
            f"[{bid}]\n{(r.stdout or '')[:1000]}" for bid, r in eval_results.items()
        )
    for bid, result in eval_results.items():
        report_subprocess(result, f"evaluator sprint-{sprint_num}-{bid}", console)

    # 8. worktree 자동 커밋 (evaluator turn).
    for spec, wt in zip(branch_specs, worktrees):
        commit_res = auto_commit_worktree(wt.path, spec.id, sprint_num, "evaluator")
        if commit_res.status == "error":
            notifier.notify(
                "warning",
                f"⚠ worktree 자동 커밋 실패 ({spec.id}, evaluator): "
                f"{commit_res.stderr.strip()[:300]}",
                project_name=paths.project_name,
            )

    # 9. checkpoint 갱신.
    for bs in cp.branches:
        bs.phase = Phase.EVALUATING_DONE
    cp.advance(Phase.EVALUATING_DONE, f"parallel evaluation complete (sprint {sprint_num})")
    cp.save(paths.checkpoint_file)


# ── 병렬 분기 finalization + escalation (parallel-branches-design.md 단계 7-8) ──
#
# 세션 B(`_handle_parallel_sprint_generation`)가 generator/evaluator 단계를 끝낸 뒤
# 이 두 함수를 호출한다. 세션 분리 정책상 같은 파일 안에 살지만 기능 단위로 격리.


class _NullSpan:
    """sprint_tracer 미주입 시 안전 fallback."""

    def __enter__(self) -> dict:
        return {}

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None


class _NullTracer:
    """sprint_tracer 미주입 시 안전 fallback (sprint_totals 0 반환)."""

    def sprint_totals(self) -> dict:
        return {
            "duration_seconds": 0,
            "tokens_input": 0,
            "tokens_output": 0,
            "tokens_cache": 0,
        }

    def span(self, *args, **kwargs):
        return _NullSpan()

    def finalize(self, *args, **kwargs) -> None:
        return None


def _extract_scores_for_branch(paths: ProjectPaths, branch_id: str) -> str:
    """분기별 qa-report.md에서 score 한 줄 요약 (병렬 알림용)."""
    bp = paths.branch_paths(branch_id) if branch_id != "trunk" else paths
    if not bp.qa_report.exists():
        return ""
    scores: dict[str, int] = {}
    text = bp.qa_report.read_text(encoding="utf-8", errors="replace")
    for m in _SCORE_RE.finditer(text):
        scores[m.group(1).strip()] = int(m.group(2))
    if not scores:
        return ""
    items = list(scores.items())[:3]
    return ", ".join(f"{k} {v}/10" for k, v in items)


def _collect_branch_summary(paths: ProjectPaths, branch_states: list) -> list[dict]:
    """checkpoint.branches 리스트에서 알림용 summary dict 추출.

    원소는 BranchState (pydantic) 또는 (id, status, fails) 튜플 등 어떤 형태든 받을 수
    있게 duck-typing.
    """
    summaries: list[dict] = []
    for bs in branch_states:
        bid = getattr(bs, "branch_id", None) or (
            bs[0] if isinstance(bs, (list, tuple)) else "?"
        )
        status_raw = getattr(bs, "status", None) or (
            bs[1] if isinstance(bs, (list, tuple)) and len(bs) > 1 else ""
        )
        cfails = getattr(bs, "consecutive_fails", None) or (
            bs[2] if isinstance(bs, (list, tuple)) and len(bs) > 2 else 0
        )
        if str(status_raw).lower() in ("passed", "pass"):
            status = "PASS"
        elif str(status_raw).lower() in ("failed", "fail", "escalated"):
            status = "FAIL"
        else:
            status = str(status_raw).upper() or "?"
        summaries.append(
            {
                "branch_id": bid,
                "status": status,
                "score": _extract_scores_for_branch(paths, bid),
                "consecutive_fails": int(cfails or 0),
            }
        )
    return summaries


def _handle_parallel_sprint_finalization(
    config: ForgeConfig,
    paths: ProjectPaths,
    sprint_num: int,
    branches: list,
    worktrees: list,
    *,
    notifier: NotifierAdapter,
    sprint_tracer=None,
):
    """병렬 sprint의 finalizer 호출 + 결과 처리 (단계 7).

    호출자가 generator/evaluator를 끝내고 이 함수를 호출. 반환된 FinalizeResult의
    status를 보고 분기:
    - "merged": 전체 머지 성공 → worktree 정리 + auto_commit_trunk_artifacts
    - "merged_partial": 부분 머지 성공 (partial=True 호출 경로)
    - "needs_escalation": _handle_parallel_sprint_escalation으로 후속 처리
    - "merge_conflict" / "scope_violation" / "error": 사용자 게이트
    """
    from .agents.finalizer import run_finalize
    from .worktree import auto_commit_trunk_artifacts, remove_branch_worktrees

    span_ctx = (
        sprint_tracer.span("finalizer") if sprint_tracer is not None else _NullSpan()
    )
    with span_ctx as info:
        info["input"] = (
            f"[finalizer/sprint-{sprint_num}] merging {len(branches)} branches"
        )
        result = run_finalize(
            config,
            paths,
            branches,
            worktrees,
            partial=False,
            sprint_num=sprint_num,
            notifier=notifier,
        )
        info["stdout"] = result.detail

    if result.status == "merged":
        try:
            remove_branch_worktrees(paths.trunk_root, worktrees)
        except Exception as e:
            console.print(f"[yellow]worktree 정리 실패 (무시): {e}[/yellow]")
        try:
            auto_commit_trunk_artifacts(
                paths.trunk_root, "finalizer-merge", sprint_num
            )
        except Exception as e:
            console.print(
                f"[yellow]trunk artifacts 자동 커밋 실패 (무시): {e}[/yellow]"
            )
        return result

    if result.status == "needs_escalation":
        return result

    if result.status == "merge_conflict":
        notifier.notify(
            "warning",
            (
                f"Sprint {sprint_num} finalizer 머지 충돌 - 의미적 충돌로 abort.\n\n"
                f"파일: {', '.join(result.conflict_files) or '(목록 없음)'}\n"
                f"detail: {result.detail}\n\n"
                f"`artifacts/.merge-decisions/escalation-{sprint_num}.md` 참조.\n\n"
                f"/resume - 사용자 수동 머지 후 진행\n"
                f"/stop - 여기서 중단"
            ),
            project_name=paths.project_name,
            buttons=[["/resume", "/stop"]],
        )
        return result

    if result.status == "scope_violation":
        violating = (
            ", ".join(result.violation.violating_files[:5])
            if result.violation
            else "?"
        )
        notifier.notify(
            "warning",
            (
                f"Sprint {sprint_num} finalizer 스코프 위반 - 자동 revert 수행.\n\n"
                f"충돌 안 났던 파일을 수정함: {violating}\n"
                f"detail: {result.detail}\n\n"
                f"/resume - revert된 상태에서 재시도\n"
                f"/stop - 여기서 중단"
            ),
            project_name=paths.project_name,
            buttons=[["/resume", "/stop"]],
        )
        return result

    notifier.notify(
        "error",
        f"Sprint {sprint_num} finalizer 비정상 종료: {result.status} - {result.detail}",
        project_name=paths.project_name,
    )
    return result


def _handle_parallel_sprint_escalation(
    config: ForgeConfig,
    paths: ProjectPaths,
    sprint_num: int,
    branches: list,
    worktrees: list,
    branch_states: list,
    *,
    notifier: NotifierAdapter,
    sprint_tracer=None,
) -> dict:
    """FAIL 분기 escalation 처리 (단계 8-2).

    흐름:
    1. PASS 분기 부분 머지 (run_finalize(partial=True)). PASS worktree만 정리.
    2. FAIL worktree는 보존 (다음 라운드 Planner 참조용).
    3. auto_commit_trunk_artifacts("finalizer-partial-merge").
    4. 일괄 알림 1건 발사.
    5. 사용자 게이트 (/resume → Planner 재호출 / /skip / /stop).

    반환:
        {"user_decision": ..., "partial_merge_status": ...,
         "pass_branches": [...], "fail_branches": [...]}

    Planner 재호출 자체는 세션 B 통합 시점에서 처리 (plan-review 게이트 우회).
    """
    from .agents.finalizer import run_finalize
    from .worktree import auto_commit_trunk_artifacts, remove_branch_worktrees

    pass_branches = []
    fail_branches = []
    for spec in branches:
        bid = getattr(spec, "id", None) or getattr(spec, "branch_id", "")
        if not bid:
            continue
        bp = paths.branch_paths(bid)
        if ev.is_pass(bp):
            pass_branches.append(spec)
        else:
            fail_branches.append(spec)

    pass_ids = [
        getattr(s, "id", None) or getattr(s, "branch_id", "") for s in pass_branches
    ]
    fail_ids = [
        getattr(s, "id", None) or getattr(s, "branch_id", "") for s in fail_branches
    ]

    partial_merge_status = "skipped"

    if pass_branches:
        pass_worktrees = [wt for wt in worktrees if wt.branch_id in pass_ids]
        span_ctx = (
            sprint_tracer.span("finalizer-partial")
            if sprint_tracer is not None
            else _NullSpan()
        )
        with span_ctx as info:
            info["input"] = (
                f"[finalizer-partial/sprint-{sprint_num}] "
                f"PASS={len(pass_branches)} FAIL={len(fail_branches)}"
            )
            part_result = run_finalize(
                config,
                paths,
                pass_branches,
                pass_worktrees,
                partial=True,
                round_num=1,
                sprint_num=sprint_num,
                notifier=notifier,
            )
            info["stdout"] = part_result.detail

        if part_result.status == "merged_partial":
            partial_merge_status = "merged_partial"
            try:
                remove_branch_worktrees(paths.trunk_root, pass_worktrees)
            except Exception as e:
                console.print(
                    f"[yellow]PASS worktree 정리 실패 (무시): {e}[/yellow]"
                )
            try:
                auto_commit_trunk_artifacts(
                    paths.trunk_root, "finalizer-partial-merge", sprint_num
                )
            except Exception as e:
                console.print(
                    f"[yellow]trunk artifacts 자동 커밋 실패 (무시): {e}[/yellow]"
                )

    summaries = _collect_branch_summary(paths, branch_states)
    _notify_fail_with_options(
        notifier,
        config,
        sprint_tracer if sprint_tracer is not None else _NullTracer(),
        sprint_num,
        paths,
        consecutive=max((s.get("consecutive_fails", 0) for s in summaries), default=0),
        branch_summaries=summaries,
        escalated_branches=fail_ids,
    )

    decision = wait_for_approval_or_stop(
        paths, timeout=config.approval_timeout_seconds
    )

    return {
        "user_decision": decision,
        "partial_merge_status": partial_merge_status,
        "pass_branches": pass_ids,
        "fail_branches": fail_ids,
    }


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

    # --plan 파일은 spec.md로 직접 복사하지 않는다. 그 본문을 *사용자 요청*에 합쳐서
    # planner Mode A로 보내야 planner가 (a) 본질을 추출해 frontmatter에 박고
    # (b) plan-review.md를 함께 작성하는 의무 prompt가 적용된다.
    # 사용자가 spec.md를 직접 만들어 둔 경우만 Mode B(review)로 진입한다.
    if plan_file:
        plan = Path(plan_file)
        if plan.exists() and not paths.spec.exists():
            plan_body = plan.read_text(encoding="utf-8")
            plan_intro = (
                f"[기획서 본문 — 파일: {plan.name}]\n"
                "아래 본문에서 (a) 사용자가 명시·함축한 본질(essence_axioms) 3-7개와 "
                "(b) sprint 구획을 추출해 spec.md를 작성하라. "
                "양식은 YAML frontmatter / 마크다운 / 평문 어떤 것이든 가능하다.\n\n"
                "──── 본문 시작 ────\n"
            )
            plan_outro = "\n──── 본문 끝 ────\n"
            merged = plan_intro + plan_body + plan_outro
            request = (request + "\n\n" + merged) if request else merged

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
            from .judgment import (
                inject_essence_into_spec,
                load_essence_for_project,
                parse_essence,
            )

            essence = load_essence_for_project(
                paths.project_root,
                hint_path=config.essence_source_path or None,
            )
            # --plan 파일을 essence source 후보로 추가 시도 (yaml frontmatter 또는
            # ```yaml fence가 있으면 기계 판독 가능 → essence 객체로 변환).
            # 못 파싱해도 planner Mode A의 자동 추출 prompt가 plan 본문에서 본질을
            # 뽑아 spec.md frontmatter에 박을 예정 (그 사실을 사용자에게 정확히 전달).
            plan_essence_attempted = False
            if not essence and plan_file:
                plan_path = Path(plan_file)
                if plan_path.exists():
                    plan_essence_attempted = True
                    parsed = parse_essence(plan_path)
                    if parsed:
                        essence = parsed
            if essence:
                console.print(
                    f"[cyan]essence 로드: {essence.source} ({len(essence.axioms)} axioms)[/cyan]"
                )

            # 큰 그림 3 일부 보강: planner 작업 시작 *전에* thread root를 먼저 박는다.
            # 이렇게 해야 planner가 작업하는 동안에도 사용자가 스레드에 평문 의견
             # (whisper) 을 보낼 수 있고, handle_event가 thread_ts 매칭으로 적재 가능.
            # 첫 notify가 root가 되므로 이 한 줄이 thread_ts를 만들어준다.
            if essence:
                essence_note = f"essence: {len(essence.axioms)} axioms 로드됨 (출처: {essence.source})"
            elif plan_essence_attempted:
                essence_note = (
                    f"essence: --plan 파일({Path(plan_file).name})에 기계 판독 가능한 "
                    "yaml 블록은 없음 → planner가 본문에서 자동 추출하여 spec.md "
                    "frontmatter에 박을 예정"
                )
            elif plan_file:
                essence_note = (
                    f"essence: --plan 파일({Path(plan_file).name}) 본문을 planner에 "
                    "전달, 본문에서 추출 예정"
                )
            else:
                essence_note = (
                    "essence: 외부 파일 없음 → planner가 사용자 요청 평문에서 추출 예정"
                )
            notifier.notify(
                "info",
                f"🧵 [{paths.project_name}] forge run 시작 — planner 작업 중...\n"
                f"{essence_note}\n"
                f"이 스레드에 평문 메시지를 보내면 LLM이 다음 turn에 자동 반영합니다.",
                project_name=paths.project_name,
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
                        notifier=notifier,
                    )
                    info["stdout"] = result.stdout or ""
                    report_subprocess(result, "planner(generate)", console)
                    _reply_llm_tail(notifier, paths, "planner(generate)", result.stdout)
                else:
                    info["input"] = "[planner/review] reviewing existing spec.md"
                    result = pl.run_review(
                        config, paths,
                        essence=essence,
                        on_question=on_question_cb,
                        notifier=notifier,
                    )
                    info["stdout"] = result.stdout or ""
                    report_subprocess(result, "planner(review)", console)
                    _reply_llm_tail(notifier, paths, "planner(review)", result.stdout)

            # plan-review.md 미생성 명시 경고 (silent fallback 금지)
            if not paths.plan_review.exists():
                notifier.notify(
                    "warning",
                    "⚠ planner LLM이 plan-review.md를 작성하지 않고 종료했습니다. "
                    "위 LLM 응답을 참고해 사용자가 직접 수동 작성하거나, "
                    "더 명시적인 지시로 /revise를 누르거나, /resume으로 진행하세요.",
                    project_name=paths.project_name,
                )

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
            # 큰 그림 2: planner가 plan-review.md에 `## Axiom Verdicts` 표를 작성했으면
            # 기획 단계에서도 본질 부합도 Verdict Card를 함께 띄운다. 사용자가 결정 카드
            # 옆에서 axiom 단위 ✅⚠️❌ 분포를 보고 1탭 결정하게.
            _try_send_verdict_card(
                notifier,
                paths,
                source=paths.plan_review,
                recommendation=(
                    "기획 진행 — READY" if status == "READY"
                    else "기획 수정 권장 — 위 axiom 행의 recommend_action 참고"
                ),
                recommendation_reason=(
                    "모든 critical axiom이 spec.md에 반영됨"
                    if status == "READY"
                    else "일부 axiom이 PARTIAL/MISSING 상태"
                ),
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
                        result = pl.run_revise(revise_text, config, paths, notifier=notifier)
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
                        notifier=notifier,
                    )
                    info["stdout"] = result.stdout or ""
                    report_subprocess(result, f"planner(contract sprint-{sprint_num})", console)
                    _reply_llm_tail(notifier, paths, f"contract sprint-{sprint_num}", result.stdout)

                # sprint-contract.md 미생성 명시 경고 (silent fallback 금지)
                if not paths.sprint_contract.exists():
                    notifier.notify(
                        "warning",
                        "⚠ contract LLM이 sprint-contract.md를 작성하지 않고 종료. "
                        "generator가 이대로 진행하면 contract를 못 읽고 멈춥니다. "
                        "/revise로 명시 지시 후 재시도 권장.",
                        project_name=paths.project_name,
                    )

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
                                result = pl.run_revise(revise_text, config, paths, notifier=notifier)
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
                                    result = pl.run_contract(sprint_num, config, paths, notifier=notifier)
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

            # ── 병렬 분기 분기점 (parallel-branches-design.md 단계 6) ──
            # sprint-contract.md의 `## Parallel Task Graph (YAML)` 섹션을 읽고
            # 분기 명세를 결정. 섹션 부재 시 [BranchSpec(id="trunk")] 1개 → 단일
            # 분기 모드(아래 if 분기). 회귀 0 보호.
            try:
                sprint_contract_text = (
                    paths.sprint_contract.read_text(encoding="utf-8", errors="replace")
                    if paths.sprint_contract.exists()
                    else ""
                )
                branch_specs = parse_branches(sprint_contract_text)
            except ValueError as exc:
                # 잘못된 YAML — silent fallback 금지. 사용자에게 알리고 직렬 모드로 폴백.
                notifier.notify(
                    "warning",
                    f"⚠ sprint-contract.md의 Parallel Task Graph YAML 파싱 실패: {exc}\n"
                    f"단일 분기 모드로 폴백합니다.",
                    project_name=paths.project_name,
                )
                branch_specs = [BranchSpec(id="trunk")]

            # config.max_parallel_branches 캡 강제 (1 <= N <= 4 는 ForgeConfig
            # validator가 이미 보장). N=1이면 다중 분기가 와도 단일 분기로 폴백.
            if len(branch_specs) > 1 and config.max_parallel_branches <= 1:
                console.print(
                    f"[yellow]Parallel Task Graph가 {len(branch_specs)}개 분기를 정의했지만 "
                    f"FORGE_MAX_PARALLEL_BRANCHES=1 → 단일 분기 모드로 폴백[/yellow]"
                )
                branch_specs = [BranchSpec(id="trunk")]
            elif len(branch_specs) > config.max_parallel_branches:
                console.print(
                    f"[yellow]Parallel Task Graph가 {len(branch_specs)}개 분기를 정의했지만 "
                    f"FORGE_MAX_PARALLEL_BRANCHES={config.max_parallel_branches} → "
                    f"앞 {config.max_parallel_branches}개만 실행[/yellow]"
                )
                branch_specs = branch_specs[: config.max_parallel_branches]

            if len(branch_specs) == 1:
                # ============================================================
                # === 단일 분기 모드 (회귀 0, 기존 동작 그대로) ===============
                # ============================================================
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
                            # 큰 그림 1: generator도 코딩 도중 모호한 분기에서 ASK_USER 가능.
                            # config.max_questions(default 10000)로 한도 조정.
                            generator_on_question = _make_on_question(notifier, paths, config)
                            result = run_agent_sync(
                                "generator",
                                paths.project_root,
                                initial_prompt,
                                max_turns=config.generator_max_turns,
                                on_question=generator_on_question,
                                whisper_queue_path=paths.whisper_queue,
                            )
                            info["stdout"] = result.stdout or ""
                            report_subprocess(result, f"generator sprint-{sprint_num}", console)
                            _reply_llm_tail(notifier, paths, f"generator sprint-{sprint_num}", result.stdout)
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
                            result = ev.run_evaluate(config, paths, notifier=notifier)
                            info["stdout"] = result.stdout or ""
                            report_subprocess(result, f"evaluator sprint-{sprint_num}", console)
                    except Exception as e:
                        notifier.notify("error", f"Evaluator 실행 중 예외: {e}", project_name=paths.project_name)
                    cp.advance(Phase.EVALUATING_DONE, f"evaluation complete (sprint {sprint_num})")
                    cp.save(paths.checkpoint_file)
            else:
                # ============================================================
                # === 다중 분기 모드 (병렬 실행) ===============================
                # ============================================================
                # 단계 6의 핵심 흐름: trunk artifacts 자동 커밋 → worktree 생성 →
                # generator N개 동시 실행 → worktree auto-commit → evaluator N개
                # 동시 실행 → worktree auto-commit. finalizer 호출 + FAIL 격상은
                # 세션 C 영역 (TODO 주석으로 위임 지점 표시).
                _run_multi_branch_sprint(
                    branch_specs,
                    config,
                    paths,
                    cp,
                    sprint_num,
                    sprint_tracer,
                    notifier,
                )
                # TODO(세션 C 단계 7): finalizer 호출 자리.
                #   run_finalize(config, paths, branch_specs, worktrees, notifier=notifier)
                #   → trunk 머지 + sprint-N-done.md 작성 또는 충돌 escalate.
                # TODO(세션 C 단계 8): FAIL 격상 + PASS 분기 부분 머지 자리.
                #   - branch별 ev.is_pass(paths, branch_id=spec.id) 집계
                #   - 임계점 도달 시 Planner 재호출 + 새 sprint-contract.md
                # 임시 종료: 세션 C 통합 전에는 다중 분기 sprint를 여기서 종료한다.
                notifier.notify(
                    "warning",
                    f"⚠ Sprint {sprint_num} 다중 분기({len(branch_specs)}개) 평가까지 완료.\n"
                    f"Finalizer 머지 + FAIL 격상은 세션 C 통합 후 활성화됩니다.\n"
                    f"분기별 qa-report는 artifacts/branches/<branch_id>/qa-report.md 에 있습니다.",
                    project_name=paths.project_name,
                )
                exit_code = 0
                break

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
                            result = ev.run_evaluate(config, paths, notifier=notifier)
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
                            result = ev.run_evaluate(config, paths, notifier=notifier)
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
