---
name: forge-verdict-table
description: "forge Axiom Verdicts 표 작성법. plan-review.md / qa-report.md에 essence_axioms 각각 검증한 표 박을 때. planner Mode A/B + evaluator agent가 호출."
---

# Axiom Verdicts 표

essence_axioms가 있는 프로젝트의 plan-review.md / qa-report.md 에 **반드시** 박는 표. 사용자가 카드만 보고 8-10초에 본질 충족도 판단할 수 있게.

## 핵심 규칙

각 셀은 "tests/foo.py:42 가서 봐" 같은 **위치 지시가 아니라 내용 자체**. 위치만 적으면 사용자가 파일 열어 직접 찾아야 해서 카드 존재 이유 사라짐.

## 컬럼별 답해야 할 질문

| 컬럼 | 답해야 할 질문 | 좋은 예 | 나쁜 예 |
|---|---|---|---|
| `inspection_method` | "이 본질이 충족됐는지 어떻게 따져봤나?" | "네트워크 차단 상태에서 핵심 기능 12개를 손으로 실행해 외부 호출 발생 여부 확인" | "src/net.py 점검" / "테스트 실행" |
| `measurements` | "실제로 무엇이 측정/관찰됐나?" | "12/12 통과, 어떤 호출도 발생 안 함" | "테스트 OK" / "tests 디렉토리 참조" |
| `evidence` | "가장 강한 증거 한 줄은?" | `"if conn is None: return cached"` (src/net.py:42) | "src/net.py:42" (문구 없음) |
| `counter_hypothesis` | "그래도 깨질 수 있는 시나리오는?" | "DNS만 차단된 환경에서는 timeout으로 30초 멈춤 가능" | 빈 셀 / "검토 필요" |
| `user_impact` | "본질 깨지면 사용자에게 무슨 일?" | "비행기/지하철에서 앱이 무한 로딩으로 멈춤" | "성능 영향" / "UX 저하" |

## 표 형식

```markdown
## Axiom Verdicts

| id | statement | verdict | confidence | inspection_method | measurements | evidence | counter_hypothesis | user_impact | recommend_action |
|----|-----------|---------|-----------|-------------------|--------------|----------|--------------------|--------------|------------------|
| a1 | 오프라인 동작 | VERIFIED | 95 | 네트워크 차단 상태에서 핵심 기능 12개를 손으로 실행 | 12/12 통과 | "if conn is None: return cached" (src/net.py:42) | DNS만 차단되면 timeout 30초 | 비행기/지하철 정상 동작 | accept |
| a2 | 1초 내 처리 | PARTIAL | 60 | 10MB/100MB 입력으로 처리 시간 측정 | 10MB 0.3s, 100MB skip | `@pytest.mark.skip("slow")` (tests/perf_test.py:34) | 100MB 선형이면 3s 예상 | 30%가 100MB 사용자라 위반 빈도 높음 | partial_regen(a2) |
```

## 검증 규칙

- 모든 컬럼 **필수**. `counter_hypothesis` 진짜 없으면 "없음" 명시 (빈 값 X, silent X)
- `verdict` ∈ {VERIFIED, PARTIAL, MISSING}. `confidence` 0-100 정수
- `recommend_action` ∈ {`accept`, `partial_regen(axiom_ids)`, `reject(reason)`}
- 모호 표현 ("대체로", "아마", "이 정도면", "spec.md §N 참조") 사용 시 `confidence` 강제 ≤50
- `weight: critical` axiom이 PARTIAL/MISSING이면 **종합 판정 자동 FAIL** (qa-report.md 의 경우)
- 측정값 없거나 `falsifiable_by` 빈 axiom: `verdict=MISSING`, `confidence=0`, `evidence="검증 불가 (falsifiable_by 비어있음)"`

## 작성 톤

사용자에게 말하듯 친절한 한국어 한 문장씩. 약어/내부 용어/줄임표 자제. 위치 인용은 `evidence` 셀에서만, 해당 문구를 따옴표로 함께. 위치만 적고 내용 없는 셀은 **값이 비어있는 것으로 간주** (자기 합리화 방지).
