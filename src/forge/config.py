"""설정 로드 + ProjectPaths.

v2.4: .env(프로젝트) + ~/.forge/config.env(전역) + pyproject.toml [tool.forge](공유).
우선순위: 환경변수 (FORGE_*) > 프로젝트 .env > ~/.forge/config.env > forge.toml [forge] > pyproject.toml [tool.forge] > 자동 추론 > 기본값.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .autoinfer import infer_bot_display_name, infer_project_name


def _global_config_path() -> Path:
    return Path.home() / ".forge" / "config.env"


class ForgeConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FORGE_",
        env_file=(str(_global_config_path()), ".env"),  # 뒤쪽이 우선 (프로젝트 .env가 전역 override)
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 프로젝트 식별 ──
    project_name: str = ""           # 비어있으면 디렉토리명에서 추론
    bot_display_name: str = ""       # 비어있으면 Forge-{PascalCase(project_name)}
    bot_emoji: str = ":hammer_and_wrench:"

    # ── 알림 백엔드 선택 ──
    notifier_backend: str = "telegram"   # "telegram" | "slack"

    # ── Telegram (프로젝트 .env에서 로드) ──
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Slack (~/.forge/config.env에서 전역 공유 권장) ──
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_channel: str = ""

    # ── Langfuse (~/.forge/config.env에서 전역 공유 권장) ──
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # ── 공유 설정 (pyproject.toml [tool.forge]에서 로드) ──
    max_sprint_minutes: int = 180
    max_generator_minutes: int = 120
    planner_max_turns: int = 15
    planner_review_max_turns: int = 10
    contract_max_turns: int = 12
    evaluator_max_turns: int = 100
    generator_max_turns: int = 180
    journal_max_turns: int = 80

    playwright_enabled: bool = True
    playwright_timeout_seconds: int = 600

    # ── v2.3: 자동 루프 안전장치 ──
    max_total_minutes: int = 1440
    max_consecutive_fails: int = 0   # 0 = 무제한 (사용자가 /stop으로 직접 중단). >0 시 그 횟수에서 자동 중단.
    max_total_sprints: int = 20

    # ── 승인 대기 타임아웃 (초). 기본 24시간. ──
    approval_timeout_seconds: int = 86400

    # ── 본질(essence_axioms) 파일 경로 ──
    # 사용자가 docs/essence.md (또는 essence.yaml 등) 으로 본질을 외부 제공할 때 그 경로.
    # 비어있으면 표준 후보(docs/essence.md, docs/essence.yaml 등)를 자동 탐색.
    # 본질 파일이 끝까지 없으면 → 사용자 요청 그대로 진행 (강제 X).
    # docs/plan-judgment-velocity.md 토대 3 참조.
    essence_source_path: str = ""

    # ── Langfuse span input/output 최대 문자 수. 0 이하면 무제한. ──
    langfuse_truncate_chars: int = 8000

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_bot_token and self.slack_app_token and self.slack_channel)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    def resolved_project_name(self, project_root: Path) -> str:
        return self.project_name or infer_project_name(project_root)

    def resolved_display_name(self, project_root: Path) -> str:
        if self.bot_display_name:
            return self.bot_display_name
        return infer_bot_display_name(self.resolved_project_name(project_root))

    @classmethod
    def load(cls, project_root: Path) -> "ForgeConfig":
        """환경변수 우선, 그 뒤 TOML에서 비어있지 않은 값만 덮어씀.

        env_file 튜플 순서: (~/.forge/config.env, 프로젝트/.env) — 뒤쪽이 우선.
        """
        global_env = _global_config_path()
        project_env = Path(project_root) / ".env"
        env_files: tuple[str, ...] = tuple(
            str(p) for p in (global_env, project_env) if p.exists()
        )
        base = cls(_env_file=env_files if env_files else None)

        # pyproject.toml [tool.forge] → forge.toml [forge] 순으로 읽기
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
        self.revise_signal = self.artifacts / ".revise-signal"

        # 큰 그림 3 (docs/plan-judgment-velocity.md): Slack thread_ts 영구 저장.
        # 첫 notify 시 root 메시지가 되고 그 ts를 여기 저장 → 이후 모든 알림이
        # 같은 스레드에 reply. 멀티 프로젝트 동시 실행 시 라우팅 단위.
        self.slack_thread = self.artifacts / ".slack-thread"

        # 큰 그림 1: ASK_USER 응답 저장 디렉터리. LLM이 stdout에 ask_user JSON을
        # 출력하면 orchestrator on_question 콜백이 Slack 옵션 카드 전송 + 사용자가
        # 버튼 누르면 receiver가 이 폴더에 <qid>.txt 파일 작성 → 콜백이 폴링.
        self.answers_dir = self.artifacts / ".answers"

        self.claude_settings = self.project_root / ".claude" / "settings.json"
        self.claude_md = self.project_root / "CLAUDE.md"

    @property
    def project_name(self) -> str:
        return self.project_root.name

    def ensure_artifacts(self) -> None:
        for path in (self.artifacts, self.specs, self.decisions, self.backup, self.answers_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.journal.parent.mkdir(parents=True, exist_ok=True)

    def answer_signal_for(self, qid: str) -> Path:
        """ASK_USER qid에 대한 사용자 응답 신호 파일 경로 (큰 그림 1).

        Slack 옵션 카드 버튼 클릭 시 receiver가 이 파일에 option_id를 기록 →
        orchestrator on_question 콜백이 폴링.
        """
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", qid)[:64] or "default"
        return self.answers_dir / f"{safe}.txt"

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
