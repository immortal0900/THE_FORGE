"""프로젝트명/봇 표시명 자동 추론.

디렉토리명에서 안전한 project_name을 만들고, 그로부터 Slack username을 생성한다.
"""

from __future__ import annotations

import re
from pathlib import Path


def infer_project_name(project_root: Path) -> str:
    """디렉토리명을 snake_case project_name으로 정규화.

    예: "obsidian-sync" → "obsidian_sync", "My Project" → "my_project"
    """
    raw = project_root.name
    s = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    return s or "project"


def to_pascal_case(snake: str) -> str:
    """snake_case → PascalCase. 예: "obsidian_sync" → "ObsidianSync"."""
    return "".join(part.capitalize() for part in snake.split("_") if part) or "Project"


def infer_bot_display_name(project_name: str) -> str:
    """Slack chat_postMessage의 username 값. 예: "obsidian_sync" → "Forge-ObsidianSync"."""
    return f"Forge-{to_pascal_case(project_name)}"
