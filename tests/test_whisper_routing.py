"""whisper routing + notifier prefix + rate limit 단위 테스트 (단계 9)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from forge.config import ProjectPaths
from forge.notifier.routing import (
    TokenBucketRateLimiter,
    append_whisper_routed,
    parse_whisper_prefix,
    prefix_message,
)


@pytest.fixture
def fake_paths(tmp_path):
    paths = ProjectPaths(tmp_path)
    paths.ensure_artifacts()
    (paths.artifacts / "branches" / "branch-1").mkdir(parents=True, exist_ok=True)
    (paths.artifacts / "branches" / "branch-2").mkdir(parents=True, exist_ok=True)
    return paths


# parse_whisper_prefix


def test_parse_no_prefix_returns_none():
    target, body = parse_whisper_prefix("그냥 평문 메시지")
    assert target is None
    assert body == "그냥 평문 메시지"


def test_parse_branch_prefix():
    target, body = parse_whisper_prefix("@branch-2 안녕 코드 좀 봐줘")
    assert target == "branch-2"
    assert body == "안녕 코드 좀 봐줘"


def test_parse_all_prefix():
    target, body = parse_whisper_prefix("@all 잠시 멈춰")
    assert target == "all"
    assert body == "잠시 멈춰"


def test_parse_prefix_without_body_treated_as_plain():
    target, body = parse_whisper_prefix("@branch-1")
    assert target is None
    assert body == "@branch-1"


def test_parse_multiline_body():
    target, body = parse_whisper_prefix("@branch-1 첫 줄\n두 번째 줄")
    assert target == "branch-1"
    assert "두 번째 줄" in body


# append_whisper_routed


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_append_routes_branch_prefix_to_branch_queue(fake_paths):
    targets = append_whisper_routed(fake_paths, "@branch-2 hello")
    assert targets == ["branch-2"]

    queue = (
        fake_paths.trunk_root
        / "artifacts"
        / "branches"
        / "branch-2"
        / "whisper-queue.jsonl"
    )
    records = _read_jsonl(queue)
    assert len(records) == 1
    assert records[0]["text"] == "hello"
    assert records[0]["target"] == "branch-2"

    # trunk 큐는 비어 있어야 함
    assert _read_jsonl(fake_paths.whisper_queue) == []


def test_append_routes_plain_to_trunk(fake_paths):
    targets = append_whisper_routed(fake_paths, "그냥 메시지")
    assert targets == ["trunk"]

    records = _read_jsonl(fake_paths.whisper_queue)
    assert len(records) == 1
    assert records[0]["text"] == "그냥 메시지"
    assert records[0]["target"] == "trunk"


def test_append_routes_at_all_broadcasts(fake_paths):
    targets = append_whisper_routed(fake_paths, "@all 모두 봐줘")
    assert set(targets) == {"branch-1", "branch-2", "trunk"}

    for bid in ("branch-1", "branch-2"):
        q = (
            fake_paths.trunk_root
            / "artifacts"
            / "branches"
            / bid
            / "whisper-queue.jsonl"
        )
        records = _read_jsonl(q)
        assert records and records[0]["text"] == "모두 봐줘"
        assert records[0]["target"] == "all"

    trunk_records = _read_jsonl(fake_paths.whisper_queue)
    assert trunk_records and trunk_records[0]["text"] == "모두 봐줘"


def test_append_creates_queue_for_unseen_branch(fake_paths):
    """분기 디렉토리가 아직 없어도 큐는 자동 생성 (분기 곧 시작 가능)."""
    targets = append_whisper_routed(fake_paths, "@branch-9 즉시 적재")
    assert targets == ["branch-9"]

    q = (
        fake_paths.trunk_root
        / "artifacts"
        / "branches"
        / "branch-9"
        / "whisper-queue.jsonl"
    )
    assert q.exists()
    assert _read_jsonl(q)[0]["text"] == "즉시 적재"


# prefix_message


def test_prefix_message_no_branch_returns_as_is():
    assert prefix_message("generator 시작", None) == "generator 시작"
    assert prefix_message("generator 시작", "trunk") == "generator 시작"


def test_prefix_message_adds_branch_tag():
    assert (
        prefix_message("generator 시작", "branch-1")
        == "[branch-1] generator 시작"
    )


# TokenBucketRateLimiter


def test_rate_limiter_allows_burst_then_paces():
    """burst 만큼은 즉시, 그 이상은 sleep."""
    limiter = TokenBucketRateLimiter(rate_per_sec=10.0, burst=3)
    t0 = time.monotonic()
    for _ in range(3):
        assert limiter.acquire(timeout=1.0) is True
    burst_elapsed = time.monotonic() - t0
    # burst 3개는 사실상 즉시 (< 0.5s)
    assert burst_elapsed < 0.5

    # 4번째는 다음 토큰 (10 tokens/s -> ~0.1s) 대기
    t1 = time.monotonic()
    assert limiter.acquire(timeout=1.0) is True
    wait = time.monotonic() - t1
    assert wait >= 0.05
    assert wait < 0.5


def test_rate_limiter_timeout():
    """rate가 너무 느려서 timeout 안에 토큰 못 얻으면 False."""
    limiter = TokenBucketRateLimiter(rate_per_sec=0.1, burst=1)
    assert limiter.acquire(timeout=1.0) is True  # burst 소모
    assert limiter.acquire(timeout=0.3) is False


def test_rate_limiter_invalid_rate_rejected():
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate_per_sec=0.0)
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(rate_per_sec=-1.0)
