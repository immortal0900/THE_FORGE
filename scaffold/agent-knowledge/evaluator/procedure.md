# QA 평가 절차 (Step 0-5)

## Step 0: qa-report.md 초안 Write (최우선)

다른 도구 쓰기 전 `artifacts/qa-report.md` 스켈레톤 Write. 평가 중 Edit으로 채운다. (max-turns 중단 대비)

## Step 1: 컨텍스트 수집

1. `artifacts/spec.md` — 전체 프로젝트
2. `artifacts/sprint-contract.md` — 스프린트 범위
3. `artifacts/specs/` — 관련 상세 스펙만
4. `artifacts/progress-log.md` — Generator 작업 기록
5. 소스 코드 탐색 (Glob → Read)

## Step 2: 자동화 검증 실행

Bash로 pytest, npm test, lint, 타입 체크 시도. 각 stdout/stderr를 근거로 기록.

**Bash 명령 timeout**: 모든 호출 `timeout=30000` (30초) 이하 명시. 무한 대기 가능 명령(server, watcher, REPL)은 호출 자체 금지.

세션 hang 방지는 `.claude/agent-knowledge/evaluator/bash-guard.md` 참조.

## Step 3: 코드 리뷰

sprint-contract.md 각 항목의 구현 여부, 명세 일치, 에러 핸들링, 엣지 케이스 확인.

## Step 4: 평가 기준 (각 1-10점)

- 기능 완성도 (FAIL: 7점 미만)
- 코드 품질 (FAIL: 7점 미만)
- 테스트 커버리지 (FAIL: 7점 미만)
- 명세 충실도 (FAIL: 7점 미만)

## Step 5: 보고서 작성 → artifacts/qa-report.md

```
## 종합 판정: PASS | FAIL
## 점수: 기능 X/10, 품질 X/10, 테스트 X/10, 명세 X/10
## Sprint Contract 항목별
- [x/ ] 항목명: PASS/FAIL — 근거 (파일:라인)
## 상세 평가
...
```

essence_axioms가 있으면 Axiom Verdicts 표를 추가 — `.claude/agent-knowledge/_shared/verdict-table.md` 참조.

## 절대 규칙

- "이 정도면 괜찮다" = 버그를 통과시키는 순간
- 파일명:라인 번호 없는 지적은 지적이 아니다
- 테스트를 실행할 수 있는데 안 한 채 PASS 금지
- 의심스러우면 FAIL
