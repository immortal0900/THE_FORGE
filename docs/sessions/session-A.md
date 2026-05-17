# 세션 A: THE FORGE 병렬 분기 기반 레이어 구현

## 컨텍스트
- 메인 plan: `c:\1.Project\THE_FORGE\docs\parallel-branches-design.md` (전체 9단계 설계서, **정독 필수**)
- 너의 책임: 단계 0, 1, 2, 3 (기반 구조). 다른 세션 B/C가 너의 산출물 위에서 동시 진행한다.
- base 브랜치: `feature/parallel-branches`에서 분기한 `feature/parallel-foundation`
- 작업 디렉토리: `c:\1.Project\THE_FORGE` (코드), `c:\1.Project\THE_FORGE_TEST` (테스트 실행)
- 라인 번호 표기 규칙: plan의 0번 섹션 준수. 심볼명 우선, 라인 번호는 가변 보조.

## 단계 0: 설정 변수 (단계 0 명세 그대로)
- `src/forge/config.py::ForgeConfig`에 다음 추가:
  - `max_parallel_branches: int = 1`
  - `branch_fail_escalate_threshold: int = 2`
- 1 <= N <= 4 캡 강제
- 환경변수: `FORGE_MAX_PARALLEL_BRANCHES`, `FORGE_BRANCH_FAIL_ESCALATE_THRESHOLD`

## 단계 1: BranchState + Checkpoint.branches
- `src/forge/checkpoint.py`에 `BranchState(BaseModel)` 신설
  - 필드: branch_id, phase, sprint, consecutive_fails, worktree_path, git_branch, status("active"/"passed"/"failed"/"escalated"), detail, timestamp
- `Checkpoint`에 `branches: list[BranchState] = []` 필드 추가
- 직렬화 round-trip 단위 테스트 + 옛 `.harness-checkpoint`(branches 키 없음) 로드 호환 검증

## 단계 2: worktree.py 신설 + auto-commit 정책 + .gitignore
- `src/forge/worktree.py` 신설. 함수:
  - `create_branch_worktrees(project_root, sprint_num, branch_ids, base_ref) -> list[BranchWorktree]`
  - `auto_commit_worktree(worktree_path, branch_id, sprint_num, turn_kind) -> CommitResult`
  - `auto_commit_trunk_artifacts(trunk_root, turn_kind, sprint_num) -> CommitResult`
    - **pathspec 명시**: `artifacts/spec.md`, `sprint-contract.md`, `plan-review.md`만 stage. `src/`, `tests/` 등 사용자 영역은 절대 stage하지 않음.
  - `remove_branch_worktrees(project_root, worktrees) -> None`
  - `merge_into_trunk(project_root, branch_refs, strategy="no-ff") -> MergeResult`
    - `--no-commit` 옵션, 충돌 시 abort는 호출자(Finalizer)가 결정
  - `verify_finalizer_merge_scope(project_root, expected_conflict_files) -> ScopeViolation | None`
- `src/forge/cli.py::_ensure_gitignore` 확장: `.worktrees/`, `artifacts/branches/`, `artifacts/sprint-*-done.md`, `artifacts/.merge-decisions/`
- `scaffold/agents/journal.md`에 영역 분리 정책 명시 추가:
  - "trunk 사용자 코드 (`src/`, `tests/`) → 사용자가 commit 결정 (기존 정신)"
  - "시스템 산출물 (`artifacts/spec.md`, `sprint-contract.md`, `plan-review.md`) → orchestrator 자동 커밋 (신규)"
  - ".worktrees/sprint-* → orchestrator 자동 커밋 (신규)"

## 단계 3: ProjectPaths.branch_paths + trunk_root
- `src/forge/config.py::ProjectPaths`에 헬퍼:
  - `trunk_root @property` (`git rev-parse --git-common-dir`의 부모)
  - `branch_paths(branch_id, *, in_worktree=False) -> ProjectPaths`
    - `branch_id="trunk"`이면 self 반환 (회귀 0)
    - `in_worktree=True` → worktree cwd 기준 (generator/evaluator subprocess가 사용)
    - `in_worktree=False` → trunk 절대 경로 기준 (orchestrator/finalizer가 사용)
    - progress-log/qa-report/whisper-queue는 **항상 trunk 절대 경로** 가리킴 (artifacts/branches/{branch_id}/...)
    - spec/sprint-contract는 in_worktree에 따라 worktree 또는 trunk

## 산출물
- git branch `feature/parallel-foundation`에 commit
- 단위 테스트 통과:
  - BranchState round-trip
  - Checkpoint v1(branches 키 없음) → v2 로드 호환
  - branch_paths 폴백 (trunk이면 self)
  - worktree 함수 (subprocess 모킹으로 git 명령 호출 검증)
- **회귀 테스트 1번 시나리오 통과**: `FORGE_MAX_PARALLEL_BRANCHES=1` 기본값에서 기존 forge E2E 결과가 byte-level 일치

## 금지
- 단계 4-9 영역 손대지 마라 (다른 세션 영역)
- `src/forge/orchestrator.py`, `runner.py`, `evaluator.py`, `planner.py` 손대지 마라
- 새 의존성 추가 금지

## 완료 보고 (PR 본문)
1. 추가/수정한 파일 목록 + 라인 수
2. 단위 테스트 결과 (어떤 케이스 몇 개 통과)
3. 회귀 시나리오 1번 통과 증거 (byte-level diff 결과)
4. 미해결 의문점 / 후속 세션이 알아야 할 가정
