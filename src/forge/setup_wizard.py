"""`forge setup` 마법사 — ~/.forge/config.env 전역 설정 파일 생성/갱신.

Slack/Langfuse 토큰은 여기에 한 번만 저장되고, 모든 프로젝트의 ForgeConfig가 읽어간다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console(force_terminal=True, legacy_windows=False)


def _config_path() -> Path:
    return Path.home() / ".forge" / "config.env"


def _parse_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE 또는 KEY="VALUE" 형식의 env 파일을 dict로 파싱."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        result[key] = val
    return result


def _mask(value: str) -> str:
    if not value:
        return "(unset)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]}"


def _prompt(
    label: str,
    default: Optional[str] = None,
    existing: Optional[str] = None,
    mask: bool = False,
) -> str:
    """입력 프롬프트. 엔터(빈 입력)만 치면 existing 또는 default 유지."""
    shown_default = default or ""
    hint_parts = []
    if existing:
        hint_parts.append(f"기존: {_mask(existing) if mask else existing}")
    if shown_default and not existing:
        hint_parts.append(f"기본: {shown_default}")
    hint = f" ({', '.join(hint_parts)})" if hint_parts else ""
    value = typer.prompt(f"{label}{hint}", default="", show_default=False)
    if not value:
        return existing if existing is not None else shown_default
    return value


def run_setup(reset: bool = False) -> None:
    """대화형으로 값을 수집해 ~/.forge/config.env에 저장."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = {} if reset else _parse_env_file(path)

    console.print()
    console.print("[bold cyan]🔧 THE FORGE 전역 설정 마법사[/bold cyan]")
    console.print(f"저장 위치: [dim]{path}[/dim]")
    console.print(
        "[dim]모든 프로젝트가 이 파일을 읽습니다. 프로젝트별로 덮어쓰려면 "
        "그 프로젝트의 .env에 같은 키를 설정하세요.[/dim]\n"
    )

    if existing:
        table = Table(title="현재 저장된 값")
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")
        for k in sorted(existing):
            v = existing[k]
            mask_it = "TOKEN" in k or "SECRET" in k or "KEY" in k
            table.add_row(k, _mask(v) if mask_it else v)
        console.print(table)
        console.print(
            "\n[yellow]빈 엔터를 치면 기존 값 유지. 새 값을 입력하면 덮어씁니다.[/yellow]\n"
        )

    values = dict(existing)

    console.print("[bold]── 알림 백엔드 ──[/bold]")
    backend = _prompt(
        "FORGE_NOTIFIER_BACKEND (telegram|slack)",
        default="slack",
        existing=values.get("FORGE_NOTIFIER_BACKEND"),
    )
    if backend not in ("telegram", "slack"):
        console.print(f"[red]잘못된 값 '{backend}'. slack으로 설정합니다.[/red]")
        backend = "slack"
    values["FORGE_NOTIFIER_BACKEND"] = backend

    console.print("\n[bold]── Slack (전역 공유) ──[/bold]")
    console.print("[dim]https://api.slack.com/apps 에서 발급한 토큰을 입력하세요. 스킵하려면 엔터만.[/dim]")
    for key, label in [
        ("FORGE_SLACK_BOT_TOKEN", "Bot Token (xoxb-...)"),
        ("FORGE_SLACK_APP_TOKEN", "App-Level Token (xapp-...)"),
        ("FORGE_SLACK_CHANNEL", "Channel ID (C01ABC...)"),
    ]:
        v = _prompt(label, existing=values.get(key), mask=("TOKEN" in key))
        if v:
            values[key] = v

    console.print("\n[bold]── Langfuse (선택) ──[/bold]")
    console.print("[dim]관측 시스템. 사용하지 않으면 모두 엔터.[/dim]")
    for key, label, default in [
        ("FORGE_LANGFUSE_PUBLIC_KEY", "Public Key (pk-lf-...)", None),
        ("FORGE_LANGFUSE_SECRET_KEY", "Secret Key (sk-lf-...)", None),
        ("FORGE_LANGFUSE_HOST", "Host", "https://cloud.langfuse.com"),
    ]:
        v = _prompt(
            label,
            default=default,
            existing=values.get(key),
            mask=("KEY" in key or "SECRET" in key),
        )
        if v:
            values[key] = v

    # 파일 쓰기
    lines = ["# THE FORGE 전역 설정 — forge setup으로 생성/갱신", ""]
    ordered_keys = [
        "FORGE_NOTIFIER_BACKEND",
        "FORGE_SLACK_BOT_TOKEN",
        "FORGE_SLACK_APP_TOKEN",
        "FORGE_SLACK_CHANNEL",
        "FORGE_LANGFUSE_PUBLIC_KEY",
        "FORGE_LANGFUSE_SECRET_KEY",
        "FORGE_LANGFUSE_HOST",
    ]
    seen = set()
    for k in ordered_keys:
        if k in values and values[k]:
            lines.append(f'{k}="{values[k]}"')
            seen.add(k)
    # 기타 사용자가 직접 넣은 키 보존
    for k in sorted(values):
        if k in seen or not values[k]:
            continue
        lines.append(f'{k}="{values[k]}"')

    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")

    # 권한 0o600 (POSIX만)
    try:
        if os.name == "posix":
            os.chmod(path, 0o600)
    except OSError:
        pass

    console.print(f"\n[green]✅ {path} 저장 완료[/green]")
    console.print(
        "[dim]이후 모든 프로젝트에서 `forge init`만 실행하면 이 값이 자동으로 사용됩니다.[/dim]"
    )
    if backend == "slack":
        console.print(
            "[dim]다음 단계: 프로젝트 디렉토리에서 `forge init` → `forge run \"<요청>\"`[/dim]"
        )
