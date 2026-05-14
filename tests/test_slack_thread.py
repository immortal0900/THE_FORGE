"""SlackNotifier의 thread_ts 영구 저장 / reply 라우팅 단위 테스트.

큰 그림 3 (docs/plan-judgment-velocity.md):
- 첫 notify → root 메시지 + ts 저장
- 이후 notify → 같은 thread_ts에 reply
- 멀티 프로젝트는 각자 paths.slack_thread를 가지므로 자연 분리

실제 Slack API는 호출하지 않고 WebClient를 mock으로 대체.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


from forge.config import ForgeConfig, ProjectPaths


def _build_notifier(tmp_path: Path, slack_enabled: bool = True):
    """SlackNotifier를 mock된 WebClient로 wired up."""
    from forge.notifier.slack.adapter import SlackNotifier

    config = ForgeConfig(
        project_name="testproj",
        bot_display_name="TestBot",
        slack_bot_token="xoxb-test" if slack_enabled else "",
        slack_app_token="xapp-test" if slack_enabled else "",
        slack_channel="C12345" if slack_enabled else "",
    )
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    notifier = SlackNotifier(config, paths)
    notifier._web = MagicMock()
    return notifier, paths


def test_first_notify_records_root_thread_ts(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100"}

    sent = notifier.notify("info", "hello")
    assert sent is True
    assert notifier._thread_ts == "1700000000.000100"
    # 영구 저장 확인
    assert paths.slack_thread.exists()
    assert paths.slack_thread.read_text(encoding="utf-8").strip() == "1700000000.000100"
    # 첫 호출은 thread_ts 없이 보내야 root가 됨
    call = notifier._web.chat_postMessage.call_args
    assert "thread_ts" not in call.kwargs


def test_second_notify_replies_to_root_thread(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100"}

    notifier.notify("info", "root message")
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000001.000200"}
    notifier.notify("warning", "reply message")

    second_call = notifier._web.chat_postMessage.call_args_list[1]
    assert second_call.kwargs.get("thread_ts") == "1700000000.000100"
    # root는 여전히 첫 메시지 ts
    assert notifier._thread_ts == "1700000000.000100"


def test_thread_ts_persists_across_notifier_instances(tmp_path):
    """크래시 후 다음 forge run 에서도 같은 스레드 유지."""
    notifier1, paths = _build_notifier(tmp_path)
    notifier1._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100"}
    notifier1.notify("info", "root")

    # 새 SlackNotifier 인스턴스 → paths.slack_thread에서 복원
    from forge.notifier.slack.adapter import SlackNotifier

    notifier2 = SlackNotifier(notifier1._config, paths)
    notifier2._web = MagicMock()
    notifier2._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000002.000300"}

    assert notifier2._thread_ts == "1700000000.000100"
    notifier2.notify("info", "still same thread")
    call = notifier2._web.chat_postMessage.call_args
    assert call.kwargs.get("thread_ts") == "1700000000.000100"


def test_reset_thread_clears_file_and_state(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100"}
    notifier.notify("info", "root")
    assert paths.slack_thread.exists()

    notifier.reset_thread()
    assert notifier._thread_ts is None
    assert not paths.slack_thread.exists()

    # 다음 notify는 새 root가 됨
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000005.000999"}
    notifier.notify("info", "new root")
    assert notifier._thread_ts == "1700000005.000999"


def test_file_upload_uses_same_thread_ts(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100"}
    upload_file = tmp_path / "attach.md"
    upload_file.write_text("payload", encoding="utf-8")

    notifier.notify("info", "with file", file_path=upload_file)

    upload_call = notifier._web.files_upload_v2.call_args
    assert upload_call is not None
    # 같은 thread에 reply (root와 동일 ts)
    assert upload_call.kwargs.get("thread_ts") == "1700000000.000100"


def test_disabled_notifier_does_not_send(tmp_path):
    notifier, paths = _build_notifier(tmp_path, slack_enabled=False)
    notifier._web = None  # disabled simulation
    result = notifier.notify("info", "hello")
    assert result is False
    assert not paths.slack_thread.exists()


def test_load_thread_ts_handles_corrupted_file(tmp_path):
    """파일이 깨졌거나 빈 줄만 있으면 None."""
    from forge.notifier.slack.adapter import SlackNotifier

    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    paths.slack_thread.write_text("   \n", encoding="utf-8")

    config = ForgeConfig(slack_bot_token="x", slack_app_token="y", slack_channel="C")
    notifier = SlackNotifier(config, paths)
    assert notifier._thread_ts is None


# ── 큰 그림 2: send_verdict_card ────────────────────────────────────────────


_VERDICT_TABLE = (
    "## Axiom Verdicts\n\n"
    "| id | statement | verdict | confidence | im | meas | ev | ch | ui | rec |\n"
    "|----|-----------|---------|------------|-----|------|----|----|-----|-----|\n"
    "| a1 | 본질1 | VERIFIED | 95 | im1 | m1 | e1 | 없음 | u1 | accept |\n"
    "| a2 | 본질2 | PARTIAL | 60 | im2 | m2 | e2 | 위협 | u2 | partial_regen(a2) |\n"
)


def test_send_verdict_card_returns_false_when_no_verdicts(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    qa = paths.qa_report
    qa.write_text("## 종합 판정: PASS\n", encoding="utf-8")
    result = notifier.send_verdict_card(qa)
    assert result is False
    notifier._web.chat_postMessage.assert_not_called()


def test_send_verdict_card_sends_blocks_with_verdicts(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100"}
    qa = paths.qa_report
    qa.write_text(_VERDICT_TABLE, encoding="utf-8")

    result = notifier.send_verdict_card(
        qa,
        recommendation="a2만 부분 재실행",
        recommendation_reason="신뢰도 60→90 회복",
        cost_estimate="+12분",
    )
    assert result is True
    call = notifier._web.chat_postMessage.call_args
    blocks = call.kwargs.get("blocks") or []
    # header + divider + 2 axiom sections + divider + recommendation = 6+
    assert len(blocks) >= 5
    assert blocks[0]["type"] == "header"
    # 카드 텍스트에 axiom id가 들어있는지
    section_texts = " ".join(
        b.get("text", {}).get("text", "")
        for b in blocks if b.get("type") == "section"
    )
    assert "a1" in section_texts
    assert "a2" in section_texts
    assert "a2만 부분 재실행" in section_texts
    assert "+12분" in section_texts


def test_send_verdict_card_replies_to_existing_thread(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    # 미리 root 메시지 1개로 thread 형성
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100"}
    notifier.notify("info", "root")

    qa = paths.qa_report
    qa.write_text(_VERDICT_TABLE, encoding="utf-8")
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000001.000200"}
    notifier.send_verdict_card(qa)

    second_call = notifier._web.chat_postMessage.call_args_list[1]
    assert second_call.kwargs.get("thread_ts") == "1700000000.000100"


def test_send_verdict_card_attaches_buttons(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100"}
    qa = paths.qa_report
    qa.write_text(_VERDICT_TABLE, encoding="utf-8")
    notifier.send_verdict_card(qa, buttons=[["/resume", "/revise"], ["/exit"]])

    call = notifier._web.chat_postMessage.call_args
    blocks = call.kwargs.get("blocks") or []
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 1
    elements = action_blocks[0].get("elements", [])
    action_ids = {e.get("action_id") for e in elements}
    assert "forge_resume" in action_ids
    assert "forge_revise" in action_ids
    assert "forge_exit" in action_ids
