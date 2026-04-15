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


class Checkpoint(BaseModel):
    phase: Phase = Phase.NONE
    detail: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    def should_run(self, target: Phase) -> bool:
        return self.phase <= target

    def advance(self, phase: Phase, detail: str = "") -> None:
        self.phase = phase
        self.detail = detail
        self.timestamp = datetime.now().isoformat()

    def save(self, checkpoint_file: Path) -> None:
        checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "phase": int(self.phase),
            "phase_name": self.phase.name,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }
        checkpoint_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, checkpoint_file: Path) -> "Checkpoint":
        if not checkpoint_file.exists():
            return cls()
        try:
            data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            return cls(
                phase=Phase(data.get("phase", 0)),
                detail=data.get("detail", ""),
                timestamp=data.get("timestamp", datetime.now().isoformat()),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return cls()
