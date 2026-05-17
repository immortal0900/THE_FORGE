"""essence_axioms (본질) 파싱과 spec.md 인용.

본질 정책 (docs/plan-judgment-velocity.md 토대 3):
- 본질은 인간 사용자가 정의 (0→1). LLM이 자동 생성 X.
- 두 경로로 제공:
    1. docs/essence.md (또는 essence.yaml) 같은 파일
    2. 별도 본질 정의 skill의 출력 (artifacts/essence-axioms.yaml 캐시)
- **있으면 참고, 없으면 사용자 요청 그대로 진행 (강제 X)**.
- planner는 *읽기 전용 인용*. 자체 추가 / 수정 / 추출 금지.

토대 3 산출물:
- `Axiom` / `EssenceSource` 데이터 클래스
- `find_essence_file()` / `parse_essence()`: 입력
- `inject_essence_into_spec()`: spec.md 상단 frontmatter에 인용

큰 그림 2 산출물:
- `AxiomVerdict` 데이터 클래스
- `parse_qa_axiom_verdicts()`: qa-report.md의 Axiom Verdicts 표 파싱
- `build_verdict_card_blocks()`: Slack Block Kit Verdict Card 빌더
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
    # planner가 자동 추출하여 spec.md frontmatter에 박은 essence_axioms도 재인용 가능.
    # 이 후보를 마지막에 두어 사용자 제공 파일 우선.
    "artifacts/spec.md",
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

    실패 (파일 없음 / 파싱 오류 / axioms 비어있음) 시 None. 진단 메시지가
    필요한 호출자는 `try_parse_essence`를 직접 호출하라.
    """
    source, _err = try_parse_essence(path)
    return source


def try_parse_essence(path: Path) -> tuple[Optional[EssenceSource], Optional[str]]:
    """essence 파일 파싱 + 진단 메시지 반환.

    반환: (EssenceSource | None, error_message | None)
    - 성공: (source, None)
    - 실패: (None, "왜 실패했는지 사람 읽을 수 있는 한 줄")

    silent fail 금지 — 호출자가 사용자에게 진단을 전달할 수 있도록.
    예: spec.md frontmatter의 falsifiable_by 줄에 콤마+따옴표 나열로
    `expected <block end>, but found ','` 같은 YAML 문법 깨짐을 즉시 노출.
    """
    if not path.exists():
        return None, f"파일 없음: {path}"
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
        return None, f"지원 안 하는 확장자: {suffix} ({path.name})"

    if not yaml_text:
        return None, (
            f"{path.name}에 essence 정의를 찾지 못함 "
            f"(frontmatter 또는 ```yaml fenced 코드 없음)"
        )
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return None, (
            f"{path.name} YAML 파싱 실패: {exc}. "
            f"multiline 값은 literal block(|)으로 적어야 합니다 "
            f"(예: `falsifiable_by: |\\n  여러 줄 텍스트`)"
        )
    if not isinstance(data, dict):
        return None, f"{path.name} YAML 루트가 매핑이 아님 (type={type(data).__name__})"

    raw_axioms = data.get("essence_axioms") or data.get("axioms")
    if not isinstance(raw_axioms, list):
        return None, (
            f"{path.name}에 essence_axioms 또는 axioms 키가 없음 "
            f"(있는 키: {list(data.keys())})"
        )

    axioms: list[Axiom] = []
    skipped: list[str] = []
    for i, item in enumerate(raw_axioms):
        if not isinstance(item, dict):
            skipped.append(f"#{i} 매핑 아님")
            continue
        statement = str(item.get("statement", "")).strip()
        if not statement:
            skipped.append(f"#{i} statement 빔")
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
        return None, (
            f"{path.name}에 유효한 axiom 0개. skipped={skipped}"
        )

    source = EssenceSource(
        source=str(path),
        imported_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        axioms=axioms,
    )
    # 부분 skip은 경고로 알리되 성공으로 반환
    if skipped:
        return source, f"일부 axiom skip: {', '.join(skipped)}"
    return source, None


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
    진단 메시지가 필요하면 `try_load_essence_for_project` 사용.
    """
    source, _err = try_load_essence_for_project(project_root, hint_path)
    return source


def try_load_essence_for_project(
    project_root: Path,
    hint_path: Optional[str] = None,
) -> tuple[Optional[EssenceSource], Optional[str]]:
    """프로젝트의 essence 로드 + 진단 메시지.

    반환: (EssenceSource | None, error_message | None)
    - 성공: (source, None)
    - 표준 후보 모두 없음: (None, "essence 파일 없음 — docs/essence.md 등 확인")
    - 파일은 있지만 파싱 실패: (None, "spec.md YAML 파싱 실패: ...")

    silent fail 금지. Slack 카드 발송 시 None이면 인트로/진단 카드에 메시지
    노출 → 사용자가 chip이 비어 있는 이유 즉시 파악.
    """
    path = find_essence_file(project_root, hint_path)
    if path is None:
        return None, (
            f"essence 파일 없음 — docs/essence.md, docs/essence.yaml, "
            f"artifacts/essence-axioms.yaml, artifacts/spec.md(frontmatter) 중 "
            f"하나를 만드세요 (검색 루트: {project_root})"
        )
    return try_parse_essence(path)


# ── 큰 그림 2: Verdict Card 데이터 ──────────────────────────────────────────


@dataclass
class AxiomVerdict:
    """qa-report.md의 Axiom Verdicts 표 한 행. evaluator가 작성."""

    id: str
    statement: str
    verdict: str   # VERIFIED | PARTIAL | MISSING
    confidence: int   # 0-100
    inspection_method: str = ""
    measurements: str = ""
    evidence: str = ""
    counter_hypothesis: str = ""
    user_impact: str = ""
    recommend_action: str = ""


_VERDICT_SECTION_RE = re.compile(
    r"^##\s*Axiom\s*Verdicts\s*$(.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def _is_separator_row(cells: list[str]) -> bool:
    """`|---|---|...|` 같은 마크다운 표 구분선인지."""
    if not cells:
        return False
    return all(re.match(r"^:?-+:?$", c) for c in cells if c)


def _parse_confidence(raw: str) -> int:
    """'95', '95%', '95 %' 등에서 정수 추출. 실패 시 0."""
    m = re.search(r"(\d+)", raw or "")
    return int(m.group(1)) if m else 0


def parse_axiom_verdicts(source: Path) -> list[AxiomVerdict]:
    """어떤 마크다운 파일에서든 `## Axiom Verdicts` 섹션 표를 파싱.

    qa-report.md (evaluator 결과) / plan-review.md (planner 기획 자체 평가) 양쪽에서
    동일 형식의 verdict 표를 추출하기 위한 일반화 함수.
    표 없으면 빈 리스트. 헤더 행과 구분선은 자동 제외.
    """
    if not source.exists():
        return []
    text = source.read_text(encoding="utf-8", errors="replace")
    m = _VERDICT_SECTION_RE.search(text)
    if not m:
        return []
    section = m.group(1)

    verdicts: list[AxiomVerdict] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 10:
            continue
        if _is_separator_row(cells):
            continue
        # 헤더 행 감지: 첫 셀이 "id" 라벨
        if cells[0].lower() == "id":
            continue
        verdicts.append(
            AxiomVerdict(
                id=cells[0],
                statement=cells[1],
                verdict=cells[2].upper(),
                confidence=_parse_confidence(cells[3]),
                inspection_method=cells[4],
                measurements=cells[5],
                evidence=cells[6],
                counter_hypothesis=cells[7],
                user_impact=cells[8],
                recommend_action=cells[9],
            )
        )
    return verdicts


# 하위 호환 alias (기존 호출처 보호).
parse_qa_axiom_verdicts = parse_axiom_verdicts


# ── 큰 그림 2: Slack Verdict Card 렌더 ──────────────────────────────────────


_VERDICT_ICON = {"VERIFIED": "✅", "PARTIAL": "⚠️", "MISSING": "❌"}


def _confidence_bar(pct: int, length: int = 10) -> str:
    """0-100 → 유니코드 블록 게이지 바 (██████░░░░)."""
    pct = max(0, min(100, pct))
    filled = round(pct / 100 * length)
    return "█" * filled + "░" * (length - filled)


def build_verdict_card_blocks(
    verdicts: list[AxiomVerdict],
    *,
    recommendation: str = "",
    recommendation_reason: str = "",
    cost_estimate: str = "",
    essence: Optional["EssenceSource"] = None,
) -> list[dict]:
    """Slack Block Kit Verdict Card 빌더 (4섹션 양식).

    카드 구조: 본질당 4섹션으로 사용자가 8-10초에 판단 가능하게 정리.
    - header: 본질 부합도 (아이콘 분포 + N/M 카운트)
    - divider
    - 각 본질당 1블록:
        헤더(아이콘 + id + statement + confidence + 게이지)
        ① 본질 근접도 수치+근거 (confidence + evidence 인용 + inspection_method)
        ② 무슨 본질 (statement, 1줄)
        ③ 왜 이 본질이 필요한가 (essence.rationale 있으면 우선 + measurements)
        ④ 이게 깨지면 (user_impact + counter_hypothesis 반박)
        💡 LLM 추천: recommend_action
    - divider
    - 카드 전체 추천(planner/evaluator가 넘긴 recommendation) + 비용

    essence 인자: spec.md frontmatter의 essence_axioms 정보 (rationale 포함)를
    카드에 함께 노출하려면 호출자가 전달. 없으면 ③ 섹션이 measurements만 보여줌.
    10컬럼 표 양식은 유지 — 이 빌더가 *재구성*만 함.
    """
    blocks: list[dict] = []
    if not verdicts:
        return blocks

    # essence 가 있으면 id → Axiom 매핑 dict로 만들어 rationale을 ③에 결합.
    essence_by_id: dict[str, "Axiom"] = {}
    if essence is not None:
        for ax in essence.axioms:
            essence_by_id[ax.id] = ax

    counts: dict[str, int] = {"VERIFIED": 0, "PARTIAL": 0, "MISSING": 0}
    icons = ""
    for v in verdicts:
        icons += _VERDICT_ICON.get(v.verdict, "❓")
        counts[v.verdict] = counts.get(v.verdict, 0) + 1
    header_text = f"본질 부합도 {icons}  {counts['VERIFIED']}/{len(verdicts)} 본질"

    blocks.append(
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text[:150], "emoji": True},
        }
    )
    blocks.append({"type": "divider"})

    for v in verdicts:
        icon = _VERDICT_ICON.get(v.verdict, "❓")
        bar = _confidence_bar(v.confidence)
        # 본질 헤더 한 줄 (id + statement + verdict + confidence + 게이지)
        head_line = (
            f"{icon} *{v.id}*  {v.statement}    *{v.confidence}%*  `{bar}`"
        )

        # ① 본질 근접도 수치+근거
        prox_lines = [f"*① 본질 근접도*  {v.confidence}%  `{bar}`"]
        if v.evidence:
            prox_lines.append(f"  • _근거 (직접 인용)_: {v.evidence}")
        if v.inspection_method:
            prox_lines.append(f"  • _검사 방법_: {v.inspection_method}")
        if not v.evidence and not v.inspection_method:
            prox_lines.append("  • _(planner/evaluator가 근거를 채우지 않음)_")

        # ② 무슨 본질
        what_lines = ["*② 무슨 본질*", f"  {v.statement or '_(빈 항목)_'}"]

        # ③ 왜 이 본질이 필요한가 (essence.rationale 우선 + measurements 결합)
        why_lines = ["*③ 왜 이 본질이 필요한가*"]
        ax = essence_by_id.get(v.id)
        if ax is not None and ax.rationale:
            why_lines.append(f"  • _이유_: {ax.rationale}")
        if v.measurements:
            why_lines.append(f"  • _spec/코드 반영_: {v.measurements}")
        if (ax is None or not ax.rationale) and not v.measurements:
            why_lines.append("  • _(rationale/measurements 모두 빔)_")

        # ④ 이게 깨지면
        impact_lines = ["*④ 이게 깨지면*"]
        if v.user_impact:
            impact_lines.append(f"  • _사용자 영향_: {v.user_impact}")
        # 반박은 "없음"이라도 표기 (silent 금지)
        impact_lines.append(
            f"  • _반박 시나리오_: {v.counter_hypothesis or '없음'}"
        )

        sections = [
            head_line,
            "\n".join(prox_lines),
            "\n".join(what_lines),
            "\n".join(why_lines),
            "\n".join(impact_lines),
        ]
        if v.recommend_action:
            sections.append(f"💡 *LLM 추천*: `{v.recommend_action}`")
        text = "\n\n".join(sections)

        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text[:2900]},
            }
        )
        blocks.append({"type": "divider"})

    if recommendation or cost_estimate or recommendation_reason:
        parts: list[str] = []
        if recommendation:
            parts.append(f"💡 *LLM 추천 (카드 전체)*: {recommendation}")
        if recommendation_reason:
            parts.append(f"   _왜_: {recommendation_reason}")
        if cost_estimate:
            parts.append(f"💰 {cost_estimate}")
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(parts)[:2900]},
            }
        )

    return blocks


# ── Branch Capability Card 데이터 ─────────────────────────────────────────


@dataclass
class BranchCapability:
    """sprint-capabilities.md frontmatter의 branches[] 항목 한 개.

    planner Mode C가 sprint-contract.md와 1:1로 작성. orchestrator가 sprint
    시작 전 게이트에서 분기당 1장의 카드로 사용자에게 노출 → keep/drop/revise.
    """

    id: str
    title: str = ""
    tasks: list[str] = field(default_factory=list)
    related_essence: list[str] = field(default_factory=list)
    score_llm: int = 0
    score_floor: int = 0
    basis: str = ""
    what_is: str = ""
    why_needed: str = ""
    absence_impact: str = ""
    recommend_action: str = "keep"   # keep | drop | revise


def _coerce_str_list_loose(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def parse_branch_capabilities(source: Path) -> list[BranchCapability]:
    """sprint-capabilities.md frontmatter에서 BranchCapability 목록 추출.

    파일 없음 / frontmatter 없음 / branches 키 없음 → 빈 리스트 (silent fallback —
    planner 누락 케이스는 orchestrator가 별도 경고 처리).
    YAML 파싱 오류는 ValueError로 끌어올린다 (silent 금지).
    """
    if not source.exists():
        return []
    text = source.read_text(encoding="utf-8", errors="replace")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return []
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"sprint-capabilities.md frontmatter YAML 파싱 실패: {exc}") from exc
    if not isinstance(data, dict):
        return []
    raw_branches = data.get("branches")
    if not isinstance(raw_branches, list):
        return []

    caps: list[BranchCapability] = []
    for idx, item in enumerate(raw_branches):
        if not isinstance(item, dict):
            continue
        bid = str(item.get("id", "")).strip()
        if not bid:
            continue
        score_llm_raw = item.get("essence_score_llm", item.get("score_llm", 0))
        score_floor_raw = item.get("essence_score_floor", item.get("score_floor", 0))
        try:
            score_llm = max(0, min(100, int(score_llm_raw)))
        except (TypeError, ValueError):
            score_llm = 0
        try:
            score_floor = max(0, min(100, int(score_floor_raw)))
        except (TypeError, ValueError):
            score_floor = 0
        caps.append(
            BranchCapability(
                id=bid,
                title=str(item.get("title", "")).strip(),
                tasks=_coerce_str_list_loose(item.get("tasks")),
                related_essence=_coerce_str_list_loose(item.get("related_essence")),
                score_llm=score_llm,
                score_floor=score_floor,
                basis=str(item.get("essence_basis", item.get("basis", ""))).strip(),
                what_is=str(item.get("what_is", "")).strip(),
                why_needed=str(item.get("why_needed", "")).strip(),
                absence_impact=str(item.get("absence_impact", "")).strip(),
                recommend_action=str(item.get("recommend_action", "keep")).strip() or "keep",
            )
        )
    return caps


# ── Branch Capability Card 렌더 ───────────────────────────────────────────


def _proximity_icon(score: int) -> str:
    """0-100 근접도 → ✅⚠️❌ 시각 아이콘."""
    if score >= 80:
        return "✅"
    if score >= 60:
        return "⚠️"
    return "❌"


def build_branch_capability_intro_blocks(
    sprint_num: int,
    total: int,
    *,
    essence_diagnostic: Optional[str] = None,
) -> list[dict]:
    """분기 카드 N장 발송 전 인트로 1장. 'Sprint N 분기 승인 M개'.

    essence_diagnostic: essence 로드 실패/부분 skip 시 사용자에게 노출할
    한 줄 진단. None이면 평소 안내문만. 있으면 본질 chip이 왜 비어 있는지
    카드 인트로에 즉시 표시 — silent fail 방지.
    """
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🎯 Sprint {sprint_num} 분기 승인 — {total}개",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "각 분기별로 본질 부합도와 작업 범위를 확인하고 "
                        "[승인 / 분기 빼기 / 수정 요청] 중 하나를 선택하세요."
                    ),
                }
            ],
        },
    ]
    if essence_diagnostic:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"⚠️ *본질 로드 경고*\n"
                        f"{essence_diagnostic[:1800]}\n\n"
                        "_원인: 아래 chip이 `[a1: 본질 내용]`이 아니라 `[a1]`만 보이는 이유._"
                    ),
                },
            }
        )
    return blocks


def _format_essence_chips(
    ids: list[str],
    essence: Optional["EssenceSource"],
    *,
    max_statement_chars: int = 40,
) -> str:
    """본질 id 목록을 `[a1: 본질 내용]` chip 형태로 포맷.

    essence가 있으면 statement를 함께 노출하여 사용자가 카드에서 spec.md를
    들춰보지 않아도 id가 무슨 본질인지 즉시 파악. essence가 없거나 해당 id가
    essence에 없으면 그냥 `[a1]`로 폴백.
    """
    if not ids:
        return "(매핑 없음)"
    by_id: dict[str, "Axiom"] = {}
    if essence is not None:
        for ax in essence.axioms:
            by_id[ax.id] = ax
    chips: list[str] = []
    for aid in ids:
        ax = by_id.get(aid)
        if ax is None or not ax.statement:
            chips.append(f"[{aid}]")
            continue
        stmt = ax.statement.strip()
        if len(stmt) > max_statement_chars:
            stmt = stmt[: max_statement_chars - 1] + "…"
        chips.append(f"[{aid}: {stmt}]")
    return " ".join(chips)


def build_branch_capability_card_blocks(
    cap: BranchCapability,
    *,
    sprint_num: int,
    idx: int,
    total: int,
    essence: Optional["EssenceSource"] = None,
) -> list[dict]:
    """분기 1개 카드 (4섹션 + task 체크리스트 + 액션 버튼).

    Slack Block Kit 구조. 액션 버튼 value는 orchestrator 헬퍼가 project_name
    prefix와 합쳐 `{project}::branch_cap::{branch_id}::{action}` 형태로 만든다.

    essence 인자: 매핑된 본질 id를 `[a1: 본질 내용]` chip으로 풀어 노출 (없으면
    `[a1]` 폴백). 사용자가 카드만 보고 어느 본질인지 즉시 알 수 있게 함.
    """
    icon = _proximity_icon(max(cap.score_llm, cap.score_floor))
    essence_chips = _format_essence_chips(cap.related_essence, essence)

    blocks: list[dict] = []
    blocks.append(
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{icon} {cap.title or cap.id}  ({cap.id})  [{idx}/{total}]",
                "emoji": True,
            },
        }
    )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"관련 본질: {essence_chips}"}
            ],
        }
    )

    if cap.tasks:
        task_lines = "\n".join(f"  ☐ {t}" for t in cap.tasks)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*이 분기의 작업*\n{task_lines}"[:2900],
                },
            }
        )

    bar_llm = _confidence_bar(cap.score_llm)
    bar_floor = _confidence_bar(cap.score_floor)
    proximity_lines = [
        "*① 본질 근접도*",
        f"  • LLM 추정 *{cap.score_llm}%*  `{bar_llm}`",
        f"  • 규칙 하한 *{cap.score_floor}%*  `{bar_floor}`",
    ]
    if cap.related_essence:
        proximity_lines.append(
            f"  • 매핑 본질: {_format_essence_chips(cap.related_essence, essence)}"
        )
    if cap.basis:
        proximity_lines.append(f"  • _근거_: {cap.basis}")
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(proximity_lines)[:2900]},
        }
    )

    what_text = cap.what_is or "_(planner가 채우지 않음)_"
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*② 무슨 기능*\n{what_text}"[:2900]},
        }
    )

    why_text = cap.why_needed or "_(planner가 채우지 않음)_"
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*③ 왜 필요한가*\n{why_text}"[:2900]},
        }
    )

    absence_text = cap.absence_impact or "_(planner가 채우지 않음)_"
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*④ 이게 없으면*\n{absence_text}"[:2900]},
        }
    )

    if cap.recommend_action:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"💡 LLM 추천: `{cap.recommend_action}`",
                    }
                ],
            }
        )

    return blocks


# ── Sprint Approval Card (finalizer 직후) ──────────────────────────────────


@dataclass
class SprintApprovalData:
    """finalizer 산출물에서 추출한 Sprint Approval Card용 데이터.

    sprint_num: sprint 번호
    merged_branches: 머지된 분기 목록 (id, status, conflict_count)
    decisions: 사용된 decision-NNN 목록 (decision_id, summary)
    essence_scores: 분기 가중 본질 평균 (essence_id, avg_score, icon)
    next_sprint_preview: 다음 sprint 예고
    escalated_branches: escalate된 분기 (있으면)
    """

    sprint_num: int
    merged_branches: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    essence_scores: list[dict] = field(default_factory=list)
    next_sprint_preview: str = ""
    escalated_branches: list[str] = field(default_factory=list)


_DONE_BRANCHES_SECTION_RE = re.compile(
    r"^##\s*머지된\s*분기\s*$(.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
_DONE_DECISIONS_SECTION_RE = re.compile(
    r"^##\s*사용된\s*decision[^\n]*$(.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def _parse_done_branches(section: str) -> list[dict]:
    """`- branch-1 - 충돌 N건` 같은 라인 파싱."""
    rows: list[dict] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        body = line.lstrip("-").strip()
        m = re.match(r"([A-Za-z0-9_-]+)\s*[-:]\s*(.+)$", body)
        if not m:
            rows.append({"id": body, "status": "merged", "note": ""})
            continue
        bid = m.group(1)
        note = m.group(2).strip()
        conflict_match = re.search(r"충돌\s*(\d+)\s*건", note)
        conflict_count = int(conflict_match.group(1)) if conflict_match else 0
        status = "merged"
        if "abort" in note.lower() or "fail" in note.lower():
            status = "failed"
        rows.append(
            {
                "id": bid,
                "status": status,
                "conflict_count": conflict_count,
                "note": note,
            }
        )
    return rows


def _parse_done_decisions(section: str) -> list[dict]:
    rows: list[dict] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        body = line.lstrip("-").strip()
        m = re.match(r"(decision-\d+)\s*[-:]?\s*(.*)$", body, re.IGNORECASE)
        if not m:
            continue
        rows.append({"decision_id": m.group(1), "summary": m.group(2).strip()})
    return rows


def _aggregate_essence_scores(
    paths_per_branch: list[Path],
) -> list[dict]:
    """각 분기 qa-report.md의 Axiom Verdicts를 본질 id별로 평균.

    paths_per_branch: 분기별 qa-report.md 절대 경로 list (존재 안 하는 건 skip).
    반환: [{"id": "a1", "avg_score": 92, "icon": "✅", "weak_branches": [...]}]
    """
    bucket: dict[str, dict] = {}
    for qa_path in paths_per_branch:
        verdicts = parse_axiom_verdicts(qa_path)
        for v in verdicts:
            slot = bucket.setdefault(
                v.id,
                {"id": v.id, "statement": v.statement, "scores": [], "weak_branches": []},
            )
            slot["scores"].append(v.confidence)
            if v.confidence < 70:
                slot["weak_branches"].append(qa_path.parent.name)

    rows: list[dict] = []
    for axiom_id, slot in bucket.items():
        scores = slot["scores"]
        avg = round(sum(scores) / len(scores)) if scores else 0
        rows.append(
            {
                "id": axiom_id,
                "statement": slot["statement"],
                "avg_score": avg,
                "icon": _proximity_icon(avg),
                "weak_branches": slot["weak_branches"],
            }
        )
    rows.sort(key=lambda r: r["id"])
    return rows


def parse_sprint_approval(
    done_path: Path,
    *,
    sprint_num: int,
    branch_qa_paths: Optional[list[Path]] = None,
    next_sprint_preview: str = "",
    escalated_branches: Optional[list[str]] = None,
) -> Optional[SprintApprovalData]:
    """finalizer 산출물 `sprint-{N}-done.md` 파싱 + 분기 qa-report 본질 집계.

    done_path 없으면 None (orchestrator가 카드 발송 skip + 경고).
    """
    if not done_path.exists():
        return None
    text = done_path.read_text(encoding="utf-8", errors="replace")

    merged: list[dict] = []
    m_branches = _DONE_BRANCHES_SECTION_RE.search(text)
    if m_branches:
        merged = _parse_done_branches(m_branches.group(1))

    decisions: list[dict] = []
    m_decisions = _DONE_DECISIONS_SECTION_RE.search(text)
    if m_decisions:
        decisions = _parse_done_decisions(m_decisions.group(1))

    essence_scores: list[dict] = []
    if branch_qa_paths:
        essence_scores = _aggregate_essence_scores(branch_qa_paths)

    return SprintApprovalData(
        sprint_num=sprint_num,
        merged_branches=merged,
        decisions=decisions,
        essence_scores=essence_scores,
        next_sprint_preview=next_sprint_preview,
        escalated_branches=list(escalated_branches or []),
    )


def build_sprint_approval_card_blocks(data: SprintApprovalData) -> list[dict]:
    """Sprint Approval Card Block Kit 빌더 (finalizer 통합 직후).

    헤더 + 머지 결과 + 충돌 결정 + 본질 부합도 종합 + 다음 sprint 예고.
    버튼은 orchestrator 헬퍼가 첨부.
    """
    blocks: list[dict] = []
    blocks.append(
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🏁 Sprint {data.sprint_num} 통합 완료 — 승인 요청",
                "emoji": True,
            },
        }
    )

    if data.merged_branches:
        chips = []
        for b in data.merged_branches:
            icon = "✅"
            if b.get("status") == "failed":
                icon = "❌"
            elif b.get("conflict_count", 0) > 0:
                icon = "⚠️"
            note = ""
            if b.get("conflict_count", 0) > 0:
                note = f"(충돌 {b['conflict_count']}건)"
            chips.append(f"{b['id']} {icon}{note}")
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*머지된 분기*\n" + " / ".join(chips),
                },
            }
        )

    if data.escalated_branches:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*escalate된 분기*\n"
                        + ", ".join(data.escalated_branches)
                        + " (Planner 재호출 대기)"
                    ),
                },
            }
        )

    if data.decisions:
        deco_lines = "\n".join(
            f"  • `{d['decision_id']}` {d.get('summary', '')}" for d in data.decisions
        )
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*충돌 결정 (사용자 사후 검토)*\n{deco_lines}"[:2900],
                },
            }
        )

    if data.essence_scores:
        lines = ["*본질 부합도 종합 (분기 평균)*"]
        for e in data.essence_scores:
            line = f"  {e['icon']} *{e['id']}*  {e.get('statement', '')[:50]}  {e['avg_score']}%"
            if e["weak_branches"]:
                line += f"  _(약함: {', '.join(e['weak_branches'])})_"
            lines.append(line)
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]},
            }
        )

    if data.next_sprint_preview:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*다음 sprint 예정*\n"
                        + data.next_sprint_preview[:1000]
                    ),
                },
            }
        )

    blocks.append({"type": "divider"})
    return blocks
