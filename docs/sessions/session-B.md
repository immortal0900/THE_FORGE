# 세션 B: THE FORGE 병렬 실행 엔진 구현

## 컨텍스트
- 메인 plan: `c:\1.Project\THE_FORGE\docs\parallel-branches-design.md` (**정독 필수**)
- 너의 책임: 단계 4, 5, 6 (병렬 실행 엔진)
- base 브랜치: `feature/parallel-foundation` 완료 후 `feature/parallel-engine`으로 분기
- 의존성: 세션 A가 만든 `worktree.py`, `BranchState`, `ProjectPaths.branch_paths` 사용

## 단계 4: contract.py + planner.md 확장
- `src/forge/contract.py` 신설:
  - `BranchSpec` dataclass (id, title, tasks, depends_on, files_owned)
  - `parse_branches(sprint_contract_text) -> list[BranchSpec]`
    - `## Parallel Task Graph (YAML)` 섹션 파싱
    - 부재 시 `[BranchSpec(id="trunk", ...)]` 1개 반환 (회귀 보호)
- `scaffold/agents/planner.md` + `.claude/agents/planner.md`에 "병렬화 가능성 판단 절차" 섹션 추가:
  - 독립성 3 기준: 파일 충돌 없음 / 의존성 DAG 위에서 동시 가능 / 인터페이스 명시
  - `Parallel Task Graph (YAML)` 형식 예시 (id, title, tasks, depends_on, files_owned)
  - 1개만이면 섹션 생략 가능 → parse_branches 폴백

## 단계 5: runner.py::run_agents_parallel
- `src/forge/agents/runner.py`에 신규 함수:
  - `run_agents_parallel(branch_specs, project_paths, config, agent_kind) -> list[RunResult]`
  - `asyncio.Semaphore`로 `max_parallel_branches` 한도 강제
  - 각 `ClaudeCliSession`에 cwd=worktree, whisper_queue_path=branch별 큐 주입
  - generator prompt에 trunk 절대 경로 주입 (단계 3-4 참조)
- `run_agent_sync`는 변경 없이 그대로 (단일 분기 + finalizer가 사용)

## 단계 6: orchestrator 분기 선택 + evaluator.py 변경
- `src/forge/orchestrator.py`의 sprint 루프 (generator/evaluator 호출 지점) 다음 로직으로 감싼다:
  ```
  branches = parse_branches(sprint_contract_text)
  if len(branches) == 1:
      # 기존 코드 그대로 (회귀 0)
  else:
      auto_commit_trunk_artifacts(paths.project_root, "planner-contract", sprint_num)
      worktrees = create_branch_worktrees(...)
      run_agents_parallel("generator")
      for spec, wt in zip(...): auto_commit_worktree(wt.path, ..., "generator")
      run_agents_parallel("evaluator")
      for spec, wt in zip(...): auto_commit_worktree(wt.path, ..., "evaluator")
      # 단계 7 finalizer 호출 부분은 세션 C가 추가
  ```
- `src/forge/agents/evaluator.py::run_evaluate` 시그니처 변경:
  - `branch_id: str = "trunk"` 인자 추가 (기본값으로 회귀 0)
  - `branch_id != "trunk"` 시 `paths.branch_paths(branch_id)` 사용, prompt에 trunk 절대 경로 주입
  - `is_pass`, `validate_qa_report`도 `branch_id` 인자 추가

## 산출물
- git branch `feature/parallel-engine`
- 단위 테스트:
  - `parse_branches` (섹션 부재 / 단일 / 2-4 branch / 잘못된 YAML 거부)
  - `evaluator.run_evaluate(branch_id="trunk")` = 기존 동작
  - `evaluator.run_evaluate(branch_id="branch-1")` = 분기 경로 사용
- **회귀 테스트 1번 통과** (단일 분기 모드 byte-level 일치)
- **병렬 골든 패스 2번 통과** (N=2 시나리오)

## 금지
- 단계 7-9 영역 손대지 마라:
  - `src/forge/agents/finalizer.py`, `scaffold/agents/finalizer.md`, `.claude/agents/finalizer.md`
  - `_notify_fail_with_options` 변경
  - whisper 라우팅 / notifier prefix
- 세션 A 영역 (`worktree.py` 함수 시그니처, `BranchState`, `ProjectPaths`) 변경 금지. 호출만 가능.

## orchestrator.py 충돌 주의
세션 C도 `orchestrator.py`를 건드린다 (단계 8 FAIL 격상). **너는 단계 6 분기 선택 로직만** 작성. 단계 7 finalizer 호출 자리와 단계 8 FAIL 처리 자리는 TODO 주석으로 남겨 세션 C에 위임.

## 완료 보고 (PR 본문)
1. 단위 테스트 통과 케이스
2. 회귀 1번 + 골든 2번 통과 증거
3. 세션 C에 위임한 TODO 주석 위치 목록
