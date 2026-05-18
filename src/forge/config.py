"""설정 로드 + ProjectPaths.

v2.4: .env(프로젝트) + ~/.forge/config.env(전역) + pyproject.toml [tool.forge](공유).
우선순위: 환경변수 (FORGE_*) > 프로젝트 .env > ~/.forge/config.env > forge.toml [forge] > pyproject.toml [tool.forge] > 자동 추론 > 기본값.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import field_validator
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
    max_sprint_minutes: int = 5000
    max_generator_minutes: int = 4000
    # Mode A는 spec.md + plan-review.md + Axiom Verdicts 표(5-7행) + whisper 응답을
    # 한 세션에서 처리하므로 turn 여유가 필요. Mode B(review)도 verdict 표 작성을
    # 의무화했으니 동일 수준.
    planner_max_turns: int = 200
    planner_review_max_turns: int = 200
    contract_max_turns: int = 200
    evaluator_max_turns: int = 500
    generator_max_turns: int = 500
    journal_max_turns: int = 200

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

    # ── 병렬 분기 (parallel-branches-design.md 단계 0) ──
    # 최대 동시 분기 수. 기본 1 = 직렬 모드 (기존 동작과 동일, 회귀 0).
    # 캡: 1 <= N <= 4. 환경변수 FORGE_MAX_PARALLEL_BRANCHES.
    max_parallel_branches: int = 1
    # 한 분기가 몇 번 연속 실패하면 Planner 재호출(escalation)을 발사할지.
    # 캡: 1 <= N <= 10. 환경변수 FORGE_BRANCH_FAIL_ESCALATE_THRESHOLD.
    branch_fail_escalate_threshold: int = 2

    @field_validator("max_parallel_branches", mode="before")
    @classmethod
    def _clamp_max_parallel_branches(cls, v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 1
        if n < 1:
            return 1
        if n > 4:
            return 4
        return n

    @field_validator("branch_fail_escalate_threshold", mode="before")
    @classmethod
    def _clamp_branch_fail_escalate_threshold(cls, v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 2
        if n < 1:
            return 1
        if n > 10:
            return 10
        return n

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
        # _env_file은 pydantic-settings BaseSettings.__init__의 런타임 override 매직 kwarg.
        # 공식 지원이지만 type stub에 안 박혀 있어 type checker가 빨간줄을 그음 → 무시.
        base = cls(_env_file=env_files if env_files else None)  # type: ignore[call-arg]

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
        self.sprint_capabilities = self.artifacts / "sprint-capabilities.md"
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
        self.capability_drops = self.artifacts / ".capability-drops"
        self.sprint_done_signal = self.artifacts / ".sprint-done-signal"

        # 큰 그림 3 (docs/plan-judgment-velocity.md): Slack thread_ts 영구 저장.
        # 첫 notify 시 root 메시지가 되고 그 ts를 여기 저장 → 이후 모든 알림이
        # 같은 스레드에 reply. 멀티 프로젝트 동시 실행 시 라우팅 단위.
        self.slack_thread = self.artifacts / ".slack-thread"

        # 큰 그림 1: ASK_USER 응답 저장 디렉터리. LLM이 stdout에 ask_user JSON을
        # 출력하면 orchestrator on_question 콜백이 Slack 옵션 카드 전송 + 사용자가
        # 버튼 누르면 receiver가 이 폴더에 <qid>.txt 파일 작성 → 콜백이 폴링.
        self.answers_dir = self.artifacts / ".answers"

        # 큰 그림 3 나머지: 사용자가 Slack 스레드에 평문 메시지를 보내면 receiver가
        # 이 JSONL 파일에 한 줄씩 append. runner의 whisper poller가 매 LLM turn
        # 사이마다 새 라인을 읽어 LLM stdin에 "[사용자 의견] ..." user message로 push.
        self.whisper_queue = self.artifacts / ".whisper-queue.jsonl"

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

    # ── 병렬 분기 헬퍼 (parallel-branches-design.md 단계 3) ──

    @property
    def trunk_root(self) -> Path:
        """trunk worktree의 절대 경로.

        self가 worktree(`<trunk>/.worktrees/sprint-N-branch-K`) 위치를 가리키더라도
        `git rev-parse --git-common-dir`을 사용해 trunk 위치로 거슬러 올라간다.

        - trunk 안에서 호출: git이 ".git" 또는 "<trunk>/.git" 반환 → 부모가 trunk
        - worktree 안에서 호출: git이 "<trunk>/.git" 절대 경로 반환 → 부모가 trunk

        git이 없거나 not-a-repo이면 self.project_root를 그대로 반환 (안전 fallback).
        """
        import subprocess

        try:
            proc = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "--git-common-dir"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except (FileNotFoundError, OSError):
            return self.project_root
        if proc.returncode != 0:
            return self.project_root
        raw = proc.stdout.strip()
        if not raw:
            return self.project_root
        git_dir = Path(raw)
        if not git_dir.is_absolute():
            git_dir = (self.project_root / git_dir).resolve()
        else:
            git_dir = git_dir.resolve()
        return git_dir.parent

    def branch_paths(
        self,
        branch_id: str,
        *,
        in_worktree: bool = False,
    ) -> "ProjectPaths":
        """분기별 ProjectPaths.

        branch_id="trunk" 면 self를 그대로 반환 (회귀 0 보호).
        그 외 분기는 새 ProjectPaths 인스턴스를 만들고, 분기별 경로 필드만 override.

        in_worktree=True
            generator/evaluator subprocess가 cwd=worktree에서 사용하는 모드.
            spec/sprint-contract/plan-review는 self.project_root/artifacts/* 그대로
            (git이 worktree로 sync한 카피를 가리킴).
        in_worktree=False
            orchestrator/finalizer가 trunk에서 사용하는 모드.
            spec/sprint-contract/plan-review는 self.project_root/artifacts/* 그대로
            (= trunk 절대 경로).

        progress_log / qa_report / whisper_queue 는 **두 모드 모두 항상 trunk 절대
        경로**(artifacts/branches/{branch_id}/...)를 가리킨다. 분기별 .gitignore 영역
        이라 worktree에는 존재하지 않기 때문.
        """
        if branch_id == "trunk":
            return self

        base = self.project_root  # in_worktree=True면 worktree, False면 trunk
        bp = ProjectPaths(base)

        # 분기별 산출물은 항상 trunk artifacts/branches/{branch_id}/ 아래로 격리.
        trunk = self.trunk_root
        branch_dir = trunk / "artifacts" / "branches" / branch_id
        bp.progress_log = branch_dir / "progress-log.md"
        bp.qa_report = branch_dir / "qa-report.md"
        bp.whisper_queue = branch_dir / "whisper-queue.jsonl"
        return bp

    def ensure_branch_artifacts(self, branch_id: str) -> None:
        """artifacts/branches/{branch_id}/ 디렉토리 보장 (trunk 기준).

        generator/evaluator가 progress-log/qa-report/whisper-queue를 쓸 수 있도록
        분기 시작 전 호출.
        """
        if branch_id == "trunk":
            return
        (self.trunk_root / "artifacts" / "branches" / branch_id).mkdir(
            parents=True, exist_ok=True
        )
