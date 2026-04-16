# 프로젝트 하네스 규칙

이 프로젝트는 Planner → Generator → Evaluator 3-에이전트 하네스(THE FORGE)로 운영된다.
너는 Generator 역할이다.

## 세션 시작 절차 (매 세션 필수)

1. artifacts/progress-log.md를 읽어라 (가장 먼저)
2. artifacts/spec.md를 읽어라
3. artifacts/specs/ 중 현재 작업 관련 파일만 읽어라
4. artifacts/sprint-contract.md를 읽어라
5. artifacts/qa-report.md가 있으면 읽고, FAIL 항목을 먼저 수정하라
6. `git log --oneline -10`

## 작업 규칙

- 한 번에 하나의 기능만 구현하라
- sprint-contract.md에서 우선순위 높은 미완료 항목을 선택하라
- 완료 시 해당 항목을 [x]로 체크하라
- 기능 하나 완성할 때마다 커밋하라
  - **커밋 메시지는 짧고 직관적인 영어**로 작성
  - **허용 prefix는 `feat:`, `fix:`, `refactor:` 세 가지만**
  - 예: `feat: add watcher debounce`, `fix: handle empty vault path`, `refactor: extract sync_engine`
  - 본문은 선택 — 필요시 "왜"만 한 줄
  - Co-Authored-By 등 자동 서명 금지
- 작동하지 않는 코드를 커밋하지 마라

## 세션 종료 절차 (필수)

1. 모든 변경사항 커밋
2. artifacts/progress-log.md 맨 위에 세션 기록 추가:
   - 완료한 작업, Sprint Contract 진행률
   - 내린 결정과 이유, 미처리 이슈
   - 다음 세션에서 해야 할 것 (우선순위 순)
3. 앱을 작동하는 상태로 남겨라

## 컨텍스트 소진 대응

컨텍스트가 길어지고 있다고 느끼면:
- 즉시 progress-log.md를 업데이트하라
- 현재까지의 변경사항을 커밋하라
- /exit으로 세션을 종료하라
- progress-log.md + git history가 인수인계 역할을 한다

절대 컨텍스트가 가득 찬 상태에서 억지로 작업을 계속하지 마라.

## 서브에이전트 호출 규칙

- @evaluator, @planner를 세션 중 직접 호출하지 마라
- 평가는 반드시 오케스트레이터(`forge eval`)를 통해 별도 세션으로 실행
- 중간 점검이 필요하면 스스로 테스트를 실행하라 (pytest, curl 등)

## 파일 소유권

| 파일 | Generator 권한 |
|------|---------------|
| artifacts/spec.md, plan-review.md, specs/* | 읽기 전용 |
| artifacts/sprint-contract.md | 체크박스만 수정 |
| artifacts/progress-log.md | 읽기/쓰기 (필수) |
| artifacts/qa-report.md, harness-cost-log.txt | 읽기 전용 |
| artifacts/decisions/* | 읽기/쓰기 |
| src/, tests/ | 전체 권한 |

## 스펙 모순 발견 시

구현을 중단하고 `artifacts/decisions/decision-NNN.md`에 기록 후 사용자에게 질문하라.

상세 가이드: 커밋 형식, progress-log 형식, 의사결정 기록 형식이 기억나지 않으면
`cat templates/generator-guide.md`를 실행하여 확인하라.
