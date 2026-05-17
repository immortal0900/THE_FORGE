"""contract.parse_branches 단위 테스트 (parallel-branches-design.md 단계 4).

테스트 케이스:
- 섹션 부재 → [BranchSpec(id="trunk")] 1개 (회귀 보호)
- 단일 분기만 정의된 YAML → 1개 BranchSpec
- 2-4 분기 YAML → 그대로 파싱
- 잘못된 YAML 거부 (ValueError)
- 스키마 위반 거부 (id 누락, 중복, 예약어, 정의되지 않은 depends_on 등)
"""

from __future__ import annotations

import pytest

from forge.contract import BranchSpec, parse_branches


# ── 섹션 부재 → trunk 폴백 ──────────────────────────────────────────────────


def test_empty_text_returns_trunk():
    result = parse_branches("")
    assert result == [BranchSpec(id="trunk")]


def test_whitespace_only_returns_trunk():
    result = parse_branches("   \n\n  \t  \n")
    assert result == [BranchSpec(id="trunk")]


def test_no_parallel_section_returns_trunk():
    text = """# Sprint 1

## Tasks
- [ ] item one
- [ ] item two

## Notes
some notes
"""
    result = parse_branches(text)
    assert len(result) == 1
    assert result[0].id == "trunk"


def test_heading_without_yaml_block_returns_trunk():
    """헤더만 있고 코드 블록이 없으면 단일 분기로 폴백."""
    text = """# Sprint 1

## Parallel Task Graph (YAML)

(이 sprint는 분할 불가)

## Other section
"""
    result = parse_branches(text)
    assert len(result) == 1
    assert result[0].id == "trunk"


def test_empty_yaml_block_returns_trunk():
    text = """## Parallel Task Graph (YAML)

```yaml
```
"""
    result = parse_branches(text)
    assert len(result) == 1
    assert result[0].id == "trunk"


def test_branches_key_missing_returns_trunk():
    text = """## Parallel Task Graph (YAML)

```yaml
notes: nothing here
```
"""
    result = parse_branches(text)
    assert len(result) == 1
    assert result[0].id == "trunk"


def test_empty_branches_list_returns_trunk():
    text = """## Parallel Task Graph (YAML)

```yaml
branches: []
```
"""
    result = parse_branches(text)
    assert len(result) == 1
    assert result[0].id == "trunk"


# ── 단일 분기 명시 ──────────────────────────────────────────────────────────


def test_single_branch_yaml():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: branch-1
    title: "단독 분기"
    tasks: ["t1", "t2"]
    files_owned: ["src/x/*"]
```
"""
    result = parse_branches(text)
    assert len(result) == 1
    assert result[0].id == "branch-1"
    assert result[0].title == "단독 분기"
    assert result[0].tasks == ["t1", "t2"]
    assert result[0].files_owned == ["src/x/*"]
    assert result[0].depends_on == []


# ── 2-4 분기 ─────────────────────────────────────────────────────────────────


def test_two_branches():
    text = """# Sprint 1

## Parallel Task Graph (YAML)

```yaml
branches:
  - id: branch-1
    title: "Auth"
    tasks:
      - "OAuth 콜백"
      - "세션 토큰"
    depends_on: []
    files_owned:
      - "src/auth/*"
      - "tests/auth/*"
  - id: branch-2
    title: "DB"
    tasks:
      - "migrations"
    depends_on: []
    files_owned:
      - "src/db/*"
```
"""
    result = parse_branches(text)
    assert len(result) == 2
    assert [b.id for b in result] == ["branch-1", "branch-2"]
    assert result[0].title == "Auth"
    assert result[0].tasks == ["OAuth 콜백", "세션 토큰"]
    assert result[0].files_owned == ["src/auth/*", "tests/auth/*"]
    assert result[1].title == "DB"
    assert result[1].files_owned == ["src/db/*"]


def test_four_branches():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: b1
  - id: b2
  - id: b3
  - id: b4
```
"""
    result = parse_branches(text)
    assert len(result) == 4
    assert [b.id for b in result] == ["b1", "b2", "b3", "b4"]


def test_depends_on_reference():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: a
  - id: b
    depends_on: [a]
```
"""
    result = parse_branches(text)
    assert result[1].depends_on == ["a"]


def test_string_tasks_coerced_to_list():
    """tasks: "foo" 같은 단일 문자열도 허용 (list로 정규화)."""
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: x
    tasks: hello
```
"""
    result = parse_branches(text)
    assert result[0].tasks == ["hello"]


# ── 잘못된 YAML / 스키마 위반 ───────────────────────────────────────────────


def test_invalid_yaml_raises():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: x
    title: "unclosed
```
"""
    with pytest.raises(ValueError, match="YAML"):
        parse_branches(text)


def test_root_not_mapping_raises():
    text = """## Parallel Task Graph (YAML)

```yaml
- just a list
- not a mapping
```
"""
    with pytest.raises(ValueError, match="매핑"):
        parse_branches(text)


def test_branches_not_list_raises():
    text = """## Parallel Task Graph (YAML)

```yaml
branches: "not a list"
```
"""
    with pytest.raises(ValueError, match="list"):
        parse_branches(text)


def test_missing_id_raises():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - title: "no id"
```
"""
    with pytest.raises(ValueError, match=r"\.id"):
        parse_branches(text)


def test_empty_id_raises():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: ""
```
"""
    with pytest.raises(ValueError, match=r"\.id"):
        parse_branches(text)


def test_invalid_id_chars_raises():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: "has spaces"
```
"""
    with pytest.raises(ValueError, match="영문/숫자"):
        parse_branches(text)


def test_trunk_reserved_raises():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: trunk
```
"""
    with pytest.raises(ValueError, match="trunk"):
        parse_branches(text)


def test_duplicate_id_raises():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: x
  - id: x
```
"""
    with pytest.raises(ValueError, match="중복"):
        parse_branches(text)


def test_unknown_depends_on_raises():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: a
    depends_on: [does-not-exist]
```
"""
    with pytest.raises(ValueError, match="정의되지 않은"):
        parse_branches(text)


def test_tasks_non_string_item_raises():
    text = """## Parallel Task Graph (YAML)

```yaml
branches:
  - id: a
    tasks: [123]
```
"""
    with pytest.raises(ValueError, match="문자열"):
        parse_branches(text)
