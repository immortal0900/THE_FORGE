# Finalizer 산출물 형식

상황에 따라 셋 중 하나를 작성. **최소 하나는 반드시 작성**되어야 종료 가능.

## 1. 정상 모드: `artifacts/sprint-{N}-done.md`

```markdown
# Sprint N - DONE (Finalizer)

## 머지된 분기
- branch-1 - 충돌 0건
- branch-2 - 충돌 3건, decision-001/002/003 참조

## 사용된 decision-NNN 목록 (사용자 사후 검토)
- decision-001 - 한 줄 요약
- decision-002 - 한 줄 요약

## 분기별 PASS 점수
- branch-1: PASS (score: ...)
- branch-2: PASS (score: ...)

## 사용자 사후 검토 권장 포인트
- 한 줄
```

## 2. 부분 머지 모드: `artifacts/sprint-{N}-partial-{round}.md`

```markdown
# Sprint N - PARTIAL MERGE round {round} (Finalizer)

## 이번 라운드 머지된 PASS 분기
- branch-1 - 충돌 N건
- branch-3 - 충돌 0건

## 다음 라운드 참조용 FAIL 분기 (worktree 보존됨)
- branch-2 - qa-report 인용: "..."

## 사용된 decision-NNN 목록
- (있으면 나열)

## Planner 재호출 시 인지해야 할 trunk 변경
- 한 줄
```

## 3. 의미적 충돌 abort: `artifacts/.merge-decisions/escalation-{N}.md`

```markdown
# Sprint N - Finalizer abort (의미적 충돌)

## 충돌 파일
- `src/auth/login.py`

## 양쪽 입장
- branch-1: "X를 사용한다"
- branch-3: "X 대신 Y를 사용한다"

## 왜 양립 불가인가
- 한 줄

## 사용자에게 필요한 결정
- 한 줄
```

## 어느 것을 작성하는가

| 상황 | 산출물 |
|---|---|
| 모든 PASS 분기 정상 머지 완료 | `sprint-{N}-done.md` |
| orchestrator가 `partial=True` 호출 | `sprint-{N}-partial-{round}.md` |
| 의미적 충돌로 `git merge --abort` 한 경우 | `escalation-{N}.md` |
| 사전 검사에서 FAIL 분기 감지 | `escalation-{N}.md` |

## 작성 규칙

- 모든 항목 필수. 빈 셀 두지 마라
- "PASS 점수" 는 분기 qa-report.md의 종합 점수에서 인용
- "사후 검토 권장 포인트" 가 없으면 "없음" 명시 (빈 값 금지)
- 산출물은 Edit으로 신규 생성도 가능 (Write 차단)
