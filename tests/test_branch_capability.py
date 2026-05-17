"""Branch Capability Card + Sprint Approval Card 단위 테스트.

대상:
- judgment.parse_branch_capabilities (sprint-capabilities.md frontmatter 파싱)
- judgment.build_branch_capability_card_blocks (Slack Block Kit 구조)
- judgment.build_branch_capability_intro_blocks (인트로 카드)
- judgment.parse_sprint_approval (finalizer 산출물 + qa-report 본질 집계)
- judgment.build_sprint_approval_card_blocks (sprint 통합 승인 카드)
- orchestrator._consume_capability_drops (signal 파일 → keep/drop/revise 분류)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from forge.config import ProjectPaths
from forge.judgment import (
    BranchCapability,
    SprintApprovalData,
    build_branch_capability_card_blocks,
    build_branch_capability_intro_blocks,
    build_sprint_approval_card_blocks,
    parse_branch_capabilities,
    parse_sprint_approval,
)


# ── parse_branch_capabilities ──────────────────────────────────────────────


def test_parse_branch_capabilities_missing_file_returns_empty(tmp_path):
    assert parse_branch_capabilities(tmp_path / "missing.md") == []


def test_parse_branch_capabilities_no_frontmatter_returns_empty(tmp_path):
    p = tmp_path / "no-frontmatter.md"
    p.write_text("# 본문만 있음, frontmatter 없음", encoding="utf-8")
    assert parse_branch_capabilities(p) == []


def test_parse_branch_capabilities_no_branches_key_returns_empty(tmp_path):
    p = tmp_path / "no-branches.md"
    p.write_text(
        textwrap.dedent(
            """\
            ---
            sprint_number: 1
            ---
            본문
            """
        ),
        encoding="utf-8",
    )
    assert parse_branch_capabilities(p) == []


def test_parse_branch_capabilities_full_schema(tmp_path):
    p = tmp_path / "sprint-capabilities.md"
    p.write_text(
        textwrap.dedent(
            """\
            ---
            sprint_number: 1
            branches:
              - id: branch-1
                title: "URL 입력 + 진행률 표시"
                tasks:
                  - "URL 폼 컴포넌트"
                  - "다운로드 진행률 SSE 핸들러"
                related_essence: [a2, a3]
                essence_score_llm: 88
                essence_score_floor: 70
                essence_basis: |
                  본질 a2와 직접 부합.
                what_is: "URL 한 줄 입력 → 진행률 표시"
                why_needed: "사용자가 진행 상황을 모르면 재시도 비용 2배"
                absence_impact: "무응답 화면 → 본질 a2 위반"
                recommend_action: keep
              - id: branch-2
                title: "백엔드 큐"
                tasks: ["워커 큐 셋업"]
                related_essence: []
                essence_score_llm: 30
                essence_score_floor: 0
                essence_basis: ""
                what_is: ""
                why_needed: ""
                absence_impact: ""
                recommend_action: drop
            ---
            """
        ),
        encoding="utf-8",
    )
    caps = parse_branch_capabilities(p)
    assert len(caps) == 2
    c1, c2 = caps
    assert c1.id == "branch-1"
    assert c1.title == "URL 입력 + 진행률 표시"
    assert c1.tasks == ["URL 폼 컴포넌트", "다운로드 진행률 SSE 핸들러"]
    assert c1.related_essence == ["a2", "a3"]
    assert c1.score_llm == 88
    assert c1.score_floor == 70
    assert "본질 a2" in c1.basis
    assert c1.recommend_action == "keep"
    assert c2.id == "branch-2"
    assert c2.recommend_action == "drop"
    assert c2.related_essence == []


def test_parse_branch_capabilities_invalid_yaml_raises(tmp_path):
    p = tmp_path / "broken.md"
    p.write_text(
        textwrap.dedent(
            """\
            ---
            sprint_number: 1
            branches: [: not yaml
            ---
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        parse_branch_capabilities(p)


def test_parse_branch_capabilities_clamps_score_to_0_100(tmp_path):
    p = tmp_path / "out-of-range.md"
    p.write_text(
        textwrap.dedent(
            """\
            ---
            sprint_number: 1
            branches:
              - id: branch-1
                essence_score_llm: 9999
                essence_score_floor: -50
            ---
            """
        ),
        encoding="utf-8",
    )
    caps = parse_branch_capabilities(p)
    assert caps[0].score_llm == 100
    assert caps[0].score_floor == 0


# ── build_branch_capability_card_blocks ────────────────────────────────────


def _sample_cap() -> BranchCapability:
    return BranchCapability(
        id="branch-1",
        title="URL 입력 + 진행률 표시",
        tasks=["URL 폼 컴포넌트", "다운로드 진행률 SSE 핸들러"],
        related_essence=["a2", "a3"],
        score_llm=88,
        score_floor=70,
        basis="본질 a2와 직접 부합",
        what_is="URL 한 줄 입력 → 진행률 표시",
        why_needed="진행 상황을 모르면 재시도 비용 2배",
        absence_impact="무응답 화면 → 본질 a2 위반",
        recommend_action="keep",
    )


def test_build_branch_capability_card_has_4_sections_and_tasks():
    blocks = build_branch_capability_card_blocks(
        _sample_cap(), sprint_num=1, idx=1, total=3
    )
    # header(1) + context(1) + tasks section(1) + 4섹션(4) + 추천 context(1) = 8
    types = [b["type"] for b in blocks]
    assert types[0] == "header"
    assert types.count("section") >= 5  # tasks + 4섹션
    # 본질 근접도 ① 라벨이 본문 어딘가에 들어있어야 함
    joined = "".join(
        b.get("text", {}).get("text", "")
        for b in blocks
        if b.get("type") == "section"
    )
    assert "① 본질 근접도" in joined
    assert "② 무슨 기능" in joined
    assert "③ 왜 필요한가" in joined
    assert "④ 이게 없으면" in joined
    assert "LLM 추정 *88%*" in joined
    assert "규칙 하한 *70%*" in joined
    assert "URL 폼 컴포넌트" in joined  # task 체크리스트 노출


def test_build_branch_capability_card_handles_empty_optional_fields():
    cap = BranchCapability(id="branch-x", title="", tasks=[], related_essence=[])
    blocks = build_branch_capability_card_blocks(cap, sprint_num=1, idx=1, total=1)
    # 최소한 header + 4섹션은 항상 있어야 함
    assert blocks[0]["type"] == "header"
    joined = "".join(
        b.get("text", {}).get("text", "")
        for b in blocks
        if b.get("type") == "section"
    )
    assert "_(planner가 채우지 않음)_" in joined


def test_build_branch_capability_intro_has_title_with_sprint_and_count():
    blocks = build_branch_capability_intro_blocks(sprint_num=2, total=4)
    header_text = blocks[0]["text"]["text"]
    assert "Sprint 2" in header_text
    assert "4" in header_text


def test_build_branch_capability_card_essence_chips_inline_statement():
    """essence를 넘기면 본질 chip이 [a1: 본질 내용] 양식으로 노출되어야 한다.

    회귀 방지: 누가 chip 양식을 `[a1]`만으로 되돌리면 즉시 잡힘. 사용자
    결정(2026-05-17): id만 보면 무슨 본질인지 모르니 statement를 chip에 결합.
    """
    from forge.judgment import Axiom, EssenceSource

    essence = EssenceSource(
        source="docs/essence.md",
        imported_at="2026-05-17",
        axioms=[
            Axiom(id="a1", statement="오프라인에서 동작", weight="critical"),
            Axiom(id="a4", statement="단순함 우선", weight="high"),
            Axiom(id="a6", statement="MVP 우선", weight="critical"),
        ],
    )
    cap = BranchCapability(
        id="branch-1",
        title="설계 종이에 박기",
        related_essence=["a1", "a4", "a6"],
        score_llm=78,
        score_floor=100,
    )
    blocks = build_branch_capability_card_blocks(
        cap, sprint_num=1, idx=1, total=3, essence=essence
    )
    # context block(헤더 직후)에서 chip 양식 확인
    context_texts = [
        el["text"]
        for b in blocks
        if b.get("type") == "context"
        for el in b.get("elements", [])
    ]
    chip_text = "\n".join(context_texts)
    assert "[a1: 오프라인에서 동작]" in chip_text
    assert "[a4: 단순함 우선]" in chip_text
    assert "[a6: MVP 우선]" in chip_text


def test_build_branch_capability_card_essence_chips_fallback_when_no_essence():
    """essence가 없으면 `[a1]` 폴백 (statement 없이 id만)."""
    cap = BranchCapability(
        id="branch-1", related_essence=["a1", "a2"], score_llm=50, score_floor=70
    )
    blocks = build_branch_capability_card_blocks(
        cap, sprint_num=1, idx=1, total=1, essence=None
    )
    context_texts = [
        el["text"]
        for b in blocks
        if b.get("type") == "context"
        for el in b.get("elements", [])
    ]
    chip_text = "\n".join(context_texts)
    assert "[a1]" in chip_text
    assert "[a2]" in chip_text
    # statement는 없음 (essence 없으니 폴백)
    assert ":" not in chip_text.split("관련 본질:")[-1].split("\n")[0].replace("관련 본질:", "")


def test_build_branch_capability_intro_shows_essence_diagnostic():
    """essence 로드 실패 진단 메시지가 주어지면 인트로 카드에 명시 노출되어야 한다.

    회귀 방지: silent fail 금지. 사용자가 chip이 비어 있는 이유를 카드 안에서
    즉시 파악할 수 있어야 함.
    """
    diag = "spec.md YAML 파싱 실패: expected <block end>, but found ','"
    blocks = build_branch_capability_intro_blocks(
        sprint_num=1, total=3, essence_diagnostic=diag
    )
    section_texts = "\n".join(
        b["text"]["text"] for b in blocks if b.get("type") == "section"
    )
    assert "본질 로드 경고" in section_texts
    assert "expected <block end>" in section_texts


def test_build_branch_capability_intro_no_warning_when_essence_ok():
    """essence_diagnostic=None이면 경고 섹션이 추가되지 않는다 (silent 정상)."""
    blocks = build_branch_capability_intro_blocks(
        sprint_num=1, total=3, essence_diagnostic=None
    )
    section_texts = "\n".join(
        b["text"].get("text", "")
        for b in blocks
        if b.get("type") == "section"
    )
    assert "본질 로드 경고" not in section_texts


def test_build_branch_capability_card_chip_truncates_long_statement():
    """statement가 40자 넘으면 말줄임표로 잘림 (chip 길이 제어)."""
    from forge.judgment import Axiom, EssenceSource

    long_stmt = "이것은 매우 길고 자세한 본질 설명입니다 " * 3  # 60+ chars
    essence = EssenceSource(
        source="docs/essence.md",
        imported_at="2026-05-17",
        axioms=[Axiom(id="a1", statement=long_stmt, weight="critical")],
    )
    cap = BranchCapability(
        id="branch-1", related_essence=["a1"], score_llm=80, score_floor=100
    )
    blocks = build_branch_capability_card_blocks(
        cap, sprint_num=1, idx=1, total=1, essence=essence
    )
    text = "\n".join(
        el["text"]
        for b in blocks
        if b.get("type") == "context"
        for el in b.get("elements", [])
    )
    assert "…" in text  # 말줄임표
    # chip 자체 길이가 합리적 (40자 + 말줄임 + id + 괄호 정도)
    chip_part = [seg for seg in text.split() if seg.startswith("[a1:")][0]
    assert len(chip_part) <= 60


# ── parse_sprint_approval ──────────────────────────────────────────────────


def _write_done_md(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """\
            # Sprint 1 - DONE (Finalizer)

            ## 머지된 분기
            - branch-1 - 충돌 0건
            - branch-2 - 충돌 3건, decision-001/002/003 참조

            ## 사용된 decision-NNN 목록 (사용자 사후 검토)
            - decision-001 - 인증 미들웨어 합치기, branch-1 채택
            - decision-002 - import 순서 정리

            ## 분기별 PASS 점수
            - branch-1: PASS
            - branch-2: PASS
            """
        ),
        encoding="utf-8",
    )


def _write_branch_qa(path: Path, branch_id: str, score: int, axiom_id: str = "a1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            f"""\
            # QA Report - {branch_id}

            ## Axiom Verdicts

            | id | statement | verdict | confidence | inspection_method | measurements | evidence | counter_hypothesis | user_impact | recommend_action |
            |---|---|---|---|---|---|---|---|---|---|
            | {axiom_id} | 통과 검증 | VERIFIED | {score} | 측정함 | 12/12 통과 | 코드 인용 | 없음 | OK | accept |
            """
        ),
        encoding="utf-8",
    )


def test_parse_sprint_approval_returns_none_when_done_missing(tmp_path):
    assert parse_sprint_approval(tmp_path / "missing.md", sprint_num=1) is None


def test_parse_sprint_approval_full(tmp_path):
    done = tmp_path / "sprint-1-done.md"
    _write_done_md(done)
    qa1 = tmp_path / "branches" / "branch-1" / "qa-report.md"
    qa2 = tmp_path / "branches" / "branch-2" / "qa-report.md"
    _write_branch_qa(qa1, "branch-1", 90)
    _write_branch_qa(qa2, "branch-2", 60)

    data = parse_sprint_approval(
        done,
        sprint_num=1,
        branch_qa_paths=[qa1, qa2],
        next_sprint_preview="Sprint 2: 결과 저장",
    )
    assert data is not None
    assert data.sprint_num == 1
    assert len(data.merged_branches) == 2
    assert data.merged_branches[0]["id"] == "branch-1"
    assert data.merged_branches[1]["conflict_count"] == 3
    assert len(data.decisions) == 2
    assert data.decisions[0]["decision_id"] == "decision-001"
    assert len(data.essence_scores) == 1
    assert data.essence_scores[0]["id"] == "a1"
    assert data.essence_scores[0]["avg_score"] == 75  # (90+60)/2
    assert "branch-2" in data.essence_scores[0]["weak_branches"]  # <70
    assert data.next_sprint_preview == "Sprint 2: 결과 저장"


# ── build_sprint_approval_card_blocks ──────────────────────────────────────


def test_build_sprint_approval_card_renders_all_sections():
    data = SprintApprovalData(
        sprint_num=2,
        merged_branches=[
            {"id": "branch-1", "status": "merged", "conflict_count": 0, "note": ""},
            {"id": "branch-2", "status": "merged", "conflict_count": 2, "note": ""},
        ],
        decisions=[{"decision_id": "decision-001", "summary": "branch-1 채택"}],
        essence_scores=[
            {
                "id": "a1",
                "statement": "오프라인 동작",
                "avg_score": 85,
                "icon": "✅",
                "weak_branches": [],
            }
        ],
        next_sprint_preview="Sprint 3: 히스토리",
        escalated_branches=[],
    )
    blocks = build_sprint_approval_card_blocks(data)
    text = "".join(
        b.get("text", {}).get("text", "")
        for b in blocks
        if b.get("type") == "section"
    )
    assert "머지된 분기" in text
    assert "branch-1" in text and "branch-2" in text
    assert "decision-001" in text
    assert "본질 부합도 종합" in text
    assert "Sprint 3" in text
    assert blocks[0]["type"] == "header"
    assert "Sprint 2" in blocks[0]["text"]["text"]


def test_build_sprint_approval_card_shows_escalated_branches():
    data = SprintApprovalData(
        sprint_num=1,
        merged_branches=[{"id": "branch-1", "status": "merged", "conflict_count": 0}],
        escalated_branches=["branch-3"],
    )
    blocks = build_sprint_approval_card_blocks(data)
    text = "".join(
        b.get("text", {}).get("text", "")
        for b in blocks
        if b.get("type") == "section"
    )
    assert "escalate된 분기" in text
    assert "branch-3" in text


# ── orchestrator._consume_capability_drops ─────────────────────────────────


def test_consume_capability_drops_classifies_and_unlinks(tmp_path):
    # ProjectPaths를 직접 만들어서 capability_drops 경로 사용
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "artifacts").mkdir()
    paths = ProjectPaths(project_root)

    paths.capability_drops.write_text(
        "keep\tbranch-1\n"
        "drop\tbranch-2\n"
        "revise\tbranch-3\n"
        "drop\tbranch-1\n",  # branch-1 결정 번복: 마지막 drop이 유효
        encoding="utf-8",
    )

    from forge.orchestrator import _consume_capability_drops
    keeps, drops, revises = _consume_capability_drops(paths)
    assert keeps == []  # branch-1은 drop으로 덮였음
    assert sorted(drops) == ["branch-1", "branch-2"]
    assert revises == ["branch-3"]
    # 파일은 처리 후 unlink
    assert not paths.capability_drops.exists()


def test_consume_capability_drops_missing_file_returns_empties(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "artifacts").mkdir()
    paths = ProjectPaths(project_root)
    from forge.orchestrator import _consume_capability_drops
    assert _consume_capability_drops(paths) == ([], [], [])


# ── orchestrator._wait_for_sprint_done_signal ──────────────────────────────


def test_wait_for_sprint_done_signal_approve(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "artifacts").mkdir()
    paths = ProjectPaths(project_root)

    # 미리 신호 박아두면 즉시 approve 반환
    paths.sprint_done_signal.write_text("1", encoding="utf-8")
    from forge.orchestrator import _wait_for_sprint_done_signal
    result = _wait_for_sprint_done_signal(
        paths, sprint_num=1, poll_interval=0.01, max_seconds=2.0
    )
    assert result == "approve"
    # 신호 파일은 처리 후 unlink
    assert not paths.sprint_done_signal.exists()


def test_wait_for_sprint_done_signal_stop(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "artifacts").mkdir()
    paths = ProjectPaths(project_root)

    paths.stop_signal.write_text("stop", encoding="utf-8")
    from forge.orchestrator import _wait_for_sprint_done_signal
    result = _wait_for_sprint_done_signal(
        paths, sprint_num=1, poll_interval=0.01, max_seconds=2.0
    )
    assert result == "stop"


def test_wait_for_sprint_done_signal_revise(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "artifacts").mkdir()
    paths = ProjectPaths(project_root)

    paths.revise_signal.write_text("수정 지시문", encoding="utf-8")
    from forge.orchestrator import _wait_for_sprint_done_signal
    result = _wait_for_sprint_done_signal(
        paths, sprint_num=1, poll_interval=0.01, max_seconds=2.0
    )
    assert result == "revise"
    # revise_signal은 호출자가 읽으므로 unlink 안 함
    assert paths.revise_signal.exists()


def test_wait_for_sprint_done_signal_timeout(tmp_path):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "artifacts").mkdir()
    paths = ProjectPaths(project_root)

    from forge.orchestrator import _wait_for_sprint_done_signal
    result = _wait_for_sprint_done_signal(
        paths, sprint_num=1, poll_interval=0.01, max_seconds=0.1
    )
    assert result == "timeout"


# ── _run_multi_branch_sprint 시그니처 회귀 ────────────────────────────────


def test_run_multi_branch_sprint_returns_list_annotation():
    """다중 분기 모드 함수가 worktrees(list)를 반환하도록 시그니처가 확정돼야
    finalizer 통합 자리에서 호출자가 worktrees를 받아 finalizer에 전달 가능.
    회귀 방지: 누가 다시 -> None 으로 되돌리면 이 테스트가 즉시 잡음.
    """
    from forge import orchestrator
    annotations = orchestrator._run_multi_branch_sprint.__annotations__
    # from __future__ import annotations 로 인해 문자열로 저장됨
    ret = annotations.get("return")
    assert ret in ("list", list), (
        f"_run_multi_branch_sprint must return list[worktrees], got {ret!r}"
    )
