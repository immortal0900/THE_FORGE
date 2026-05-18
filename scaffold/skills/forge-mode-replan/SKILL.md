---
name: forge-mode-replan
description: "Planner Mode E. forge sprint 일부 분기가 연속 FAIL 임계점 도달 시 sprint-contract.md 분기 재분할. parallel-branches-design.md 단계 8-2의 5번째 단계. orchestrator escalation 후 planner가 호출."
---

# Mode E: Escalation 후 Sprint Contract 재작성

조건: orchestrator가 직전 sprint의 일부 분기 연속 FAIL → planner replan 요청.

## 절차

1. **기존 artifacts/sprint-contract.md** Read — 이전 분할 구조 파악
2. **escalation된 각 분기의 artifacts/branches/{id}/qa-report.md** Read — FAIL 사유 종합 (무엇이 왜 실패했나)
3. **PASS하여 trunk에 머지된 분기**(orchestrator가 prompt에 명시)는 이미 코드베이스 반영됨. **다시 만들지 마라**. 그 결과를 base로 새 contract
4. **재분할 시 적어도 하나 변경** (같은 contract 재시도는 결함 못 풂):
   - 분할 자체 변경 (영역 재배치, 분기 합치기/쪼개기, 단일 분기 회귀)
   - `files_owned` 재정의 (공유 파일 충돌이 원인이면)
   - 태스크 단순화 (한 분기 과부하면 P0 일부를 P1 강등)
   - 본질 부합 재점검 (본질 무관 작업 섞였으면 drop)
5. **artifacts/sprint-contract.md** Write — `sprint_number`는 그대로 유지 (같은 sprint 안의 재작성), 분할 영역만 새로
6. **artifacts/sprint-capabilities.md** Write — 새 분할에 맞춰 capability cards 갱신 (forge-capability-yaml skill 호출)
7. **plan-review 게이트 우회** — escalation 알림에서 이미 사용자 동의 받음. 별도 검토 없이 다음 generator로 진행

## 핵심 원칙

분할 자체를 바꾸는 것이 Mode E 의 본질. 같은 contract 로 또 재시도하면 같은 결과만 나옴.
