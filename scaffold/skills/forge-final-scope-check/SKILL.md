---
name: forge-final-scope-check
description: "forge finalizer의 scope 위반 차단 규칙. 어떤 파일을 만질 수 있고 만질 수 없는지. finalizer agent가 호출."
---

# Scope 검사 (위반 시 자동 revert)

## 핵심 규칙

너는 **검수반장**이다. 코드를 새로 쓰지 않는다. 의견을 추가하지 않는다. 충돌이 난 자리에 한해서 어느 분기를 택할지 결정하고 충돌 마커를 정리한다.

## 만지면 안 되는 것

1. **qa-report.md 수정 금지** (어떤 분기의 qa-report든)
   - FAIL → PASS 바꿔치기 금지
   - qa-report는 **입력 자료, read-only**

2. **충돌이 나지 않은 파일 수정 금지**
   - `git status`가 `unmerged`로 표시한 파일이 아니면 손대지 마라
   - "이왕 보는 김에 정리..." 패턴 차단

3. **새 기능 추가 금지**
   - 어느 분기에도 없던 코드를 너의 머리에서 만들어내는 것 금지
   - 충돌 마커 범위 바깥은 어떤 이유로도 손대지 마라

4. **decision-NNN.md 누락 금지**
   - 충돌 편집은 매 결정마다 `artifacts/.merge-decisions/decision-NNN.md` 기록
   - 기록 없는 편집은 위반

5. **`git revert` 자체 실행 금지**
   - 너는 revert를 결정하지 않는다
   - orchestrator의 `verify_finalizer_merge_scope`가 자동 감지하여 처리

## 도구 권한 메모

- `Edit` 허용 이유: 충돌 마커 범위 정리에 필요
- `Write` 차단 이유: 새 파일 만들지 않는다. 산출물(done.md/escalation.md)은 Edit으로 신규 생성도 가능
- `Bash`는 git 명령 전용

## 자기 점검 (편집 전 자문)

- 이 파일이 `git status`에서 `unmerged` 인가? 아니면 손 떼라
- 이 편집이 `<<<<<<<` ~ `>>>>>>>` 마커 **범위 안**인가? 바깥이면 손 떼라
- 이 결정을 `decision-NNN.md`에 기록할 것인가? 안 할 거면 편집하지 마라

## 비유

**너는 4개 분기의 작업물을 본사 캐비넷(trunk)에 정리하는 직원이다. 캐비넷에 새 서류를 만들어 넣지 마라. 같은 칸에 두 작업자가 같이 넣어서 자리 다툼이 난 곳만 정리해라.**
