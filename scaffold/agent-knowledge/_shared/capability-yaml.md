# sprint-capabilities.md 작성

**파일 위치**: `artifacts/sprint-capabilities.md`. frontmatter YAML 단일 소스 + 본문은 사람 친화 미러(선택). Write 도구로 생성.

**핵심 규칙**: sprint-contract.md의 분기(branch) 1개 = capabilities[] 1개. 단일 분기(직렬) 모드면 `id: trunk` 1개. 사용자가 카드 1장만 보고 8-10초에 keep/drop/revise 판단 가능해야 한다 → 각 필드에 **내용 자체**.

## frontmatter 스키마

```yaml
---
sprint_number: 1
branches:
  - id: branch-1                # contract.py BranchSpec.id와 1:1 매핑
    title: "URL 입력 + 진행률 표시"
    tasks:
      - "URL 폼 컴포넌트"
      - "다운로드 진행률 SSE 핸들러"
    related_essence: [a2, a3]   # 매핑된 본질 id 목록
    essence_score_llm: 88       # 0-100. critical=80+, high=60-80, medium=40-60
    essence_score_floor: 70     # max(매핑 본질 weight 환산). critical=100, high=70, medium=40
    essence_basis: |
      본질 a2(시각차분 측정)와 직접 부합. a3(노이즈 차단)에도 약하게 기여.
      이유: 사용자가 입력→결과 흐름을 끊지 않고 보게 함.
    what_is: "URL 한 줄 입력 → 다운로드 진행률 실시간 표시"
    why_needed: |
      본질 a2의 이유: "어디까지 진행됐는지 모르면 새로고침/재시도로 불필요 비용 유발."
      spec §사용자 시나리오 1과 일치.
    absence_impact: |
      입력 후 무응답 화면 → 진행 중인지 죽었는지 모름. 재요청으로 비용 2배. 본질 a2 위반.
    recommend_action: keep      # keep | drop | revise
---
```

## 필드별 핵심

- `essence_score_llm`: weight + rationale + 사용자 시나리오 종합한 본질 부합도 추정
- `essence_score_floor`: 규칙 기반 하한선 (매핑 본질 weight 환산값 중 최댓값)
- `essence_basis`: 어느 본질 statement에 어떻게 부합하는지 자연어 1-2줄. 본질 id 만 적지 말고 **왜 부합하는지 이유**
- `what_is`: 분기가 만들 기능 한 문장 직접 묘사 (위치만 지시 X)
- `why_needed`: 본질 rationale + spec 사용자 시나리오 인용. 위치 X, 내용 O
- `absence_impact`: 빠지면 사용자에게 일어날 일을 결과로 묘사. 어느 본질 깨지는지도 명시
- `recommend_action`: keep(본질 부합 명확) / drop(본질 무관) / revise(부분 보강 필요)

## 금지

- `essence_basis` / `why_needed` / `absence_impact` 셀에 "spec.md §N 참조", "코드에 있음" 같은 위치만 적기 → 카드만으로 사용자 판단 불가
- `related_essence`가 빈 분기를 P0에 두는 것 (본질 무관 기능). 이런 분기는 `recommend_action: drop` 권유
