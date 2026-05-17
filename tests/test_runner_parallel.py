"""runner.run_agents_parallel 단위 테스트 (단계 5).

ClaudeCliSession을 실제로 띄우지 않고 monkeypatch로 ForgeAgentRunner.run을 가짜
RunResult 반환으로 대체. 동시 실행 + 세마포어 한도 + branch_id 라우팅 검증.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from forge.agents import runner as rn
from forge.agents.runner import ParallelBranchTask, RunResult, run_agents_parallel


def test_returns_empty_for_no_tasks():
    assert run_agents_parallel([], "generator", max_parallel=2) == {}


def test_runs_two_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """두 분기를 동시 실행하고 branch_id 키로 RunResult를 반환."""

    async def fake_run(self, initial_prompt: str) -> RunResult:
        # ClaudeCliSession을 안 띄우고 prompt만 받아 즉시 반환.
        return RunResult(returncode=0, stdout=f"OK::{initial_prompt[:20]}", stderr="")

    # start/close 가 호출되더라도 무해하도록 ClaudeCliSession도 가벼운 mock으로.
    class _FakeSession:
        def __init__(self, **kwargs):
            self.session_id = "test"
            self.agent = kwargs.get("agent")
            self.cwd = kwargs.get("cwd")
            self.max_turns = kwargs.get("max_turns")

    monkeypatch.setattr(rn, "ClaudeCliSession", _FakeSession)
    monkeypatch.setattr(rn.ForgeAgentRunner, "run", fake_run)

    tasks = [
        ParallelBranchTask(
            branch_id="branch-1",
            cwd=tmp_path / "wt-1",
            initial_prompt="branch-1 prompt content here",
        ),
        ParallelBranchTask(
            branch_id="branch-2",
            cwd=tmp_path / "wt-2",
            initial_prompt="branch-2 prompt content here",
        ),
    ]
    results = run_agents_parallel(tasks, "generator", max_parallel=2)

    assert set(results.keys()) == {"branch-1", "branch-2"}
    assert results["branch-1"].returncode == 0
    assert "branch-1 prompt" in results["branch-1"].stdout
    assert "branch-2 prompt" in results["branch-2"].stdout


def test_semaphore_caps_concurrency(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """max_parallel=1이면 4개 task가 동시에 1개씩만 진행되어야 한다."""
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_run(self, initial_prompt: str) -> RunResult:
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        async with lock:
            in_flight -= 1
        return RunResult(returncode=0, stdout="OK", stderr="")

    class _FakeSession:
        def __init__(self, **kwargs):
            self.session_id = "test"

    monkeypatch.setattr(rn, "ClaudeCliSession", _FakeSession)
    monkeypatch.setattr(rn.ForgeAgentRunner, "run", fake_run)

    tasks = [
        ParallelBranchTask(
            branch_id=f"b{i}",
            cwd=tmp_path / f"wt-{i}",
            initial_prompt="p",
        )
        for i in range(4)
    ]
    run_agents_parallel(tasks, "generator", max_parallel=1)
    assert peak == 1


def test_semaphore_allows_max_parallel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """max_parallel=3이면 4개 task 중 동시 3개까지 진행 가능."""
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_run(self, initial_prompt: str) -> RunResult:
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.1)
        async with lock:
            in_flight -= 1
        return RunResult(returncode=0, stdout="OK", stderr="")

    class _FakeSession:
        def __init__(self, **kwargs):
            self.session_id = "test"

    monkeypatch.setattr(rn, "ClaudeCliSession", _FakeSession)
    monkeypatch.setattr(rn.ForgeAgentRunner, "run", fake_run)

    tasks = [
        ParallelBranchTask(
            branch_id=f"b{i}",
            cwd=tmp_path / f"wt-{i}",
            initial_prompt="p",
        )
        for i in range(4)
    ]
    run_agents_parallel(tasks, "generator", max_parallel=3)
    assert peak == 3
