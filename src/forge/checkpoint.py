"""Pydantic 모델 기반 체크포인트 복구."""

from __future__ import annotations

import json
from datetime import datetime
from enum import IntEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Phase(IntEnum):
    NONE = 0
    PLANNING = 1
    PLANNING_DONE = 2
    CONTRACT = 3
    CONTRACT_DONE = 4
    GENERATING = 5
    GENERATING_DONE = 6
    EVALUATING = 7
    EVALUATING_DONE = 8


class BranchState(BaseModel):
    """한 병렬 분기의 진행 상태 (parallel-branches-design.md 단계 1).

    Checkpoint.branches 리스트의 원소. 비어있으면(=리스트가 빈 채면) 단일 분기 모드
    (기존 forge 동작과 동일, 회귀 0).
    """

    branch_id: str
    phase: Phase = Phase.NONE
    sprint: int = 0
    consecutive_fails: int = 0
    worktree_path: str = ""
    git_branch: str = ""
    status: str = "active"  # "active" / "passed" / "failed" / "escalated"
    detail: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class Checkpoint(BaseModel):
    phase: Phase = Phase.NONE
    detail: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    branches: list[BranchState] = Field(default_factory=list)

    def should_run(self, target: Phase) -> bool:
        return self.phase <= target

    def advance(self, phase: Phase, detail: str = "") -> None:
        self.phase = phase
        self.detail = detail
        self.timestamp = datetime.now().isoformat()

    def note(self, detail: str) -> None:
        """Phase는 그대로 두고 detail과 timestamp만 갱신 (진행 상황 하트비트).

        장시간 단일 Phase 안에서 일어나는 중간 이벤트(subprocess 완료, 승인 대기 진입,
        수정 모드 실행 등)를 사용자에게 실시간 노출하기 위한 용도.
        """
        self.detail = detail
        self.timestamp = datetime.now().isoformat()

    def save(self, checkpoint_file: Path) -> None:
        checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "phase": int(self.phase),
            "phase_name": self.phase.name,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "branches": [
                {
                    "branch_id": b.branch_id,
                    "phase": int(b.phase),
                    "phase_name": b.phase.name,
                    "sprint": b.sprint,
                    "consecutive_fails": b.consecutive_fails,
                    "worktree_path": b.worktree_path,
                    "git_branch": b.git_branch,
                    "status": b.status,
                    "detail": b.detail,
                    "timestamp": b.timestamp,
                }
                for b in self.branches
            ],
        }
        checkpoint_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, checkpoint_file: Path) -> "Checkpoint":
        if not checkpoint_file.exists():
            return cls()
        try:
            data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            branches_data = data.get("branches", []) or []
            branches: list[BranchState] = []
            for item in branches_data:
                try:
                    branches.append(
                        BranchState(
                            branch_id=item.get("branch_id", ""),
                            phase=Phase(item.get("phase", 0)),
                            sprint=int(item.get("sprint", 0) or 0),
                            consecutive_fails=int(item.get("consecutive_fails", 0) or 0),
                            worktree_path=item.get("worktree_path", "") or "",
                            git_branch=item.get("git_branch", "") or "",
                            status=item.get("status", "active") or "active",
                            detail=item.get("detail", "") or "",
                            timestamp=item.get("timestamp", datetime.now().isoformat()),
                        )
                    )
                except (ValueError, TypeError):
                    continue
            return cls(
                phase=Phase(data.get("phase", 0)),
                detail=data.get("detail", ""),
                timestamp=data.get("timestamp", datetime.now().isoformat()),
                branches=branches,
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return cls()
