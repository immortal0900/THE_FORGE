"""typer CLI — run / eval / status / init / notify."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import sys

import typer
from rich.console import Console
from rich.table import Table

from . import __version__

# Windows cp949 콘솔에서 유니코드 인쇄 실패 방지.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
from .checkpoint import Checkpoint, Phase
from .config import ForgeConfig, ProjectPaths

app = typer.Typer(name="forge", help=f"THE FORGE v{__version__} - 범용 하네스 오케스트레이터")
console = Console(force_terminal=True, legacy_windows=False)


def _paths(root: Optional[Path]) -> ProjectPaths:
    return ProjectPaths(Path(root or Path.cwd()).resolve())


@app.command()
def run(
    request: Optional[str] = typer.Argument(None, help="사용자 요청 (spec 생성용)"),
    plan: Optional[Path] = typer.Option(None, "--plan", help="기획서 파일 경로"),
    root: Optional[Path] = typer.Option(None, "--root", help="프로젝트 루트 (기본: cwd)"),
) -> None:
    """메인 하네스 사이클 실행."""
    from .orchestrator import run_cycle

    project_root = Path(root or Path.cwd()).resolve()
    config = ForgeConfig.load(project_root)
    code = run_cycle(
        request=request,
        plan_file=plan,
        config=config,
        project_root=project_root,
    )
    raise typer.Exit(code=code)


@app.command(name="eval")
def eval_cmd(
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Evaluator만 재실행."""
    from .agents import evaluator as ev
    from .cost_tracker import SprintTracer

    paths = _paths(root)
    paths.ensure_artifacts()
    config = ForgeConfig.load(paths.project_root)
    sprint_num = paths.current_sprint()
    tracer = SprintTracer(config, sprint_num, paths.project_name, paths.cost_log)
    with tracer.span("evaluator", mode="eval-only"):
        ev.run_evaluate(config, paths)
    tracer.finalize()
    ok, reason = ev.validate_qa_report(paths)
    if ok:
        console.print(f"[green]qa-report.md 생성 완료 — PASS={ev.is_pass(paths)}[/green]")
    else:
        console.print(f"[red]검증 실패: {reason}[/red]")


@app.command()
def status(root: Optional[Path] = typer.Option(None, "--root")) -> None:
    """현재 체크포인트 및 경로 상태 출력."""
    paths = _paths(root)
    cp = Checkpoint.load(paths.checkpoint_file)
    config = ForgeConfig.load(paths.project_root)

    table = Table(title=f"THE FORGE status — {paths.project_name}")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    table.add_row("project_root", str(paths.project_root))
    table.add_row("phase", cp.phase.name)
    table.add_row("detail", cp.detail)
    table.add_row("timestamp", cp.timestamp)
    table.add_row("sprint (next)", str(paths.current_sprint()))
    table.add_row("telegram_enabled", str(config.telegram_enabled))
    table.add_row("langfuse_enabled", str(config.langfuse_enabled))
    for p in (paths.spec, paths.plan_review, paths.sprint_contract, paths.qa_report):
        table.add_row(p.name, "OK" if p.exists() else "-")
    console.print(table)


@app.command()
def init(
    template: Optional[str] = typer.Option(None, "--template", help="도메인 템플릿(미사용 예약)"),
    force: bool = typer.Option(False, "--force", help="기존 파일을 .backup/에 백업 후 덮어쓰기"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """프로젝트 부트스트랩 (v2.0 부록 A 6단계 중 3단계)."""
    paths = _paths(root)
    paths.ensure_artifacts()
    scaffold = _scaffold_dir()
    if not scaffold.exists():
        console.print(f"[red]scaffold/ 디렉토리를 찾을 수 없습니다: {scaffold}[/red]")
        raise typer.Exit(code=5)

    _copy_scaffold(scaffold, paths, force=force)
    _merge_claude_settings(scaffold, paths, force=force)
    _ensure_forge_toml(scaffold, paths, force=force)
    _ensure_gitignore(paths)

    console.print("[green]forge init 완료.[/green]")
    console.print(
        "\n[bold]다음 단계 (v2.0 부록 A):[/bold]\n"
        "  1. forge.toml에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 입력\n"
        "  2. (선택) LANGFUSE_* 키 입력\n"
        "  3. forge run \"요청 내용\" 으로 첫 사이클 실행\n"
    )


@app.command()
def notify(
    event_type: str = typer.Argument(..., help="예: session_stop, info"),
    message: str = typer.Argument(..., help="메시지 본문"),
    file_path: Optional[Path] = typer.Argument(None, help="첨부 파일 (선택)"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Hooks용 알림 유틸리티."""
    from .telegram.notifier import notify as send

    paths = _paths(root)
    config = ForgeConfig.load(paths.project_root)
    send(config, event_type, message, file_path=file_path, project_name=paths.project_name)


@app.command()
def version() -> None:
    console.print(f"THE FORGE v{__version__}")


# ── init helpers ────────────────────────────────────────────────────────────

def _scaffold_dir() -> Path:
    """설치된 패키지 기준 scaffold/ 경로 탐색."""
    here = Path(__file__).resolve().parent
    candidates = [
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

    agent_targets = {
        scaffold / "agents" / "planner" / "AGENT.md":
            paths.project_root / ".claude" / "agents" / "planner" / "AGENT.md",
        scaffold / "agents" / "evaluator" / "AGENT.md":
            paths.project_root / ".claude" / "agents" / "evaluator" / "AGENT.md",
    }
    for src, dst in agent_targets.items():
        if src.exists():
            _backup_then_copy(src, dst, paths.backup, force)

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


def _ensure_forge_toml(scaffold: Path, paths: ProjectPaths, force: bool) -> None:
    example = scaffold / "forge.toml.example"
    target = paths.project_root / "forge.toml"
    if not example.exists():
        return
    if target.exists() and not force:
        return
    if target.exists():
        paths.backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, paths.backup / "forge.toml.bak")
    shutil.copy2(example, target)


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
        "forge.toml",
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
