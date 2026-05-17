# 세션 C: THE FORGE Finalizer + 병렬 모드 UX 구현

## 컨텍스트
- 메인 plan: `c:\1.Project\THE_FORGE\docs\parallel-branches-design.md` (**정독 필수**)
- 너의 책임: 단계 7, 8, 9 (Finalizer 에이전트 + FAIL 격상 + Whisper/알림)
- base 브랜치: `feature/parallel-foundation` 완료 후 `feature/parallel-finalizer`로 분기
- 의존성: 세션 A의 `worktree.py` (`auto_commit_*`, `merge_into_trunk`, `verify_finalizer_merge_scope`), 세션 B의 `run_agents_parallel`

## 단계 7: Finalizer 에이전트 + 자동 위반 감지
- 신규 파일:
  - `scaffold/agents/finalizer.md` (배포 원본)
  - `.claude/agents/finalizer.md` (운영 카피)
    - frontmatter: `tools: [Read, Edit, Bash]` (Edit 허용, Write 차단)
    - 시스템 프롬프트 본문:
      - **허용 편집**: `git status`가 unmerged로 표시한 파일의 충돌 마커 (`<<<<<<<` / `=======` / `>>>>>>>`) 범위 안만
      - **금지**: qa-report.md 수정 (FAIL→PASS 바꿔치기), 충돌 안 난 파일 수정, 새 기능 추가
      - decision-NNN.md 기록 의무 ("어느 분기 채택 / 다른 분기 무엇 버림 / 이유")
      - 부분 머지 모드 지원 (단계 8-2)
  - `src/forge/agents/finalizer.py`:
    - `run_finalize(config, paths, branches, worktrees, *, partial=False, notifier=None) -> FinalizeResult`
    - 1. FAIL 분기 사전 검사 → `needs_escalation` 반환
    - 2. `merge_into_trunk` 호출 → 충돌 시 finalizer LLM 세션 (`run_agent_sync("finalizer", ...)`)
    - 3. 머지 commit 후 `verify_finalizer_merge_scope` 호출
    - 4. 위반 시 `git revert` + 사용자 게이트
    - 5. 성공 시 `artifacts/sprint-{N}-done.md` 작성 (decision-NNN 목록과 한 줄 요약 노출)

## 단계 8: FAIL 격상 + PASS 부분 머지
- `src/forge/orchestrator.py`의 sprint 루프에 단계 8-2 흐름 구현 (세션 B가 남긴 TODO 자리):
  - branch별 `consecutive_fails` 추적
  - 임계점(`branch_fail_escalate_threshold`) 도달 시 Planner 재호출 + 새 sprint-contract.md (plan-review 게이트 우회)
  - 부분 머지 흐름:
    - finalizer가 needs_escalation 반환 시
    - PASS 분기만 `run_finalize(..., partial=True)`
    - FAIL worktree 보존 (디버깅 + 다음 라운드 참조)
    - `auto_commit_trunk_artifacts(..., "finalizer-partial-merge", ...)`
    - Planner 재호출 시 프롬프트에 trunk diff 요약 + PASS 분기 결과 명시 주입
- `_notify_fail_with_options` 정정:
  - 일괄 통보 (1 sprint = 최대 1 알림)
  - escalation 시점에만 알림 (임계점 미만 자동 재시도는 알림 X)
  - 메시지 형식: "Sprint N ESCALATION + 분기별 점수 + /resume /skip /stop"

## 단계 9: Whisper 라우팅 + 알림 prefix
- 라우팅 규칙 구현 (`src/forge/notifier/slack/receiver.py`, `telegram/receiver.py`):
  - `@branch-2 메시지` → `artifacts/branches/branch-2/whisper-queue.jsonl`에 push
  - 일반 메시지 (prefix 없음) → trunk `artifacts/.whisper-queue.jsonl`
  - `@all 메시지` → 모든 활성 분기 큐에 broadcast
- `src/forge/notifier/base.py` 또는 호출부에 prefix 태깅:
  - 예: `"[branch-1] generator 시작"`
- Slack rate limit 보호: 0.5초 간격 토큰 버킷 (간단 구현)

## 산출물
- git branch `feature/parallel-finalizer`
- **회귀 테스트 1번 통과**
- **검증 시나리오 통과**:
  - 3 (FAIL escalation + Planner 재호출)
  - 4 (머지 충돌 자체 해결)
  - 4-2 (의미적 충돌 abort + 게이트)
  - 4-3 (scope 위반 감지 → revert)
  - 4.8 (PASS 분기 부분 머지)

## 금지
- 세션 A 영역 (`config.py` 변수, `BranchState`, `worktree.py` 시그니처) 변경 금지. 호출만.
- 세션 B 영역 (`contract.py`, `run_agents_parallel`, `evaluator.py::run_evaluate` 시그니처) 변경 금지.
- 세션 B가 작성한 `orchestrator.py`의 단계 6 분기 로직은 손대지 마라. 그 안의 TODO 자리만 채워라.

## orchestrator.py 충돌 처리
세션 B가 단계 6 분기 로직 작성, 너는 단계 7/8 호출과 FAIL 처리 작성. 가능하면 함수 단위로 분리:
- 세션 B: `_handle_parallel_sprint_generation(...)` 함수
- 너 (세션 C): `_handle_parallel_sprint_finalization(...)` + `_handle_parallel_sprint_escalation(...)` 함수
이렇게 분리하면 같은 파일이라도 머지 충돌 0.

## 완료 보고 (PR 본문)
1. 단위 + 회귀 + 검증 시나리오 3/4/4-2/4-3/4.8 통과 증거
2. orchestrator.py의 너의 추가 함수 목록 (세션 B와 충돌 영역)
3. self-rationalization 방어 4종이 모두 작동하는 증거 시나리오 1건
