"""typer CLI — run / eval / status / init / notify — v2.3."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from ._logging import report_subprocess

# Windows cp949 콘솔에서 유니코드 인쇄 실패 방지.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
from .autoinfer import infer_project_name  # noqa: E402
from .checkpoint import Checkpoint, Phase  # noqa: E402
from .config import ForgeConfig, ProjectPaths  # noqa: E402
from . import registry as _registry  # noqa: E402

app = typer.Typer(name="forge", help=f"THE FORGE v{__version__} - 범용 하네스 오케스트레이터")
console = Console(force_terminal=True, legacy_windows=False)


def _paths(root: Optional[Path]) -> ProjectPaths:
    return ProjectPaths(Path(root or Path.cwd()).resolve())


@app.command()
def run(
    request: Optional[str] = typer.Argument(
        None,
        help=(
            "사용자 요청 평문. 본질을 직접 박아도 된다. "
            "예: forge run \"이 프로젝트의 본질은 1) 오프라인 동작 2) 1초 내 응답\""
        ),
    ),
    plan: Optional[Path] = typer.Option(
        None, "--plan", "-p",
        help=(
            "기획서 파일 경로. 양식 자유 (yaml frontmatter / 마크다운 / 평문 모두 OK). "
            "planner가 본문에서 본질을 추출해 spec.md frontmatter에 박는다."
        ),
    ),
    root: Optional[Path] = typer.Option(None, "--root", "-r", help="프로젝트 루트 (기본: cwd)"),
    from_phase: Optional[str] = typer.Option(None, "--from", help="시작 단계: planning|contract|generating|evaluating"),
    single_sprint: bool = typer.Option(False, "--single-sprint", help="1 스프린트만 실행 (v2.2 호환)"),
    max_sprints: Optional[int] = typer.Option(None, "--max-sprints", help="최대 스프린트 수 제한"),
) -> None:
    """메인 하네스 사이클 실행 (v2.3: 자동 스프린트 루프)."""
    from .orchestrator import run_cycle

    project_root = Path(root or Path.cwd()).resolve()
    config = ForgeConfig.load(project_root)

    # --from 옵션 처리
    phase = None
    if from_phase:
        phase_map = {
            "planning": Phase.PLANNING,
            "contract": Phase.CONTRACT,
            "generating": Phase.GENERATING,
            "evaluating": Phase.EVALUATING,
        }
        phase = phase_map.get(from_phase.lower())
        if phase is None:
            console.print(f"[red]알 수 없는 단계: {from_phase}[/red]")
            console.print("사용 가능: planning, contract, generating, evaluating")
            raise typer.Exit(code=1)

    code = run_cycle(
        request=request,
        plan_file=plan,
        config=config,
        project_root=project_root,
        from_phase=phase,
        single_sprint=single_sprint,
        max_sprints=max_sprints,
    )
    raise typer.Exit(code=code)


@app.command(name="eval")
def eval_cmd(
    root: Optional[Path] = typer.Option(None, "--root", "-r"),
) -> None:
    """Evaluator만 재실행."""
    from .agents import evaluator as ev
    from .cost_tracker import SprintTracer

    paths = _paths(root)
    paths.ensure_artifacts()
    config = ForgeConfig.load(paths.project_root)
    sprint_num = paths.current_sprint()
    tracer = SprintTracer(config, sprint_num, paths.project_name, paths.cost_log)
    with tracer.span("evaluator", mode="eval-only") as info:
        info["input"] = f"[evaluator/manual/sprint-{sprint_num}] forge eval invocation"
        result = ev.run_evaluate(config, paths)
        info["stdout"] = result.stdout or ""
        report_subprocess(result, "evaluator(manual)", console)
    tracer.finalize()
    ok, reason = ev.validate_qa_report(paths)
    if ok:
        console.print(f"[green]qa-report.md 생성 완료 — PASS={ev.is_pass(paths)}[/green]")
    else:
        console.print(f"[red]검증 실패: {reason}[/red]")


@app.command()
def journal(
    sprint: Optional[int] = typer.Option(None, "--sprint", "-s", help="단일 스프린트 번호"),
    sprints: Optional[str] = typer.Option(None, "--sprints", help="범위(`1-4`) 또는 쉼표 목록(`1,3,5`)"),
    since: Optional[str] = typer.Option(None, "--since", help="ISO 날짜(YYYY-MM-DD) 이후 변경사항만"),
    root: Optional[Path] = typer.Option(None, "--root", "-r"),
) -> None:
    """docs/journal.md에 사람이 읽는 엔지니어링 저널 엔트리 추가.

    에러/근본원인, 결정, 팁을 artifacts/, git log에서 추출.
    범위 미지정 시 journal.md 마지막 엔트리 이후 변경사항만 정리.
    """
    from .agents import journal as jr
    from .cost_tracker import SprintTracer

    paths = _paths(root)
    paths.ensure_artifacts()
    config = ForgeConfig.load(paths.project_root)

    specified = sum(x is not None for x in (sprint, sprints, since))
    if specified > 1:
        console.print("[red]--sprint / --sprints / --since 중 하나만 지정할 수 있습니다.[/red]")
        raise typer.Exit(code=2)

    sprint_list: Optional[list[int]] = None
    if sprint is not None:
        sprint_list = [sprint]
    elif sprints:
        try:
            sprint_list = _parse_sprint_range(sprints)
        except ValueError as e:
            console.print(f"[red]--sprints 파싱 실패: {e}[/red]")
            raise typer.Exit(code=2) from None

    console.print("[cyan]docs/journal.md 작성 중...[/cyan]")
    sprint_num = paths.current_sprint()
    tracer = SprintTracer(config, sprint_num, paths.project_name, paths.cost_log)
    with tracer.span("journal", mode="claude-p") as info:
        scope = f"sprints={sprint_list}" if sprint_list else (f"since={since}" if since else "full")
        info["input"] = f"[journal] scope: {scope}"
        result = jr.run_journal(config, paths, sprints=sprint_list, since=since)
        info["stdout"] = result.stdout or ""
        report_subprocess(result, "journal", console)
    tracer.finalize()

    if result.returncode != 0:
        console.print(f"[red]journal 에이전트 실행 실패 (exit={result.returncode})[/red]")
        if result.stderr:
            console.print(result.stderr[-2000:])
        raise typer.Exit(code=result.returncode)

    if paths.journal.exists():
        size_kb = paths.journal.stat().st_size / 1024
        console.print(f"[green]{paths.journal} ({size_kb:.1f} KB) 갱신 완료[/green]")

        # 활성 백엔드(Telegram/Slack)에 최상단 엔트리 요약 + 파일 첨부
        from .notifier import get_notifier

        notifier = get_notifier(config, paths)
        if notifier.enabled:
            title, body = _extract_latest_journal_entry(paths.journal)
            if body:
                preview = body if len(body) <= 900 else body[:900] + "\n\n…(이하 첨부 파일 참조)"
                notifier.notify(
                    "journal",
                    preview,
                    file_path=paths.journal,
                    project_name=paths.project_name,
                )
                console.print(f"[dim]{config.notifier_backend}에 저널 요약 전송됨 ({title[:60]})[/dim]")
    else:
        console.print(
            "[yellow]docs/journal.md가 생성되지 않았습니다 — 에이전트가 파일 작성 전에 턴 소진했을 가능성.[/yellow]\n"
            "[dim]힌트: pyproject.toml [tool.forge]에 journal_max_turns = 120 등으로 늘리거나 --sprint N으로 범위 좁히세요.[/dim]"
        )
        tail = (result.stdout or "").strip()[-1500:]
        if tail:
            console.print("[dim]--- stdout tail ---[/dim]")
            console.print(tail)
        err = (result.stderr or "").strip()[-800:]
        if err:
            console.print("[dim]--- stderr tail ---[/dim]")
            console.print(err)


def _parse_sprint_range(raw: str) -> list[int]:
    """`1-4` → [1,2,3,4], `1,3,5` → [1,3,5], `1-3,5` → [1,2,3,5]."""
    result: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            a, b = token.split("-", 1)
            lo, hi = int(a), int(b)
            if lo > hi:
                raise ValueError(f"범위 시작이 끝보다 큽니다: {token}")
            result.update(range(lo, hi + 1))
        else:
            result.add(int(token))
    if not result:
        raise ValueError("비어있는 범위")
    return sorted(result)


def _extract_latest_journal_entry(journal_path: Path) -> tuple[str, str]:
    """docs/journal.md 최상단 `## ` 엔트리의 (제목, 본문) 반환.

    본문은 제목 포함, 다음 `## ` 직전까지. 엔트리 없으면 빈 문자열 쌍.
    """
    if not journal_path.exists():
        return ("", "")
    lines = journal_path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = -1
    for i, line in enumerate(lines):
        if line.startswith("## "):
            start = i
            break
    if start < 0:
        return ("", "")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    title = lines[start][3:].strip()
    body = "\n".join(lines[start:end]).rstrip()
    return title, body


@app.command()
def status(root: Optional[Path] = typer.Option(None, "--root", "-r")) -> None:
    """현재 체크포인트 및 경로 상태 출력 (v2.3: 누적 시간/토큰, 스프린트 히스토리)."""
    from .cost_tracker import parse_cost_log

    paths = _paths(root)
    cp = Checkpoint.load(paths.checkpoint_file)
    config = ForgeConfig.load(paths.project_root)
    total_mins = parse_cost_log(paths.cost_log)

    table = Table(title=f"THE FORGE status — {paths.project_name}")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("project_root", str(paths.project_root))
    table.add_row("phase", cp.phase.name)
    table.add_row("detail", cp.detail)
    table.add_row("timestamp", cp.timestamp)
    table.add_row("sprint (next)", str(paths.current_sprint()))
    table.add_row("누적 시간", f"{total_mins:.0f}분")
    table.add_row("notifier_backend", config.notifier_backend)
    table.add_row("telegram_enabled", str(config.telegram_enabled))
    table.add_row("slack_enabled", str(config.slack_enabled))
    table.add_row("langfuse_enabled", str(config.langfuse_enabled))
    # 실행 모드 표시 (단일 직렬 vs 병렬 N — branch 표기 혼동 방지)
    try:
        from .contract import parse_branches

        sct = (
            paths.sprint_contract.read_text(encoding="utf-8", errors="replace")
            if paths.sprint_contract.exists()
            else ""
        )
        _specs = parse_branches(sct)
        if len(_specs) == 1 and _specs[0].id == "trunk":
            _mode = "단일 직렬 (LLM 세션 1)"
        elif len(_specs) == 1:
            _mode = f"단일 직렬 (LLM 세션 1, branch={_specs[0].id})"
        else:
            _n = min(len(_specs), config.max_parallel_branches)
            _mode = f"병렬 {_n} worktree (LLM 세션 {_n}개 동시)"
    except Exception:
        _mode = "(미정 — contract 미생성 또는 파싱 실패)"
    table.add_row("실행 모드", _mode)
    for p in (paths.spec, paths.plan_review, paths.sprint_contract, paths.qa_report):
        table.add_row(p.name, "OK" if p.exists() else "-")

    # 스프린트 히스토리
    pattern = re.compile(r"sprint-(\d+)-done\.md")
    if paths.artifacts.exists():
        done_files = sorted(
            [p for p in paths.artifacts.iterdir() if pattern.match(p.name)],
            key=lambda p: int(pattern.match(p.name).group(1)),
        )
        for f in done_files:
            num = pattern.match(f.name).group(1)
            table.add_row(f"Sprint {num}", "✅ PASS (archived)")

    console.print(table)


@app.command()
def setup(
    reset: bool = typer.Option(False, "--reset", help="기존 ~/.forge/config.env 값을 무시하고 새로 입력"),
) -> None:
    """전역 설정 마법사 — ~/.forge/config.env에 Slack/Langfuse 토큰을 한 번만 저장.

    이후 모든 프로젝트의 ForgeConfig가 이 파일을 자동으로 읽어 사용한다.
    """
    from .setup_wizard import run_setup

    run_setup(reset=reset)


@app.command()
def init(
    template: Optional[str] = typer.Option(None, "--template", help="도메인 템플릿(미사용 예약)"),
    force: bool = typer.Option(False, "--force", "-f", help="기존 파일을 .backup/에 백업 후 덮어쓰기"),
    root: Optional[Path] = typer.Option(None, "--root", "-r"),
) -> None:
    """프로젝트 부트스트랩 (scaffold 복사 + 최소 .env + pyproject.toml [tool.forge]).

    Slack/Langfuse 토큰은 `forge setup`의 ~/.forge/config.env에서 자동 로드되므로
    프로젝트 .env는 FORGE_PROJECT_NAME 한 줄로 최소화된다.
    """
    paths = _paths(root)
    paths.ensure_artifacts()
    scaffold = _scaffold_dir()
    if not scaffold.exists():
        console.print(f"[red]scaffold/ 디렉토리를 찾을 수 없습니다: {scaffold}[/red]")
        raise typer.Exit(code=5)

    # 프로젝트명 추론 + 중복 검사
    inferred = infer_project_name(paths.project_root)
    collision = _registry.check_collision(inferred, paths.project_root)
    final_name = inferred
    if collision:
        console.print(
            f"\n[yellow]⚠️ 프로젝트명 '{inferred}'는 이미 "
            f"[bold]{collision.get('path')}[/bold]에 등록돼 있습니다.[/yellow]"
        )
        console.print(f"   현재 경로: [dim]{paths.project_root}[/dim]")
        parent_tag = infer_project_name(paths.project_root.parent) or "alt"
        suggested = f"{inferred}_{parent_tag}"
        new_name = typer.prompt(
            f"새 이름을 입력하세요 (엔터 시 '{suggested}' 사용)",
            default="",
            show_default=False,
        )
        final_name = (new_name or suggested).strip() or suggested
        console.print(f"   [green]→ 프로젝트명: {final_name}[/green]")

    _registry.register_project(final_name, paths.project_root)

    _copy_scaffold(scaffold, paths, force=force)
    _merge_claude_settings(scaffold, paths, force=force)
    _ensure_env_and_pyproject(paths, project_name=final_name, force=force)
    _ensure_gitignore(paths)

    console.print(f"\n[green]forge init 완료. (project_name: {final_name})[/green]")

    global_cfg = Path.home() / ".forge" / "config.env"
    if global_cfg.exists():
        console.print(f"[dim]전역 설정 로드: {global_cfg}[/dim]")
        console.print(
            "\n[bold]다음 단계:[/bold]\n"
            "  forge run \"요청 내용\" 으로 첫 사이클 실행\n"
        )
    else:
        console.print(
            "\n[yellow]⚠️ 전역 설정 파일이 없습니다.[/yellow]\n"
            "  [bold]1.[/bold] `forge setup` 실행 — Slack/Langfuse 토큰 입력 (최초 1회)\n"
            "  [bold]2.[/bold] `forge run \"요청 내용\"`\n"
        )


@app.command()
def notify(
    event_type: str = typer.Argument(..., help="예: session_stop, info"),
    message: str = typer.Argument(..., help="메시지 본문"),
    file_path: Optional[Path] = typer.Argument(None, help="첨부 파일 (선택)"),
    root: Optional[Path] = typer.Option(None, "--root", "-r"),
) -> None:
    """Hooks용 알림 유틸리티. 활성 백엔드(Telegram/Slack)로 일회성 알림 전송."""
    from .notifier import get_notifier

    paths = _paths(root)
    config = ForgeConfig.load(paths.project_root)
    notifier = get_notifier(config, paths)
    notifier.notify(event_type, message, file_path=file_path, project_name=paths.project_name)


@app.command(name="update-templates")
def update_templates(
    root: Optional[Path] = typer.Option(None, "--root", "-r"),
    dry_run: bool = typer.Option(False, "--dry-run", help="변경 없이 대상만 출력"),
) -> None:
    """설치본 scaffold의 templates/*.md를 프로젝트 templates/로 재동기화 (기존 파일은 .backup/에 백업)."""
    paths = _paths(root)
    paths.ensure_artifacts()
    scaffold = _scaffold_dir()
    tpl_dir = scaffold / "templates"
    if not tpl_dir.exists():
        console.print(f"[red]scaffold/templates를 찾을 수 없습니다: {tpl_dir}[/red]")
        raise typer.Exit(code=5)

    target_tpl = paths.project_root / "templates"
    target_tpl.mkdir(exist_ok=True)

    updated: list[str] = []
    for src in sorted(tpl_dir.glob("*.md")):
        dst = target_tpl / src.name
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            continue
        if dry_run:
            updated.append(src.name)
            continue
        _backup_then_copy(src, dst, paths.backup, force=True)
        updated.append(src.name)

    if not updated:
        console.print("[green]모든 템플릿이 최신 상태입니다.[/green]")
        return

    verb = "갱신 예정" if dry_run else "갱신됨"
    console.print(f"[green]{len(updated)}개 템플릿 {verb}:[/green]")
    for name in updated:
        console.print(f"  • {name}")
    if not dry_run:
        console.print(f"\n기존 파일은 [dim]{paths.backup}[/dim]에 백업되었습니다.")


@app.command(name="update-agents")
def update_agents(
    root: Optional[Path] = typer.Option(None, "--root", "-r"),
    dry_run: bool = typer.Option(False, "--dry-run", help="변경 없이 대상만 출력"),
) -> None:
    """설치본 scaffold의 agents/*.md를 프로젝트 .claude/agents/로 재동기화 (기존 파일은 .backup/에 백업)."""
    paths = _paths(root)
    paths.ensure_artifacts()
    scaffold = _scaffold_dir()
    src_dir = scaffold / "agents"
    if not src_dir.exists():
        console.print(f"[red]scaffold/agents를 찾을 수 없습니다: {src_dir}[/red]")
        raise typer.Exit(code=5)

    target_dir = paths.project_root / ".claude" / "agents"
    target_dir.mkdir(parents=True, exist_ok=True)

    updated: list[str] = []
    for src in sorted(src_dir.glob("*.md")):
        dst = target_dir / src.name
        if dst.exists() and dst.read_bytes() == src.read_bytes():
            continue
        if dry_run:
            updated.append(src.name)
            continue
        _backup_then_copy(src, dst, paths.backup, force=True)
        updated.append(src.name)

    if not updated:
        console.print("[green]모든 에이전트가 최신 상태입니다.[/green]")
        return

    verb = "갱신 예정" if dry_run else "갱신됨"
    console.print(f"[green]{len(updated)}개 에이전트 {verb}:[/green]")
    for name in updated:
        console.print(f"  • {name}")
    if not dry_run:
        console.print(f"\n기존 파일은 [dim]{paths.backup}[/dim]에 백업되었습니다.")


@app.command()
def version() -> None:
    console.print(f"THE FORGE v{__version__}")


# ── init helpers ────────────────────────────────────────────────────────────

def _scaffold_dir() -> Path:
    """설치된 패키지 기준 scaffold/ 경로 탐색."""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "scaffold",  # site-packages/forge/scaffold (installed)
        here.parent.parent / "scaffold",  # src/forge/../../scaffold (dev)
        here.parent / "scaffold",
        Path.cwd() / "scaffold",
    ]
    for c in candidates:
        if c.exists() and (c / "CLAUDE.md").exists():
            return c
    return candidates[0]


def _backup_then_copy(src: Path, dst: Path, backup_dir: Path, force: bool) -> None:
    if dst.exists():
        if not force:
            return
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, backup_dir / dst.name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_scaffold(scaffold: Path, paths: ProjectPaths, force: bool) -> None:
    _backup_then_copy(scaffold / "CLAUDE.md", paths.claude_md, paths.backup, force)

    mcp_src = scaffold / ".mcp.json"
    if mcp_src.exists():
        _backup_then_copy(mcp_src, paths.project_root / ".mcp.json", paths.backup, force)

    agents_src = scaffold / "agents"
    agents_dst = paths.project_root / ".claude" / "agents"
    if agents_src.exists():
        agents_dst.mkdir(parents=True, exist_ok=True)
        for src in agents_src.glob("*.md"):
            _backup_then_copy(src, agents_dst / src.name, paths.backup, force)

    tpl_dir = scaffold / "templates"
    target_tpl = paths.project_root / "templates"
    if tpl_dir.exists():
        target_tpl.mkdir(exist_ok=True)
        for src in tpl_dir.glob("*.md"):
            _backup_then_copy(src, target_tpl / src.name, paths.backup, force)


def _merge_claude_settings(scaffold: Path, paths: ProjectPaths, force: bool) -> None:
    src = scaffold / "settings.json"
    if not src.exists():
        return
    new_data = json.loads(src.read_text(encoding="utf-8"))
    target = paths.claude_settings
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if force:
            paths.backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, paths.backup / target.name)
        merged = {**existing}
        merged.setdefault("hooks", {})
        for event, entries in new_data.get("hooks", {}).items():
            merged["hooks"].setdefault(event, [])
            existing_cmds = {
                h.get("command")
                for e in merged["hooks"][event]
                for h in e.get("hooks", [])
            }
            for entry in entries:
                new_cmds = {h.get("command") for h in entry.get("hooks", [])}
                if not (new_cmds & existing_cmds):
                    merged["hooks"][event].append(entry)
        target.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        target.write_text(json.dumps(new_data, indent=2, ensure_ascii=False), encoding="utf-8")


def _ensure_env_and_pyproject(
    paths: ProjectPaths,
    project_name: str = "",
    force: bool = False,
) -> None:
    """v2.4: 최소 .env 파일 생성 + pyproject.toml [tool.forge] 섹션 추가.

    .env는 FORGE_PROJECT_NAME 한 줄만. 토큰은 ~/.forge/config.env에서 자동 로드.
    """
    # .env 생성 (프로젝트명만)
    env_target = paths.project_root / ".env"
    resolved_name = project_name or paths.project_root.name
    if not env_target.exists() or force:
        if env_target.exists():
            paths.backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(env_target, paths.backup / ".env.bak")
        env_content = (
            "# THE FORGE — 프로젝트 고유값\n"
            "# 전역 토큰은 ~/.forge/config.env에서 자동 로드됩니다 (forge setup으로 생성).\n"
            "# 이 프로젝트만 다른 백엔드/채널을 쓰려면 아래 주석을 해제하고 값 입력.\n"
            f'FORGE_PROJECT_NAME="{resolved_name}"\n'
            "# FORGE_NOTIFIER_BACKEND=\"telegram\"\n"
            "# FORGE_SLACK_CHANNEL=\"\"\n"
            "# FORGE_TELEGRAM_BOT_TOKEN=\"\"\n"
            "# FORGE_TELEGRAM_CHAT_ID=\"\"\n"
        )
        env_target.write_text(env_content, encoding="utf-8")

    # pyproject.toml [tool.forge] 추가 — ForgeConfig default를 SSoT로 사용
    # 하드코딩 회피: config.py가 단일 진실 출처, init은 그 값을 그대로 박는다.
    # 과거 하드코딩(planner_max_turns=15 등)이 config.py default(60)와 어긋나
    # Mode B/contract가 max-turns 부족으로 잘리는 회귀 발생했음 → 동적 생성으로 차단.
    tunable_keys = (
        "max_sprint_minutes",
        "max_generator_minutes",
        "planner_max_turns",
        "planner_review_max_turns",
        "contract_max_turns",
        "evaluator_max_turns",
    )
    forge_lines = ["", "[tool.forge]"]
    for key in tunable_keys:
        default = ForgeConfig.model_fields[key].default
        forge_lines.append(f"{key} = {default}")
    forge_section = "\n".join(forge_lines) + "\n"

    pyproject = paths.project_root / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(encoding="utf-8")
        if "[tool.forge]" not in content:
            pyproject.write_text(content + forge_section, encoding="utf-8")
    # pyproject.toml이 없으면 생성하지 않음 (비-Python 프로젝트 배려)


def _ensure_gitignore(paths: ProjectPaths) -> None:
    entries = [
        "# forge runtime",
        ".env",
        "artifacts/spec.md",
        "artifacts/plan-review.md",
        "artifacts/sprint-contract.md",
        "artifacts/progress-log.md",
        "artifacts/qa-report.md",
        "artifacts/harness-cost-log.txt",
        "artifacts/.harness-checkpoint",
        "artifacts/.backup/",
        "artifacts/specs/",
        "artifacts/decisions/",
        "artifacts/.approval-signal",
        "artifacts/.skip-signal",
        "artifacts/.continue-signal",
        "artifacts/.exit-signal",
        "artifacts/.eval-signal",
        "artifacts/.stop-signal",
        "artifacts/.revise-signal",
        # 병렬 분기 (parallel-branches-design.md 단계 2, 3)
        ".worktrees/",
        "artifacts/branches/",
        "artifacts/sprint-*-done.md",
        "artifacts/.merge-decisions/",
    ]
    gi = paths.project_root / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    additions = [e for e in entries if e not in existing]
    if additions:
        with gi.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n".join(additions) + "\n")


if __name__ == "__main__":
    app()
