"""설정 로드 + ProjectPaths.

v2.2: .env(비밀) + pyproject.toml [tool.forge](공유) + forge.toml(레거시 하위호환).
우선순위: 환경변수 (FORGE_*) > .env > forge.toml [forge] > pyproject.toml [tool.forge] > 기본값.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class ForgeConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 비밀 (.env에서 로드) ──
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # ── 공유 설정 (pyproject.toml [tool.forge]에서 로드) ──
    max_sprint_minutes: int = 180
    max_generator_minutes: int = 120
    planner_max_turns: int = 15
    planner_review_max_turns: int = 10
    contract_max_turns: int = 12
    evaluator_max_turns: int = 20
    generator_max_turns: int = 180
    journal_max_turns: int = 80

    playwright_enabled: bool = True
    playwright_timeout_seconds: int = 600

    # ── v2.3: 자동 루프 안전장치 ──
    max_total_minutes: int = 1440
    max_consecutive_fails: int = 3
    max_total_sprints: int = 20

    # ── 승인 대기 타임아웃 (초). 기본 24시간. ──
    approval_timeout_seconds: int = 86400

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @classmethod
    def load(cls, project_root: Path) -> "ForgeConfig":
        """환경변수 우선, 그 뒤 TOML에서 비어있지 않은 값만 덮어씀.

        우선순위: 환경변수 (FORGE_*) > .env > forge.toml [forge] > pyproject.toml [tool.forge] > 기본값.
        """
        env_file = Path(project_root) / ".env"
        base = cls(_env_file=str(env_file) if env_file.exists() else None)

        # pyproject.toml [tool.forge] (v2.2 신규) → forge.toml [forge] (레거시) 순으로 읽기
        overrides: dict = {}
        pyproject_path = project_root / "pyproject.toml"
        forge_toml_path = project_root / "forge.toml"

        import tomllib

        if pyproject_path.exists():
            try:
                data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
                overrides.update(data.get("tool", {}).get("forge", {}))
            except Exception:
                pass

        if forge_toml_path.exists():
            try:
                data = tomllib.loads(forge_toml_path.read_text(encoding="utf-8"))
                # forge.toml 값이 pyproject.toml보다 우선 (레거시 호환)
                overrides.update(data.get("forge", {}))
            except Exception:
                pass

        if not overrides:
            return base

        field_defaults = {
            name: f.default for name, f in cls.model_fields.items()
        }
        env_set_fields: set[str] = set()
        import os

        for name in cls.model_fields:
            env_key = f"{cls.model_config.get('env_prefix', '')}{name}".upper()
            if env_key in os.environ and os.environ[env_key] != "":
                env_set_fields.add(name)

        merged = base.model_dump()
        for key, value in overrides.items():
            if key not in cls.model_fields:
                continue
            if key in env_set_fields:
                continue
            if value == field_defaults.get(key):
                continue
            if isinstance(value, str) and value == "":
                continue
            merged[key] = value
        return cls(**merged)


class ProjectPaths:
    """프로젝트 내부 artifacts 경로 일원 관리."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.artifacts = self.project_root / "artifacts"
        self.specs = self.artifacts / "specs"
        self.decisions = self.artifacts / "decisions"
        self.backup = self.artifacts / ".backup"

        self.spec = self.artifacts / "spec.md"
        self.plan_review = self.artifacts / "plan-review.md"
        self.sprint_contract = self.artifacts / "sprint-contract.md"
        self.progress_log = self.artifacts / "progress-log.md"
        self.qa_report = self.artifacts / "qa-report.md"
        self.cost_log = self.artifacts / "harness-cost-log.txt"
        self.checkpoint_file = self.artifacts / ".harness-checkpoint"
        self.journal = self.project_root / "docs" / "journal.md"

        self.approval_signal = self.artifacts / ".approval-signal"
        self.skip_signal = self.artifacts / ".skip-signal"
        self.continue_signal = self.artifacts / ".continue-signal"
        self.exit_signal = self.artifacts / ".exit-signal"
        self.eval_signal = self.artifacts / ".eval-signal"
        self.stop_signal = self.artifacts / ".stop-signal"

        self.claude_settings = self.project_root / ".claude" / "settings.json"
        self.claude_md = self.project_root / "CLAUDE.md"

    @property
    def project_name(self) -> str:
        return self.project_root.name

    def ensure_artifacts(self) -> None:
        for path in (self.artifacts, self.specs, self.decisions, self.backup):
            path.mkdir(parents=True, exist_ok=True)
        self.journal.parent.mkdir(parents=True, exist_ok=True)

    def current_sprint(self) -> int:
        """sprint-N-done.md 최대 번호 + 1. 없으면 1."""
        if not self.artifacts.exists():
            return 1
        pattern = re.compile(r"sprint-(\d+)-done\.md")
        numbers = [
            int(m.group(1))
            for p in self.artifacts.iterdir()
            if (m := pattern.match(p.name))
        ]
        return (max(numbers) + 1) if numbers else 1

    def sprint_done_path(self, sprint_num: int) -> Path:
        return self.artifacts / f"sprint-{sprint_num}-done.md"
