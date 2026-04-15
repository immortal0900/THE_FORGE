import pytest

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
