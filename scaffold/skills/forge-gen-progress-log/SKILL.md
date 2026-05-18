---
name: forge-gen-progress-log
description: "forge generator의 artifacts/progress-log.md 형식과 append 규칙. 세션 인수인계용. generator agent가 세션 종료 시 호출."
---

# progress-log.md 형식

## 위치와 append 규칙

- 위치: `artifacts/progress-log.md`
- **맨 위에 새 세션 엔트리 append**. 기존 엔트리는 절대 삭제·수정 X
- 파일이 없으면 새로 생성 (제목 `# Progress Log` 한 줄만)

## 세션 엔트리 형식

```markdown
## YYYY-MM-DD — Sprint N (branch-K 가 있으면 명시)

### 완료한 작업
- sprint-contract.md 항목 X: 한 줄 (commit `abc1234`)
- 항목 Y: 한 줄 (commit `def5678`)

### Sprint Contract 진행률
- 8/12 항목 완료 (67%)
- 남은: 항목 A, B, C, D

### 내린 결정과 이유
- decision-003 참조 — <한 줄 요약>
- 또는 inline: "X 라이브러리 대신 Y 채택 — 사유"

### 미처리 이슈
- 항목 Z: <왜 못 했는지 한 줄>
- 의심 가는 버그: <증상 + 파일:라인>

### 다음 세션 할 일 (우선순위 순)
1. 항목 A 구현 (FAIL 항목이면 최우선)
2. 항목 B 마무리
3. 의심 버그 확인
```

## 작성 톤

- 다음 세션이 **이것만 읽고 즉시 작업 시작 가능**해야 함
- 모호한 톤 금지 ("대충 잘 됐다", "조금 더 필요할 듯")
- 파일:라인 / 커밋 SHA / decision-NNN 같은 **클릭 가능한 좌표** 필수

## 자동 모드에서 특히 중요

자동 루프(forge run)에서 다음 세션이 progress-log.md만 보고 컨텍스트를 잡는다. **이 파일이 곧 인수인계서**. 누락된 미처리 이슈 = 다음 세션이 영원히 모름.

## 컨텍스트 소진 임박 시

여유 있을 때 미리 progress-log 업데이트 + 커밋. "마지막에 몰아쓰기"는 max-turns 도달 시 진행 흔적 통째 손실 위험.
