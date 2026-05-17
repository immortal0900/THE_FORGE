"""Whisper 메시지 라우팅 + 알림 prefix (parallel-branches-design.md 단계 9).

병렬 분기 모드에서 사용자 평문 의견을 어느 분기 큐로 보낼지 결정한다.

라우팅 규칙 (사용자 명시적 prefix만 사용 - forge 정신 "사용자가 직접 결정"):
- `@branch-2 메시지` -> artifacts/branches/branch-2/whisper-queue.jsonl
- `@all 메시지` -> 모든 활성 분기 큐에 broadcast (+ trunk)
- prefix 없는 일반 메시지 -> trunk artifacts/.whisper-queue.jsonl
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import ProjectPaths

_PREFIX_RE = re.compile(r"^@([\w-]+)\s+(.*)$", re.DOTALL)


def parse_whisper_prefix(text: str) -> tuple[Optional[str], str]:
    """평문 메시지에서 `@target` prefix 추출.

    반환: (target, body)
    - target=None: prefix 없음 (trunk로 라우팅)
    - target="all": broadcast 대상
    - target="branch-N" 등: 해당 분기로 라우팅
    """
    if not text:
        return None, text
    m = _PREFIX_RE.match(text.strip())
    if not m:
        return None, text
    target = m.group(1).strip()
    body = m.group(2).strip()
    if not body:
        return None, text
    return target, body


def _whisper_queue_for(paths: ProjectPaths, branch_id: str) -> Path:
    if branch_id == "trunk":
        return paths.whisper_queue
    return (
        paths.trunk_root
        / "artifacts"
        / "branches"
        / branch_id
        / "whisper-queue.jsonl"
    )


def _list_active_branches(paths: ProjectPaths) -> list[str]:
    branches_dir = paths.trunk_root / "artifacts" / "branches"
    if not branches_dir.exists():
        return []
    return sorted(
        p.name
        for p in branches_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def append_whisper_routed(
    paths: ProjectPaths,
    text: str,
    *,
    timestamp: Optional[str] = None,
) -> list[str]:
    """평문 메시지를 prefix에 따라 적절한 큐(들)에 append."""
    if not text:
        return []
    target, body = parse_whisper_prefix(text)
    ts = timestamp or datetime.now().isoformat(timespec="seconds")

    if target is None:
        _append_one(paths, "trunk", body or text, ts, "trunk")
        return ["trunk"]

    if target == "all":
        active = _list_active_branches(paths)
        for bid in active:
            _append_one(paths, bid, body, ts, "all")
        _append_one(paths, "trunk", body, ts, "all")
        return active + ["trunk"]

    _append_one(paths, target, body, ts, target)
    return [target]


def _append_one(
    paths: ProjectPaths,
    branch_id: str,
    body: str,
    ts: str,
    routing_label: str,
) -> None:
    queue = _whisper_queue_for(paths, branch_id)
    try:
        queue.parent.mkdir(parents=True, exist_ok=True)
        record = {"at": ts, "text": body, "target": routing_label}
        with queue.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def prefix_message(message: str, branch_id: Optional[str]) -> str:
    """알림 메시지 앞에 `[branch-N] ` prefix 부착.

    branch_id가 None 또는 "trunk"면 메시지 그대로 (회귀 0).
    """
    if not branch_id or branch_id == "trunk":
        return message
    tag = f"[{branch_id}] "
    if not message:
        return tag.rstrip()
    return tag + message


class TokenBucketRateLimiter:
    """Slack 등 N개 동시 알림 폭주 방지용 단순 토큰 버킷.

    초당 N개 허용 + 짧은 burst 허용. 기본값: 1초당 2개 발사 (= 0.5초 간격) +
    burst 4개까지.
    """

    def __init__(self, rate_per_sec: float = 2.0, burst: int = 4):
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        self._rate = rate_per_sec
        self._capacity = max(1, int(burst))
        self._tokens: float = float(self._capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    def acquire(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                missing = 1.0 - self._tokens
                wait = missing / self._rate
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, max(0.05, deadline - time.monotonic())))
