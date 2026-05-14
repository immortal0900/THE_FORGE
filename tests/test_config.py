
from forge.config import ForgeConfig, ProjectPaths


def test_defaults_when_no_toml(tmp_path, monkeypatch):
    for var in (
        "FORGE_TELEGRAM_BOT_TOKEN",
        "FORGE_TELEGRAM_CHAT_ID",
        "FORGE_LANGFUSE_PUBLIC_KEY",
        "FORGE_LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    config = ForgeConfig.load(tmp_path)
    assert config.max_sprint_minutes == 180
    assert config.telegram_enabled is False
    assert config.langfuse_enabled is False
    assert config.playwright_enabled is True


def test_load_from_toml(tmp_path, monkeypatch):
    for var in (
        "FORGE_TELEGRAM_BOT_TOKEN",
        "FORGE_TELEGRAM_CHAT_ID",
        "FORGE_LANGFUSE_PUBLIC_KEY",
        "FORGE_LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "forge.toml").write_text(
        """
[forge]
telegram_bot_token = "TOKEN"
telegram_chat_id = "123"
max_sprint_minutes = 60
langfuse_public_key = "pk"
langfuse_secret_key = "sk"
""",
        encoding="utf-8",
    )
    config = ForgeConfig.load(tmp_path)
    assert config.telegram_bot_token == "TOKEN"
    assert config.telegram_chat_id == "123"
    assert config.max_sprint_minutes == 60
    assert config.telegram_enabled is True
    assert config.langfuse_enabled is True


def test_env_var_takes_priority_over_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_TELEGRAM_BOT_TOKEN", "ENV_TOKEN")
    monkeypatch.setenv("FORGE_TELEGRAM_CHAT_ID", "ENV_CHAT")
    (tmp_path / "forge.toml").write_text(
        """
[forge]
telegram_bot_token = "TOML_TOKEN"
telegram_chat_id = "TOML_CHAT"
max_sprint_minutes = 90
""",
        encoding="utf-8",
    )
    config = ForgeConfig.load(tmp_path)
    assert config.telegram_bot_token == "ENV_TOKEN"
    assert config.telegram_chat_id == "ENV_CHAT"
    # toml-only 값은 반영됨
    assert config.max_sprint_minutes == 90


def test_env_var_only(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_LANGFUSE_PUBLIC_KEY", "pk-env")
    monkeypatch.setenv("FORGE_LANGFUSE_SECRET_KEY", "sk-env")
    config = ForgeConfig.load(tmp_path)  # forge.toml 없음
    assert config.langfuse_public_key == "pk-env"
    assert config.langfuse_enabled is True


def test_empty_toml_value_doesnt_clobber_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_TELEGRAM_BOT_TOKEN", "ENV_TOKEN")
    (tmp_path / "forge.toml").write_text(
        """
[forge]
telegram_bot_token = ""
""",
        encoding="utf-8",
    )
    config = ForgeConfig.load(tmp_path)
    assert config.telegram_bot_token == "ENV_TOKEN"


def test_project_paths(tmp_path):
    paths = ProjectPaths(tmp_path)
    assert paths.project_name == tmp_path.name
    paths.ensure_artifacts()
    assert paths.artifacts.is_dir()
    assert paths.specs.is_dir()
    assert paths.decisions.is_dir()
    assert paths.spec.parent == paths.artifacts


def test_current_sprint(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    assert paths.current_sprint() == 1
    (paths.artifacts / "sprint-1-done.md").write_text("x")
    (paths.artifacts / "sprint-2-done.md").write_text("x")
    assert paths.current_sprint() == 3


def test_load_from_pyproject_toml(tmp_path, monkeypatch):
    """v2.2: pyproject.toml [tool.forge] 에서 설정 로드."""
    for var in (
        "FORGE_TELEGRAM_BOT_TOKEN",
        "FORGE_TELEGRAM_CHAT_ID",
        "FORGE_LANGFUSE_PUBLIC_KEY",
        "FORGE_LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.forge]
max_sprint_minutes = 90
planner_max_turns = 20
max_total_minutes = 720
""",
        encoding="utf-8",
    )
    config = ForgeConfig.load(tmp_path)
    assert config.max_sprint_minutes == 90
    assert config.planner_max_turns == 20
    assert config.max_total_minutes == 720


def test_forge_toml_overrides_pyproject(tmp_path, monkeypatch):
    """forge.toml [forge] 값이 pyproject.toml [tool.forge]보다 우선."""
    for var in (
        "FORGE_TELEGRAM_BOT_TOKEN",
        "FORGE_TELEGRAM_CHAT_ID",
        "FORGE_LANGFUSE_PUBLIC_KEY",
        "FORGE_LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.forge]
max_sprint_minutes = 90
contract_max_turns = 8
""",
        encoding="utf-8",
    )
    (tmp_path / "forge.toml").write_text(
        """
[forge]
max_sprint_minutes = 60
""",
        encoding="utf-8",
    )
    config = ForgeConfig.load(tmp_path)
    assert config.max_sprint_minutes == 60   # forge.toml 우선
    assert config.contract_max_turns == 8    # pyproject.toml 값 유지


def test_new_safety_fields_defaults(tmp_path, monkeypatch):
    """v2.3 안전장치 필드 기본값 확인."""
    for var in (
        "FORGE_TELEGRAM_BOT_TOKEN",
        "FORGE_TELEGRAM_CHAT_ID",
        "FORGE_LANGFUSE_PUBLIC_KEY",
        "FORGE_LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    config = ForgeConfig.load(tmp_path)
    assert config.max_total_minutes == 1440
    assert config.max_consecutive_fails == 3
    assert config.max_total_sprints == 20


def test_signal_paths(tmp_path):
    """v2.3 시그널 경로 존재 확인."""
    paths = ProjectPaths(tmp_path)
    assert paths.eval_signal == paths.artifacts / ".eval-signal"
    assert paths.stop_signal == paths.artifacts / ".stop-signal"
