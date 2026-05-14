"""judgment.py 단위 테스트 — essence 파싱과 spec.md 인용.

본질 정책: 있으면 참고, 없으면 None (강제 X). 사용자 요청 그대로 진행.
"""

from __future__ import annotations

import textwrap

from forge.judgment import (
    Axiom,
    EssenceSource,
    find_essence_file,
    has_existing_essence_block,
    inject_essence_into_spec,
    load_essence_for_project,
    parse_essence,
    render_frontmatter,
)


# ── find_essence_file ───────────────────────────────────────────────────────


def test_find_essence_file_returns_none_when_missing(tmp_path):
    assert find_essence_file(tmp_path) is None


def test_find_essence_file_picks_standard_docs_essence_md(tmp_path):
    target = tmp_path / "docs" / "essence.md"
    target.parent.mkdir(parents=True)
    target.write_text("# placeholder", encoding="utf-8")
    found = find_essence_file(tmp_path)
    assert found is not None
    assert found.name == "essence.md"


def test_find_essence_file_hint_overrides_standard(tmp_path):
    custom = tmp_path / "my-essence.yaml"
    custom.write_text("essence_axioms: []", encoding="utf-8")
    found = find_essence_file(tmp_path, hint_path="my-essence.yaml")
    assert found is not None
    assert found.name == "my-essence.yaml"


def test_find_essence_file_hint_missing_returns_none(tmp_path):
    assert find_essence_file(tmp_path, hint_path="nope.md") is None


# ── parse_essence ───────────────────────────────────────────────────────────


def test_parse_essence_yaml_basic(tmp_path):
    f = tmp_path / "essence.yaml"
    f.write_text(
        textwrap.dedent(
            """
            essence_axioms:
              - id: a1
                statement: "오프라인에서 동작"
                rationale: "비행기/지하철"
                falsifiable_by: "네트워크 차단 테스트"
                weight: critical
              - id: a2
                statement: "1초 내 처리"
                weight: high
            """
        ).strip(),
        encoding="utf-8",
    )
    essence = parse_essence(f)
    assert essence is not None
    assert len(essence.axioms) == 2
    assert essence.axioms[0].id == "a1"
    assert essence.axioms[0].statement == "오프라인에서 동작"
    assert essence.axioms[0].weight == "critical"
    assert essence.axioms[1].id == "a2"
    assert essence.axioms[1].rationale == ""
    assert essence.source.endswith("essence.yaml")
    assert essence.imported_at  # ISO timestamp


def test_parse_essence_md_frontmatter(tmp_path):
    f = tmp_path / "essence.md"
    f.write_text(
        textwrap.dedent(
            """
            ---
            essence_axioms:
              - id: a1
                statement: "단일 zip export"
                falsifiable_by: "압축 파일 1개"
            ---

            # 본문은 사용자 메모. 무시됨.
            """
        ).strip(),
        encoding="utf-8",
    )
    essence = parse_essence(f)
    assert essence is not None
    assert len(essence.axioms) == 1
    assert essence.axioms[0].statement == "단일 zip export"


def test_parse_essence_md_yaml_fence(tmp_path):
    f = tmp_path / "essence.md"
    f.write_text(
        textwrap.dedent(
            """
            # 프로젝트 본질

            ```yaml
            essence_axioms:
              - id: a1
                statement: "본질 1"
            ```

            추가 설명...
            """
        ).strip(),
        encoding="utf-8",
    )
    essence = parse_essence(f)
    assert essence is not None
    assert essence.axioms[0].statement == "본질 1"


def test_parse_essence_aliases_axioms_key(tmp_path):
    """essence_axioms 대신 axioms 키도 허용."""
    f = tmp_path / "essence.yaml"
    f.write_text(
        textwrap.dedent(
            """
            axioms:
              - id: a1
                statement: "본질 1"
            """
        ).strip(),
        encoding="utf-8",
    )
    essence = parse_essence(f)
    assert essence is not None
    assert essence.axioms[0].id == "a1"


def test_parse_essence_returns_none_when_no_statement(tmp_path):
    f = tmp_path / "essence.yaml"
    f.write_text("essence_axioms: []", encoding="utf-8")
    assert parse_essence(f) is None


def test_parse_essence_skips_items_without_statement(tmp_path):
    f = tmp_path / "essence.yaml"
    f.write_text(
        textwrap.dedent(
            """
            essence_axioms:
              - id: skipme
              - id: a1
                statement: "유효한 본질"
            """
        ).strip(),
        encoding="utf-8",
    )
    essence = parse_essence(f)
    assert essence is not None
    assert len(essence.axioms) == 1
    assert essence.axioms[0].id == "a1"


def test_parse_essence_unsupported_extension_returns_none(tmp_path):
    f = tmp_path / "essence.json"
    f.write_text('{"essence_axioms": []}', encoding="utf-8")
    assert parse_essence(f) is None


# ── inject_essence_into_spec ────────────────────────────────────────────────


def _sample_essence() -> EssenceSource:
    return EssenceSource(
        source="docs/essence.md",
        imported_at="2026-05-15T00:00:00",
        axioms=[
            Axiom(id="a1", statement="본질 1", weight="critical"),
            Axiom(id="a2", statement="본질 2", rationale="이유", weight="high"),
        ],
    )


def test_inject_into_missing_spec_returns_false(tmp_path):
    spec = tmp_path / "spec.md"
    assert inject_essence_into_spec(spec, _sample_essence()) is False


def test_inject_into_spec_without_frontmatter_prepends(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("# 기존 본문\n\n내용...\n", encoding="utf-8")
    changed = inject_essence_into_spec(spec, _sample_essence())
    assert changed is True
    text = spec.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "essence_axioms:" in text
    assert "# 기존 본문" in text


def test_inject_into_spec_with_existing_frontmatter_merges(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text(
        textwrap.dedent(
            """
            ---
            project: demo
            owner: hwain
            ---
            # 본문
            """
        ).lstrip(),
        encoding="utf-8",
    )
    changed = inject_essence_into_spec(spec, _sample_essence())
    assert changed is True
    text = spec.read_text(encoding="utf-8")
    assert "project: demo" in text
    assert "owner: hwain" in text
    assert "essence_axioms:" in text


def test_inject_is_idempotent(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("# 본문\n", encoding="utf-8")
    essence = _sample_essence()
    assert inject_essence_into_spec(spec, essence) is True
    assert inject_essence_into_spec(spec, essence) is False  # 같은 내용 재주입은 변경 X


def test_has_existing_essence_block(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("# 본문\n", encoding="utf-8")
    assert has_existing_essence_block(spec) is False
    inject_essence_into_spec(spec, _sample_essence())
    assert has_existing_essence_block(spec) is True


def test_render_frontmatter_yaml_shape():
    fm = render_frontmatter(_sample_essence())
    assert fm.startswith("---\n")
    assert fm.endswith("---\n")
    assert "essence_source: docs/essence.md" in fm
    assert "essence_axioms:" in fm


# ── load_essence_for_project ────────────────────────────────────────────────


def test_load_essence_for_project_no_file_returns_none(tmp_path):
    """파일이 없으면 None — 강제 X, 사용자 요청 그대로 폴백 정책."""
    assert load_essence_for_project(tmp_path) is None


def test_load_essence_for_project_standard_location(tmp_path):
    target = tmp_path / "docs" / "essence.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        textwrap.dedent(
            """
            ---
            essence_axioms:
              - id: a1
                statement: "본질"
            ---
            """
        ).strip(),
        encoding="utf-8",
    )
    essence = load_essence_for_project(tmp_path)
    assert essence is not None
    assert essence.axioms[0].statement == "본질"


def test_load_essence_for_project_with_hint(tmp_path):
    custom = tmp_path / "my-axioms.yaml"
    custom.write_text(
        "essence_axioms:\n  - id: a1\n    statement: '본질'\n",
        encoding="utf-8",
    )
    essence = load_essence_for_project(tmp_path, hint_path="my-axioms.yaml")
    assert essence is not None
    assert essence.axioms[0].id == "a1"
