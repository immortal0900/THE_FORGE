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

import pytest

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


# ── 큰 그림 1: ASK_USER 옵션 카드 + 응답 라우팅 ─────────────────────────────


_SAMPLE_ASK = {
    "type": "ask_user",
    "qid": "abc-123",
    "axiom_link": "a2",
    "situation": "큰 파일 처리 분기",
    "options": [
        {
            "id": "A",
            "label": "스트리밍",
            "icon": "🚀",
            "mechanism": "청크 단위 처리",
            "expected_metric": "100MB → 0.8s",
            "side_effect": "복구 코드 +50줄",
            "similar_case": "src/import.py:88",
        },
        {
            "id": "B",
            "label": "일괄 로드",
            "icon": "🛡️",
            "mechanism": "전체 로드 후 처리",
            "expected_metric": "100MB → 5.4s",
            "side_effect": "코드 단순",
            "similar_case": None,
        },
    ],
    "recommend": "A",
    "recommend_basis": "axiom a2 critical, sprint 범위 내",
}


def test_send_question_card_returns_false_when_missing_qid(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    ask = dict(_SAMPLE_ASK)
    ask["qid"] = ""
    assert notifier.send_question_card(ask) is False
    notifier._web.chat_postMessage.assert_not_called()


def test_send_question_card_returns_false_when_no_options(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    ask = dict(_SAMPLE_ASK)
    ask["options"] = []
    assert notifier.send_question_card(ask) is False


def test_send_question_card_renders_blocks(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100"}
    notifier.send_question_card(_SAMPLE_ASK)
    call = notifier._web.chat_postMessage.call_args
    blocks = call.kwargs.get("blocks") or []
    assert blocks[0]["type"] == "header"
    section_texts = " ".join(
        b.get("text", {}).get("text", "")
        for b in blocks if b.get("type") == "section"
    )
    assert "큰 파일 처리 분기" in section_texts
    assert "스트리밍" in section_texts
    assert "100MB → 0.8s" in section_texts
    assert "LLM 추천" in section_texts
    # 각 옵션마다 버튼 1개
    action_blocks = [b for b in blocks if b.get("type") == "actions"]
    assert len(action_blocks) == 1
    elements = action_blocks[0]["elements"]
    assert {e["action_id"] for e in elements} == {"forge_answer_A", "forge_answer_B"}
    # value 4-part 구조
    values = [e["value"] for e in elements]
    assert all(v.startswith("testproj::answer::abc-123::") for v in values)


def test_send_question_card_replies_to_thread(tmp_path):
    notifier, paths = _build_notifier(tmp_path)
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100"}
    notifier.notify("info", "root")
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700000001.000200"}

    notifier.send_question_card(_SAMPLE_ASK)
    second_call = notifier._web.chat_postMessage.call_args_list[1]
    assert second_call.kwargs.get("thread_ts") == "1700000000.000100"


def test_handle_interactive_writes_answer_file(tmp_path):
    """answer:: 분기 — 사용자 버튼 클릭 시 paths.answer_signal_for(qid)에 option_id 기록."""
    notifier, paths = _build_notifier(tmp_path)
    payload = {
        "actions": [
            {
                "action_id": "forge_answer_B",
                "value": "testproj::answer::abc-123::B",
            }
        ]
    }
    notifier._handle_interactive(payload)

    answer_file = paths.answer_signal_for("abc-123")
    assert answer_file.exists()
    assert answer_file.read_text(encoding="utf-8") == "B"


def test_handle_interactive_answer_filters_other_project(tmp_path):
    """다른 프로젝트의 answer 버튼 클릭은 무시 (멀티 프로젝트 라우팅)."""
    notifier, paths = _build_notifier(tmp_path)
    payload = {
        "actions": [
            {
                "action_id": "forge_answer_A",
                "value": "OTHERPROJ::answer::xyz-999::A",
            }
        ]
    }
    notifier._handle_interactive(payload)
    answer_file = paths.answer_signal_for("xyz-999")
    assert not answer_file.exists()


# ── 큰 그림 1 후속 (todo 8): 무기한 폴링 + /stop fallback ───────────────────


@pytest.mark.asyncio
async def test_on_question_returns_user_answer_from_file(tmp_path):
    """답변 파일이 있으면 콜백이 즉시 그 option_id 반환 + 파일 삭제."""
    from forge.orchestrator import _make_on_question

    notifier, paths = _build_notifier(tmp_path)
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700.000"}

    qid = "abc-123"
    answer_path = paths.answer_signal_for(qid)
    answer_path.write_text("B", encoding="utf-8")

    cb = _make_on_question(notifier, paths, notifier._config)
    ask = {
        "qid": qid,
        "options": [{"id": "A"}, {"id": "B"}],
        "recommend": "A",
    }
    answer = await cb(ask)
    assert answer == "B"
    assert not answer_path.exists()  # 소비된 파일은 삭제


@pytest.mark.asyncio
async def test_on_question_fallback_on_stop_signal(tmp_path):
    """/stop signal 감지 시 추천안 자동 채택 후 즉시 종료 (무기한 대기 중단)."""
    from forge.orchestrator import _make_on_question

    notifier, paths = _build_notifier(tmp_path)
    notifier._web.chat_postMessage.return_value = {"ok": True, "ts": "1700.000"}
    # 미리 stop signal 작성
    paths.stop_signal.write_text("", encoding="utf-8")

    cb = _make_on_question(notifier, paths, notifier._config)
    ask = {
        "qid": "stop-test",
        "options": [{"id": "A"}, {"id": "B"}],
        "recommend": "A",
    }
    answer = await cb(ask)
    assert answer == "A"  # 추천안 자동 채택


@pytest.mark.asyncio
async def test_on_question_fallback_when_no_qid(tmp_path):
    """qid 없는 ask 는 즉시 추천안 반환 (방어 코드)."""
    from forge.orchestrator import _make_on_question

    notifier, paths = _build_notifier(tmp_path)
    cb = _make_on_question(notifier, paths, notifier._config)
    answer = await cb({"qid": "", "options": [{"id": "A"}], "recommend": "A"})
    assert answer == "A"
