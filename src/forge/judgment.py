"""essence_axioms (본질) 파싱과 spec.md 인용.

본질 정책 (docs/plan-judgment-velocity.md 토대 3):
- 본질은 인간 사용자가 정의 (0→1). LLM이 자동 생성 X.
- 두 경로로 제공:
    1. docs/essence.md (또는 essence.yaml) 같은 파일
    2. 별도 본질 정의 skill의 출력 (artifacts/essence-axioms.yaml 캐시)
- **있으면 참고, 없으면 사용자 요청 그대로 진행 (강제 X)**.
- planner는 *읽기 전용 인용*. 자체 추가 / 수정 / 추출 금지.

이번 토대 3 산출물:
- `Axiom` / `EssenceSource` 데이터 클래스
- `find_essence_file()` / `parse_essence()`: 입력
- `inject_essence_into_spec()`: spec.md 상단 frontmatter에 인용
- (Verdict Card 빌더는 큰 그림 2 단계에서 추가)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Axiom:
    id: str
    statement: str
    rationale: str = ""
    falsifiable_by: str = ""
    weight: str = "medium"   # critical | high | medium


@dataclass
class EssenceSource:
    """사용자가 제공한 본질 묶음.

    source: 출처 (파일 경로 또는 'skill:<name>')
    imported_at: 마지막 인용 시각 (ISO 8601, mtime 기반)
    axioms: 본질 목록 (3-7개 권장)
    """

    source: str
    imported_at: str
    axioms: list[Axiom] = field(default_factory=list)


# ── 입력 ─────────────────────────────────────────────────────────────────────

_STANDARD_CANDIDATES = (
    "docs/essence.md",
    "docs/essence.yaml",
    "docs/essence.yml",
    "docs/essence-axioms.yaml",
    "artifacts/essence-axioms.yaml",
)


def find_essence_file(
    project_root: Path,
    hint_path: Optional[str] = None,
) -> Optional[Path]:
    """본질 파일 탐색.

    hint_path가 명시되면 그 경로만, 없으면 표준 후보 순회. 없으면 None.
    """
    if hint_path:
        p = (project_root / hint_path).resolve()
        return p if p.exists() else None
    for rel in _STANDARD_CANDIDATES:
        p = (project_root / rel).resolve()
        if p.exists():
            return p
    return None


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
_YAML_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)


def parse_essence(path: Path) -> Optional[EssenceSource]:
    """essence 파일 파싱.

    지원 형식:
    - .yaml / .yml : 파일 전체를 YAML로 해석
    - .md : frontmatter (--- ... ---) 또는 첫 ```yaml fenced code 안에서 YAML 추출

    실패 (파일 없음 / 파싱 오류 / axioms 비어있음) 시 None.
    """
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    yaml_text: Optional[str] = None
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        yaml_text = text
    elif suffix == ".md":
        m = _FRONTMATTER_RE.match(text)
        if m:
            yaml_text = m.group(1)
        else:
            fm = _YAML_FENCE_RE.search(text)
            if fm:
                yaml_text = fm.group(1)
    else:
        return None

    if not yaml_text:
        return None
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None

    raw_axioms = data.get("essence_axioms") or data.get("axioms")
    if not isinstance(raw_axioms, list):
        return None

    axioms: list[Axiom] = []
    for i, item in enumerate(raw_axioms):
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement", "")).strip()
        if not statement:
            continue
        axioms.append(
            Axiom(
                id=str(item.get("id", f"a{i + 1}")).strip(),
                statement=statement,
                rationale=str(item.get("rationale", "")).strip(),
                falsifiable_by=str(item.get("falsifiable_by", "")).strip(),
                weight=str(item.get("weight", "medium")).strip().lower() or "medium",
            )
        )

    if not axioms:
        return None

    return EssenceSource(
        source=str(path),
        imported_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        axioms=axioms,
    )


# ── spec.md 인용 ────────────────────────────────────────────────────────────


def _essence_to_dict(essence: EssenceSource) -> dict:
    return {
        "essence_source": essence.source,
        "essence_imported_at": essence.imported_at,
        "essence_axioms": [
            {
                "id": ax.id,
                "statement": ax.statement,
                "rationale": ax.rationale,
                "falsifiable_by": ax.falsifiable_by,
                "weight": ax.weight,
            }
            for ax in essence.axioms
        ],
    }


def render_frontmatter(essence: EssenceSource) -> str:
    """essence를 spec.md 상단 frontmatter 블록으로 직렬화 (`--- ... ---\\n`)."""
    body = yaml.safe_dump(
        _essence_to_dict(essence),
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    return f"---\n{body}\n---\n"


def has_existing_essence_block(spec_md: Path) -> bool:
    """spec.md에 이미 essence_axioms 블록이 있는지."""
    if not spec_md.exists():
        return False
    text = spec_md.read_text(encoding="utf-8", errors="replace")
    if not text.lstrip().startswith("---"):
        return False
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return False
    return "essence_axioms:" in m.group(1)


def inject_essence_into_spec(spec_md: Path, essence: EssenceSource) -> bool:
    """spec.md 상단 frontmatter에 essence 인용.

    동작:
    - spec.md 없음 → False (planner가 만들어야 함).
    - frontmatter 있음 → 그 안의 essence_* 키를 갱신, 다른 키는 보존.
    - frontmatter 없음 → 새 frontmatter를 본문 앞에 박음.

    반환: 실제로 파일이 변경됐는지 (idempotent: 동일 내용이면 False).
    """
    if not spec_md.exists():
        return False
    text = spec_md.read_text(encoding="utf-8", errors="replace")
    essence_dict = _essence_to_dict(essence)

    m = _FRONTMATTER_RE.match(text)
    if m:
        try:
            existing = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        merged = dict(existing)
        merged.update(essence_dict)
        new_yaml = yaml.safe_dump(merged, allow_unicode=True, sort_keys=False).strip()
        new_text = f"---\n{new_yaml}\n---\n" + text[m.end():]
    else:
        new_text = render_frontmatter(essence) + text

    if new_text == text:
        return False
    spec_md.write_text(new_text, encoding="utf-8")
    return True


def load_essence_for_project(
    project_root: Path,
    hint_path: Optional[str] = None,
) -> Optional[EssenceSource]:
    """프로젝트에 본질 파일 있으면 파싱, 없으면 None.

    orchestrator의 planning 진입 시 사용하는 단일 진입점.
    """
    path = find_essence_file(project_root, hint_path)
    if path is None:
        return None
    return parse_essence(path)
