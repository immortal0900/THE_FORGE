---
name: forge-final-merge-procedure
description: "forge finalizer의 분기 머지 절차. 정상 모드 + 부분 머지 모드 양쪽. finalizer agent가 호출."
---

# 분기 머지 절차

## Step 1: 사전 검사

모든 분기 `artifacts/branches/branch-K/qa-report.md`의 `종합 판정` 확인.

- 하나라도 FAIL → 즉시 종료 + `artifacts/.merge-decisions/escalation-{N}.md`에 "FAIL 분기 목록 + needs_escalation" 기록
- 정상 모드에서는 orchestrator가 이미 사전 검사를 했으므로 PASS 분기만 도달. 그래도 한 번 더 확인

## Step 2: 차례 머지

각 분기 ref에 대해 orchestrator가 prompt로 전달한 순서대로:

```
git merge forge/sprint-{N}-branch-{K} --no-ff --no-commit
```

`--no-commit` 은 충돌 발생 시 자체 해결할 시간을 벌기 위함.

## Step 3: 분기 처리

- **충돌 없음**: `git status` 깨끗 → `git commit -m "forge: finalizer-merge sprint-{N}-branch-{K}"` 즉시. 다음 분기로
- **충돌 있음**: `forge-final-conflict-resolution` skill로 진행

## Step 4: 모든 분기 완료

`artifacts/sprint-{N}-done.md` 통합 보고서 작성 — 형식은 `forge-final-archive-format` 참조.

## 부분 머지 모드 (orchestrator가 `partial=True`로 호출)

PASS 분기 일부만 trunk로 머지, FAIL 분기는 다음 라운드 Planner 재호출용으로 보존.

차이점:
- orchestrator prompt에 "부분 머지 모드, 머지할 분기: branch-1, branch-3" 명시
- 보고서 이름: `artifacts/sprint-{N}-partial-{round}.md` (done.md와 구분)
- "다음 라운드 참조용 FAIL 분기" 목록 보고서에 명시

머지·충돌 해결·자동 위반 감지는 동일.

## 종료 조건

- 정상 종료: 모든 분기 머지 commit + `sprint-{N}-done.md` 작성 후 종료
- abort 종료: `git merge --abort` + `escalation-{N}.md` 작성 + 즉시 종료
- 어느 경우든 **`git revert` 직접 실행 금지** (orchestrator의 `verify_finalizer_merge_scope`가 자동 처리)
- `decision-NNN.md` / `done.md` / `partial-{round}.md` / `escalation-{N}.md` 중 **최소 하나 반드시 작성**
