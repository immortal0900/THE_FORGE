"""5-Phase 하네스 메인 루프."""

from __future__ import annotations

import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .agents import evaluator as ev
from .agents import planner as pl
from .checkpoint import Checkpoint, Phase
from .config import ForgeConfig, ProjectPaths
from .cost_tracker import SprintTracer
from .telegram.notifier import notify
from .telegram.receiver import TelegramReceiver


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


def wait_for_approval(paths: ProjectPaths, timeout: float = 600.0) -> str:
    """Telegram 시그널 또는 stdin 입력 대기. 반환: resume/skip/exit/continue/timeout."""
    for sig in (
        paths.approval_signal,
        paths.skip_signal,
        paths.exit_signal,
        paths.continue_signal,
    ):
        sig.unlink(missing_ok=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if paths.exit_signal.exists():
            return "exit"
        if paths.skip_signal.exists():
            return "skip"
        if paths.approval_signal.exists():
            content = paths.approval_signal.read_text(encoding="utf-8").strip()
            return content or "resume"
        if paths.continue_signal.exists():
            return "continue"
        if _stdin_ready(timeout=1.0):
            return "resume"
        time.sleep(0.3)
    return "timeout"


def _invalidate_stale_review(paths: ProjectPaths) -> None:
    """spec.md가 plan-review.md보다 새로우면 리뷰 무효화."""
    if paths.spec.exists() and paths.plan_review.exists():
        if paths.spec.stat().st_mtime > paths.plan_review.stat().st_mtime:
            paths.plan_review.unlink(missing_ok=True)


def run_cycle(
    request: Optional[str] = None,
    plan_file: Optional[Path] = None,
    config: Optional[ForgeConfig] = None,
    project_root: Optional[Path] = None,
) -> int:
    """메인 사이클. 종료 코드 반환."""
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
    sprint_num = paths.current_sprint()
    tracer = SprintTracer(config, sprint_num, paths.project_name, paths.cost_log)
    receiver = TelegramReceiver(config, paths)
    receiver.start()

    exit_code = 0
    try:
        _invalidate_stale_review(paths)

        # Phase 1: Planning
        if cp.should_run(Phase.PLANNING):
            cp.advance(Phase.PLANNING, "planner running")
            cp.save(paths.checkpoint_file)
            with tracer.span("planner"):
                if not paths.spec.exists():
                    if not request:
                        notify(
                            config,
                            "error",
                            "spec.md가 없고 요청도 없습니다.",
                            project_name=paths.project_name,
                        )
                        return 2
                    pl.run_generate(request, config, paths)
                else:
                    pl.run_review(config, paths)

            status = pl.plan_review_status(paths)
            notify(
                config,
                "planner_done" if status == "READY" else "plan_revision",
                f"plan-review.md 상태: {status}",
                file_path=paths.plan_review if paths.plan_review.exists() else paths.spec,
                project_name=paths.project_name,
            )

            signal = wait_for_approval(paths, timeout=600)
            if signal == "exit":
                cp.advance(Phase.PLANNING, "halted by user after planning")
                cp.save(paths.checkpoint_file)
                return 0
            if status == "NEEDS_REVISION" and signal != "skip":
                return 0

            cp.advance(Phase.PLANNING_DONE, "planning approved")
            cp.save(paths.checkpoint_file)

        # Phase 2: Sprint Contract
        if cp.should_run(Phase.CONTRACT):
            cp.advance(Phase.CONTRACT, "contract generating")
            cp.save(paths.checkpoint_file)
            with tracer.span("contract"):
                pl.run_contract(sprint_num, config, paths)

            notify(
                config,
                "sprint_contract",
                f"Sprint {sprint_num} contract 생성됨.",
                file_path=paths.sprint_contract if paths.sprint_contract.exists() else None,
                project_name=paths.project_name,
            )
            signal = wait_for_approval(paths, timeout=600)
            if signal == "exit":
                return 0
            cp.advance(Phase.CONTRACT_DONE, "contract approved")
            cp.save(paths.checkpoint_file)

        # Phase 3: Generator (interactive)
        if cp.should_run(Phase.GENERATING):
            cp.advance(Phase.GENERATING, "generator interactive session")
            cp.save(paths.checkpoint_file)
            notify(
                config,
                "generator_start",
                f"Sprint {sprint_num} Generator 세션 시작.",
                project_name=paths.project_name,
            )
            with tracer.span("generator", mode="interactive"):
                try:
                    subprocess.run(
                        ["claude"],
                        cwd=str(paths.project_root),
                        stdin=sys.stdin,
                        stdout=sys.stdout,
                        stderr=sys.stderr,
                    )
                except KeyboardInterrupt:
                    pass
                except FileNotFoundError:
                    notify(
                        config,
                        "error",
                        "claude CLI를 찾을 수 없습니다.",
                        project_name=paths.project_name,
                    )
                    return 3
            notify(
                config,
                "generator_end",
                "Generator 세션 종료. Evaluator로 넘어갑니다.",
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
                with tracer.span("evaluator"):
                    ev.run_evaluate(config, paths)
            except Exception as e:
                notify(
                    config,
                    "error",
                    f"Evaluator 실행 중 예외: {e}",
                    project_name=paths.project_name,
                )
            cp.advance(Phase.EVALUATING_DONE, "evaluation complete")
            cp.save(paths.checkpoint_file)

        # Phase 5: 결과 판단
        exit_code = _handle_results(config, paths, cp, sprint_num)
    finally:
        receiver.stop()
        tracer.finalize()
    return exit_code


def _handle_results(
    config: ForgeConfig,
    paths: ProjectPaths,
    cp: Checkpoint,
    sprint_num: int,
) -> int:
    """Phase 5: PASS/FAIL 분기."""
    ok, reason = ev.validate_qa_report(paths)
    if not ok:
        notify(
            config,
            "warning",
            f"qa-report.md 검증 실패: {reason}",
            project_name=paths.project_name,
        )
        return 4

    if ev.is_pass(paths):
        archive = paths.sprint_done_path(sprint_num)
        try:
            archive.write_text(
                f"# Sprint {sprint_num} — DONE\n\n"
                f"## qa-report.md\n\n"
                + paths.qa_report.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
        except OSError:
            pass
        notify(
            config,
            "qa_pass",
            f"Sprint {sprint_num} PASS — 아카이브 완료.",
            file_path=paths.qa_report,
            project_name=paths.project_name,
        )
        cp.advance(Phase.NONE, f"sprint-{sprint_num} done")
        cp.save(paths.checkpoint_file)
        return 0

    notify(
        config,
        "qa_fail",
        f"Sprint {sprint_num} FAIL — 다음 행동 선택: /resume=evaluator 재실행, "
        "/skip=generator 재개, /exit=중단.",
        file_path=paths.qa_report,
        project_name=paths.project_name,
    )
    signal = wait_for_approval(paths, timeout=1800)
    if signal == "skip":
        cp.advance(Phase.GENERATING, "resume generator after qa_fail")
    elif signal == "exit":
        cp.advance(Phase.NONE, "halted by user at qa_fail")
    else:
        cp.advance(Phase.EVALUATING, "re-evaluating after qa_fail")
    cp.save(paths.checkpoint_file)
    return 1
