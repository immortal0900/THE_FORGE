"""ClaudeCliSession 단위 테스트.

토대 2 안전장치 검증: 자식 env에서 ANTHROPIC_API_KEY 가 제거되는지.
issue #37686 ($1,800 청구 사고) 방지.
"""

from __future__ import annotations

import pytest

from forge.agents.cli_session import ClaudeCliSession, build_child_env


def test_build_child_env_removes_api_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-be-removed")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "should-also-be-removed")
    monkeypatch.setenv("OTHER_VAR", "should-remain")
    env = build_child_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env.get("OTHER_VAR") == "should-remain"


def test_build_child_env_passes_oauth_token_through(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-value")
    env = build_child_env()
    assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "oauth-value"


def test_build_child_env_accepts_explicit_base():
    base = {
        "ANTHROPIC_API_KEY": "x",
        "ANTHROPIC_AUTH_TOKEN": "y",
        "FOO": "bar",
        "CLAUDE_CODE_OAUTH_TOKEN": "tok",
    }
    env = build_child_env(base)
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env.get("FOO") == "bar"
    assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "tok"


def test_session_id_default_is_uuid_str(tmp_path):
    sess = ClaudeCliSession(agent="planner", cwd=tmp_path)
    assert isinstance(sess.session_id, str) and len(sess.session_id) >= 32


def test_session_id_explicit_kept(tmp_path):
    sess = ClaudeCliSession(
        agent="planner", cwd=tmp_path, session_id="abc-123"
    )
    assert sess.session_id == "abc-123"


@pytest.mark.asyncio
async def test_send_user_message_before_start_raises(tmp_path):
    sess = ClaudeCliSession(agent="planner", cwd=tmp_path)
    with pytest.raises(Exception):
        await sess.send_user_message("hello")
