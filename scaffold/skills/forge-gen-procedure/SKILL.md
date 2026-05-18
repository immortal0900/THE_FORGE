---
name: forge-gen-procedure
description: "forge generator의 세션 시작·작업·종료 절차. Sprint Contract 기반 구현 흐름. generator agent가 호출."
---

# Generator 구현 절차

## 세션 시작 (매 세션 필수, 순서 유지)

1. `artifacts/progress-log.md` (가장 먼저)
2. `artifacts/spec.md`
3. `artifacts/specs/` 중 현재 작업 관련 파일만
4. `artifacts/sprint-contract.md`
5. `artifacts/qa-report.md` 가 있으면 읽고 **FAIL 항목을 최우선으로 수정**
6. `git log --oneline -10`

## 작업 규칙

- 우선 공식문서 참고 (context7 MCP)
- **한 번에 하나의 기능만** 구현
- sprint-contract.md에서 우선순위 높은 미완료 항목 선택
- 완료 시 해당 항목을 `[x]` 체크
- 기능 하나 완성할 때마다 커밋 — 형식은 `forge-gen-commit-style` 참조
- 작동하지 않는 코드 커밋 금지

## 세션 종료 (필수)

1. 모든 변경사항 커밋
2. `artifacts/progress-log.md` 맨 위에 세션 기록 추가 — 형식은 `forge-gen-progress-log` 참조
3. 앱을 작동하는 상태로 남겨라

## 컨텍스트 소진 대응

컨텍스트 길어지고 있다고 느끼면:
- 즉시 progress-log.md 업데이트
- 현재까지 변경사항 커밋
- 세션 종료
- progress-log.md + git history가 인수인계 역할

컨텍스트 가득 찬 상태에서 억지 진행 금지.

## 스펙 모순 발견 시

구현 중단하고 `artifacts/decisions/decision-NNN.md` 기록 (형식: `forge-gen-decision-log`) 후 **질문 없이 합리적 기본값으로 진행**. 자동 루프에서 사용자 응답을 기다릴 수 없다.
