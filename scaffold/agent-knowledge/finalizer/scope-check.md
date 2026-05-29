# Scope 검사 (위반 시 자동 revert)

## 핵심 규칙

목표는 분기들을 합쳐 **동작하는 완성품**을 만드는 것. 편집 권한은 *충돌난 파일* 로 제한 (충돌 안 난 파일은 이미 검증 통과분, 그대로 둔다). 충돌 종류별 처리는 conflict-resolution.md 참조.

## 만지면 안 되는 것

1. **qa-report.md 수정 금지** (어떤 분기의 qa-report든. FAIL → PASS 바꿔치기 금지. read-only 입력 자료)

2. **충돌 안 난 파일 수정 금지** (`git status` unmerged 파일만. 통합 코드도 충돌난 파일 안에서만)

3. **새 기능 추가 금지** (통합=두 분기 변경 잇기는 OK / 새 기능=아무도 요청 안 한 것 추가는 X)

4. **검증 없는 통합 금지** (통합 후 Bash 빌드·import·테스트 + decision에 결과 기록. 깨지면 수정, 못 풀면 3-C 강등)

5. **decision-NNN.md 누락 금지** (충돌 편집은 매 결정마다 기록)

6. **`git revert` 직접 실행 금지** (orchestrator의 `verify_finalizer_merge_scope`가 자동 처리)

## 도구

- `Edit`/`Write`: 충돌난 파일 통합 + 산출물(done/escalation/decision) 작성
- `Bash`: git 명령 + 통합 검증
- `Glob`/`Grep`/`Task`: 통합 영향 범위 파악

## 자기 점검 (편집 전)

- `git status` unmerged 파일인가? 아니면 손 떼라
- 두 분기 의도를 *잇는* 것인가, *더하는* 것인가? 후자면 손 떼라
- 통합했으면 Bash 검증 돌렸는가? 안 했으면 commit 금지
- decision에 기록할 것인가? 안 할 거면 편집 마라
