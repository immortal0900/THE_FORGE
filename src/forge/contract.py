"""Sprint Contract 파서 (parallel-branches-design.md 단계 4).

Planner가 작성한 `artifacts/sprint-contract.md`에서 `## Parallel Task Graph (YAML)`
섹션을 찾아 분기 명세(`BranchSpec`)로 변환한다.

설계 정신:
- 섹션 부재 = 직렬 1분기 모드. `[BranchSpec(id="trunk", ...)]` 1개 반환 → 호출부의
  단일 분기 분기문이 그대로 회귀 0 보호.
- 섹션 존재하지만 분기 1개만 정의 = 결과 list 길이 1. 호출부에서 `if len==1`로
  trunk 모드로 떨어진다 (worktree 안 만듦).
- YAML 파싱 실패는 silent fallback 금지 정신상 ValueError 예외로 끌어올린다.

장기 시뮬레이션: 향후 단계에서 finalizer가 BranchSpec.files_owned를 기반으로
머지 충돌 범위를 검증할 수 있도록, files_owned는 glob 패턴 list[str] 그대로
보존한다 (이번 단계에서는 parse만, 검증은 단계 7 finalizer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

import yaml


@dataclass
class BranchSpec:
    """한 병렬 분기의 명세.

    id: "branch-1" 형태의 분기 식별자. 직렬 모드일 때는 "trunk".
    title: 사람용 표시명 (예: "인증 모듈").
    tasks: 이 분기가 책임지는 작업 항목 list (체크박스 텍스트).
    depends_on: 먼저 끝나야 하는 다른 분기 id 목록 (현재 단계에서는 보관만).
    files_owned: 이 분기가 손댈 수 있는 파일 glob 패턴 list.
    """

    id: str
    title: str = ""
    tasks: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    files_owned: list[str] = field(default_factory=list)


_PARALLEL_HEADING_RE = re.compile(
    r"^\s{0,3}#{1,6}\s*Parallel\s+Task\s+Graph\s*\(YAML\)\s*$",
    re.IGNORECASE,
)


def _extract_parallel_section(text: str) -> str | None:
    """`## Parallel Task Graph (YAML)` 헤더 다음의 ```yaml``` 코드 블록 본문 반환.

    헤더 부재 → None.
    헤더는 있지만 코드 블록을 찾지 못하면 → None (silent fallback 금지 정신상
    호출부 parse_branches에서 ValueError로 끌어올려야 하나, 헤더가 빈 채로
    예고만 한 경우도 흔하므로 여기서는 None으로 신호하고, 호출부가 단일 분기로
    폴백한다).
    """
    lines = text.splitlines()
    heading_idx: int | None = None
    for i, line in enumerate(lines):
        if _PARALLEL_HEADING_RE.match(line):
            heading_idx = i
            break
    if heading_idx is None:
        return None

    # 헤더 다음부터 ```yaml ... ``` 코드 펜스 찾기. 다른 markdown 헤더가 먼저
    # 나오면 섹션 종료로 간주.
    in_fence = False
    fence_lines: list[str] = []
    for line in lines[heading_idx + 1:]:
        stripped = line.strip()
        if not in_fence:
            if stripped.startswith("```"):
                # ```yaml 또는 그냥 ```. 둘 다 허용.
                in_fence = True
                continue
            if stripped.startswith("#"):
                # 다음 헤더가 먼저 등장 — yaml 블록 없음
                return None
            # 헤더와 코드 펜스 사이의 산문은 무시
            continue
        # 펜스 내부
        if stripped.startswith("```"):
            break
        fence_lines.append(line)

    if not fence_lines:
        return None
    return "\n".join(fence_lines)


_BRANCH_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _coerce_str_list(value, *, field_name: str, branch_idx: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable):
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(
                    f"branches[{branch_idx}].{field_name}: 문자열 항목만 허용 "
                    f"(받은 타입: {type(item).__name__})"
                )
            if item.strip():
                out.append(item)
        return out
    raise ValueError(
        f"branches[{branch_idx}].{field_name}: list[str] 형식이어야 함 "
        f"(받은 타입: {type(value).__name__})"
    )


def parse_branches(sprint_contract_text: str) -> list[BranchSpec]:
    """sprint-contract.md 본문에서 분기 명세 목록을 추출.

    동작:
    1. `## Parallel Task Graph (YAML)` 섹션 부재 → [BranchSpec(id="trunk")] 반환.
    2. 섹션 존재 + 유효한 YAML + `branches: [...]` 키 → 각 항목을 BranchSpec으로.
    3. 섹션 존재 + YAML 파싱/스키마 위반 → ValueError 예외 (silent fallback 금지).

    회귀 보호: 빈 입력, None, 헤더만 있고 코드 블록 없는 경우 모두 trunk 1개로
    폴백 (계약상 "1개만이면 섹션 생략 가능"의 자연 확장).
    """
    if not sprint_contract_text or not sprint_contract_text.strip():
        return [BranchSpec(id="trunk")]

    block = _extract_parallel_section(sprint_contract_text)
    if block is None:
        return [BranchSpec(id="trunk")]

    try:
        parsed = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise ValueError(
            f"Parallel Task Graph YAML 파싱 실패: {exc}"
        ) from exc

    if parsed is None:
        # 빈 yaml 블록 — 섹션을 예고만 했음. 단일 분기 폴백.
        return [BranchSpec(id="trunk")]

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Parallel Task Graph YAML 루트는 매핑이어야 함 "
            f"(받은 타입: {type(parsed).__name__})"
        )

    branches_raw = parsed.get("branches")
    if branches_raw is None:
        # `branches:` 키 없음 → 단일 분기 폴백 (헤더만 있고 의도가 모호한 경우).
        return [BranchSpec(id="trunk")]
    if not isinstance(branches_raw, list):
        raise ValueError(
            f"`branches` 값은 list 형식이어야 함 "
            f"(받은 타입: {type(branches_raw).__name__})"
        )
    if not branches_raw:
        # 빈 리스트 → 단일 분기 폴백.
        return [BranchSpec(id="trunk")]

    specs: list[BranchSpec] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(branches_raw):
        if not isinstance(item, dict):
            raise ValueError(
                f"branches[{idx}]: 매핑이어야 함 "
                f"(받은 타입: {type(item).__name__})"
            )
        bid = item.get("id")
        if not isinstance(bid, str) or not bid.strip():
            raise ValueError(f"branches[{idx}].id: 비어있지 않은 문자열 필요")
        bid = bid.strip()
        if not _BRANCH_ID_RE.match(bid):
            raise ValueError(
                f"branches[{idx}].id={bid!r}: 영문/숫자/밑줄/하이픈만 허용"
            )
        if bid == "trunk":
            raise ValueError(
                f"branches[{idx}].id='trunk'은 예약어 (직렬 모드 전용)"
            )
        if bid in seen_ids:
            raise ValueError(f"branches[{idx}].id={bid!r}: 중복")
        seen_ids.add(bid)

        title = item.get("title", "") or ""
        if not isinstance(title, str):
            raise ValueError(
                f"branches[{idx}].title: 문자열이어야 함 "
                f"(받은 타입: {type(title).__name__})"
            )

        tasks = _coerce_str_list(item.get("tasks"), field_name="tasks", branch_idx=idx)
        depends_on = _coerce_str_list(
            item.get("depends_on"), field_name="depends_on", branch_idx=idx
        )
        files_owned = _coerce_str_list(
            item.get("files_owned"), field_name="files_owned", branch_idx=idx
        )

        specs.append(
            BranchSpec(
                id=bid,
                title=title.strip(),
                tasks=tasks,
                depends_on=depends_on,
                files_owned=files_owned,
            )
        )

    # depends_on 참조 무결성 검증 (정의되지 않은 id 참조 금지).
    for idx, spec in enumerate(specs):
        for dep in spec.depends_on:
            if dep not in seen_ids:
                raise ValueError(
                    f"branches[{idx}].depends_on={dep!r}: 정의되지 않은 분기 id"
                )

    return specs
