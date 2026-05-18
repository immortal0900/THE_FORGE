# essence_axioms 처리

이 프로젝트의 **변경 불가 약속** 3-7개. spec.md 상단 YAML frontmatter에 박힘.

## 두 경로

**경로 1 — orchestrator가 본질을 prompt에 inline 주입한 경우** (사용자가 docs/essence.md 등 외부 제공):
- spec.md 본문에 **원본 그대로** 반영. 표현·의미 재해석 금지. 자체 axiom 추가 금지
- frontmatter는 orchestrator가 자동 박음 → **건드리지 마라**

**경로 2 — 본질 prompt 없는 경우** (사용자가 평문 요청만):
- Mode A에서 spec.md 본문 또는 사용자 평문에서 본질 3-7개 자동 추출
- spec.md 최상단에 Edit 도구로 YAML frontmatter 박음

## frontmatter 스키마 (경로 2 시 직접 작성)

```yaml
---
essence_source: planner_extracted_from_user_request
essence_axioms:
  - id: a1
    statement: <한 줄, 동사형, 사용자 가치 기준>
    rationale: |
      <왜 본질인지 1-2줄, 본문의 어느 부분에서 도출했는지>
    falsifiable_by: |
      <어떻게 깨졌다고 입증할 수 있나. 여러 시나리오면 줄바꿈으로>
    weight: critical | high | medium
  - id: a2
    ...
---
```

## YAML 작성 규칙 (위반 시 파싱 실패 → 슬랙 카드에 빈 chip)

- 한 줄짜리 값: 콜론 뒤 공백 1칸. 따옴표 안 씀
- **여러 문장/콤마/따옴표 섞이는 값은 반드시 literal block(`|`)** — `falsifiable_by: "A", "B"` 같은 패턴은 YAML 파싱 실패
- 콜론, 화살표(→), 한자/이모지 포함 값도 literal block 권장
- 마지막 axiom 다음 `---` 닫기 라인 필수

## 본질 정의 원칙

- **금지**: 본문에 없는 항목 추가. 통상적 베스트프랙티스 자동 삽입. 테스트/문서/CI 같은 운영 항목을 본질로 두기 (그건 수단이지 본질 X)
- `falsifiable_by` 비면 Evaluator가 "검증 불가" 처리. planner는 추가 작업 X (사용자가 보강하도록)
