"""~/.forge/registry.json — 디렉토리명 충돌 감지용 프로젝트 레지스트리."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def _registry_path() -> Path:
    return Path.home() / ".forge" / "registry.json"


def load_registry() -> list[dict]:
    path = _registry_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def check_collision(name: str, project_root: Path) -> Optional[dict]:
    """같은 name이 다른 path로 이미 등록됐으면 해당 엔트리 반환."""
    resolved = str(project_root.resolve())
    for entry in load_registry():
        if entry.get("name") == name and entry.get("path") != resolved:
            return entry
    return None


def register_project(name: str, project_root: Path) -> None:
    """레지스트리에 (name, path) 기록. 같은 path는 업데이트, 없으면 추가."""
    resolved = str(project_root.resolve())
    entries = load_registry()
    for entry in entries:
        if entry.get("path") == resolved:
            entry["name"] = name
            break
    else:
        entries.append({"name": name, "path": resolved})

    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
