# THE FORGE 병렬 분기 + Finalizer 통합 아키텍처

## 이 plan은 한 줄로 무엇인가?

**"작업자 1명이 직렬로 하는 공장 라인(현재)을 → 작업자 4명이 동시에 일하고 마지막에 검수반장이 합치는 공장 라인으로 바꾼다."**

git worktree(워크트리, 같은 저장소를 여러 폴더에 동시 체크아웃하는 기능)로 분기를 진짜 격리한다.

---

## 0. 라인 번호 표기 규칙 (먼저 정함)

이 plan은 **심볼명(함수명/클래스명/변수명) 우선**으로 위치를 가리킨다. 라인 번호는 가변이라 코드 수정/리팩터링으로 쉽게 어긋난다.

- 정확 위치는 구현 시 `Grep "심볼명"`으로 재확인
- 본문에 적힌 라인 번호는 **"이 plan 작성 시점의 실측치"**(2026-05-17 기준)일 뿐
- 라인 번호가 본문과 다르면 **심볼명을 정답으로 본다**

### 핵심 심볼 위치표 (작성 시점 실측)

| 심볼 | 파일 | 작성 시점 라인 | 무엇 |
|---|---|---|---|
| `class ClaudeCliSession` | `src/forge/agents/cli_session.py` | 53 | claude CLI 영속 세션 클래스 |
| `asyncio.create_subprocess_exec` 호출 | `src/forge/agents/cli_session.py` | 112 | 자식 프로세스 1개 띄움 |
| `self.session_id = uuid.uuid4()` | `src/forge/agents/cli_session.py` | 81 | 세션 ID 자동 생성 |
| `build_child_env` | `src/forge/agents/cli_session.py` | 42 | API 키 환경변수 제거 |
| `class ForgeAgentRunner` | `src/forge/agents/runner.py` | 42 | 동기 실행기 |
| `def run_agent_sync` | `src/forge/agents/runner.py` | 226 | 단일 세션 동기 진입점 |
| `class Phase(IntEnum)` | `src/forge/checkpoint.py` | 13-22 | 8개 단계 열거형 |
| `class Checkpoint(BaseModel)` | `src/forge/checkpoint.py` | 25-28 | 체크포인트 본체 |
| generator 호출 (`run_agent_sync("generator", ...)`) | `src/forge/orchestrator.py` | 1036 | sprint 루프 안 generator 호출 |
| evaluator 호출 (`ev.run_evaluate(...)`) | `src/forge/orchestrator.py` | 1067 | sprint 루프 안 evaluator 호출 |
| `def _notify_fail_with_options` | `src/forge/orchestrator.py` | 459 | FAIL 시 사용자 옵션 알림 |
| `_notify_fail_with_options` 호출 | `src/forge/orchestrator.py` | 1151 | FAIL 알림 발사 지점 |
| `paths.whisper_queue` 정의 | `src/forge/config.py` | 207 | 단일 whisper 큐 파일 경로 |
| `run_evaluate` 함수 | `src/forge/agents/evaluator.py` | 17 | paths.qa_report 직접 참조 |

---

## 1. 배경 - 지금 forge가 어떻게 생겼나

### 지금 모습 (1차선 공장)

```
[기획자] → 계획서 → [구현자 1명] → 코드 → [평가자 1명] → 합격/불합격 → 다음 sprint
```

### 핵심 단어 풀이

| 용어 | 영문 원어 | 뜻 |
|---|---|---|
| 스프린트 | sprint | 한 묶음 작업 단위 (예: DB 연결 + API 1개) |
| 단계 | Phase | 진행 칸 (PLANNING/CONTRACT/GENERATING/EVALUATING 등 8칸) |
| 산출물 폴더 | artifacts/ | 에이전트 통신용 파일 모음 |
| 체크포인트 | checkpoint | 진행 저장점 (게임 세이브 파일) |
| 분기 | branch | 평행 작업선 (이걸 1→4개로 늘리는 게 이 plan) |
| 워크트리 | git worktree | 같은 저장소를 여러 폴더에 동시 체크아웃하는 git 기능 |
| 자식 프로세스 | subprocess | OS가 띄우는 별개 실행 단위 |
| 마무리 통합자 | Finalizer | 4개 결과를 1개로 합치는 새 에이전트 |

### 검증된 사실 (실측)

- **병렬 코드 0건**: `swarm` / `team` / `parallel` / `asyncio.gather` / `ThreadPoolExecutor` 키워드 모두 0건
- **git 명령 0건**: forge 코드가 `git` subprocess 호출 0건. `journal.py` 안의 "git log --since=" 문자열은 generator에게 줄 프롬프트일 뿐
- **단일 파일 가정**: `progress-log.md`, `qa-report.md`, `whisper-queue.jsonl` 모두 1개씩만 존재

한마디로: **forge는 지금 병렬도 아니고 git 자동화도 아니다. 이 plan은 두 가지를 동시에 도입한다.**

---

## 2. 사용자 확정 결정

| 결정점 | 확정 답 |
|---|---|
| 어떤 메커니즘? | DIY subprocess 병렬 (외부 라이브러리/Anthropic Agent Teams 미사용) |
| 평가 구조 | Evaluator 1:1 (구현자마다 평가자 짝꿍) |
| 합치는 역할 | 신규 Finalizer 에이전트 (4번째 에이전트) |
| 실패 시 | 하이브리드 1-D (1차 분기 단위 재시도, 임계점 도달 시 Planner 재호출로 escalate) |
| 합치는 타이밍 | 매 sprint마다 finalizer 통합 |
| **분기 격리 메커니즘** | **W. git worktree** (방금 확정) |

---

## 3. git worktree 설계 (가장 큰 미해결 → 해결안)

### 왜 worktree인가 (다른 옵션 대비)

| 옵션 | 진짜 병렬? | forge 정신 (git 직접 X) | 사용자 채택 |
|---|---|---|---|
| W. git worktree | 예 | **위배** (forge가 git 명령 호출) | **채택** |
| S. 파일 sandbox 격리 | 예 | 보존 | 미채택 |
| F. files_owned 강제 | 부분 | 보존 | 미채택 |

**트레이드오프 명시**: W 옵션은 forge가 git을 직접 다루지 않는 정책을 깬다. 그 대신 진짜 격리 + 표준 git 충돌 처리를 얻는다. self-rationalization 위험은 단계 6의 방어 장치(도구 제한 + 시스템 프롬프트 금지 + 충돌 시 사용자 게이트)로 막는다.

### worktree 라이프사이클 (3단계 비유)

**1단계: sprint 시작 시 분기 워크트리 생성**
```
forge/                                    ← trunk 워크트리 (메인 작업 공간, 사용자가 보는 곳)
.worktrees/                               ← worktree 모음 (git 무시 폴더로)
  sprint-1-branch-1/                      ← 분기 1번 워크트리 (별개 폴더, 같은 저장소)
    src/, tests/, ...                     ← 자기 src 트리 (격리됨)
  sprint-1-branch-2/                      ← 분기 2번 워크트리
    src/, tests/, ...
```

각 worktree는 자기 git 브랜치(`forge/sprint-1-branch-1`, `forge/sprint-1-branch-2`) 위에 올라간다.

**2단계: 각 generator subprocess가 자기 worktree에서 작업**
- `cli_session.ClaudeCliSession(cwd=worktree_path)`로 cwd 분리
- generator는 자기 worktree 안에서 자유롭게 코드 수정 + commit
- 동시에 N개가 돌아도 src 충돌 0 (물리적 별개 폴더)

**3단계: sprint 끝에 Finalizer가 머지**
- finalizer는 trunk worktree로 돌아와 각 분기 브랜치를 차례로 머지 (`git merge forge/sprint-1-branch-N --no-ff`)
- 충돌 발생 시 정책 → 단계 6 참조
- 머지 완료 후 `.worktrees/sprint-N-*/` 모두 제거 (`git worktree remove`)

### self-rationalization 방어 4종 (forge 정신 보존, 정책 정정 v4)

**정책 변경 노트**: 이전 plan(v3)은 "Edit 도구 차단 + 충돌 시 무조건 abort"였다. 새 결정(v4): **충돌 마커 부분 편집은 허용**(작은 충돌까지 게이트 발사하면 자동화 가치 ↓), 단 시스템 프롬프트 + decision-log + 자동 위반 감지 + 사용자 사후 검토로 다층 방어.

| 방어 장치 | 무엇 | 어디에 |
|---|---|---|
| 1. 시스템 프롬프트 범위 제한 | "git status가 충돌 표시한 파일의 충돌 마커(`<<<<<<<` / `=======` / `>>>>>>>`) 사이만 편집 가능. qa-report 수정 / 충돌 안 난 파일 수정 / 새 기능 추가 금지" | `scaffold/agents/finalizer.md` 본문 (진짜 방어막) |
| 2. decision-NNN.md 기록 의무 | 모든 충돌 편집은 `artifacts/.merge-decisions/decision-NNN.md`에 "어느 분기 채택 / 다른 분기 무엇 버림 / 이유"를 기록 | finalizer 시스템 프롬프트 + run_finalize 후처리 검증 |
| 3. 자동 위반 감지 (emergency check) | finalizer 머지 commit 직후 `git diff --stat HEAD~1`로 변경 파일 목록을 확인. 충돌 안 났던 파일이 변경됐으면 즉시 `git revert` + 사용자 게이트 | `worktree.py::verify_finalizer_merge_scope` |
| 4. 사용자 사후 검토 | 매 `sprint-N-done.md`에 사용된 모든 decision-NNN 목록과 한 줄 요약 노출 | finalizer 산출물 포맷 |

**도구 권한**: `tools: [Read, Edit, Bash]` (Edit 허용, Write는 여전히 차단 - 새 파일 만들 일 없음).

한마디로: **finalizer는 충돌 마커 안만 편집할 수 있는 좁은 권한 + 4중 감시 아래 동작.**

---

## 4. 구현 단계 9개 (위험 낮은 것부터)

| 단계 | 무엇 | 비유 |
|---|---|---|
| 0 | 설정 변수 2개 신설 | 새 다이얼 추가, 안 돌리면 효과 없음 |
| 1 | 체크포인트 모델 확장 | 게임 세이브 파일에 빈칸 추가 |
| 2 | git worktree 관리 모듈 + auto-commit 정책 + .gitignore 분리 | 워크트리 생성/삭제 + 자동 커밋 + 격리 영역 분리 |
| 3 | artifacts 폴더 (하이브리드 c) + paths 헬퍼 확장 | 공용 SSoT 칸 + 분기별 격리 칸 동시 운영 |
| 4 | 기획자가 계약서에 갈래 정보 + 파서 모듈 | 작업 지시서 양식 확장 |
| 5 | 동시 N개 실행 함수 신설 | 컨베이어 벨트 N개 모터 |
| 6 | Orchestrator 분기 선택 + auto-commit 훅 + Finalizer 호출 | 분배기 + 자동 도장 + 검수반장 합류 |
| 7 | Finalizer 에이전트 신설 (코드 + 시스템 프롬프트) | 검수반장 채용 |
| 8 | 실패 시 단계 격상 + FAIL 알림 통합 | 자동 알람 + 일괄 통보 |
| 9 | Whisper 라우팅 + 알림 prefix | 분기별 메시지 채널 분리 |

---

### 단계 0. 설정 변수 신설 (회귀 0)

**무엇을 하나**: `config.py`의 `ForgeConfig`에 변수 2개 추가.

> ⚠️ 본 설계 문서는 도입 시점 기록이다. 당시 `max_parallel_branches` 기본은 회귀 0 보호 위해 `1`(직렬)이었으나, **현재 기본값은 `4`로 변경됨** (병렬을 default 로, 직렬은 planner 판단 시에만). 최신 값은 `src/forge/config.py` 참조.

```python
max_parallel_branches: int = 1   # (도입 시점 값. 현재는 4)
# 최대 병렬 분기 수

branch_fail_escalate_threshold: int = 2
# 한 분기가 몇 번 연속 실패하면 기획자 재호출할지
```

환경변수: `FORGE_MAX_PARALLEL_BRANCHES`, `FORGE_BRANCH_FAIL_ESCALATE_THRESHOLD`. 1 ≤ N ≤ 4 캡 강제.

### 단계 1. 체크포인트 트리화 (하위 호환)

**무엇을 하나**: `Checkpoint` 모델에 분기 상태 리스트 추가.

```python
class BranchState(BaseModel):              # 신규 모델
    branch_id: str                          # 예: "branch-1"
    phase: Phase                             # 이 분기의 현재 단계
    sprint: int                              # 스프린트 번호
    consecutive_fails: int = 0              # 연속 실패 횟수
    worktree_path: str = ""                 # 이 분기의 git worktree 경로
    git_branch: str = ""                    # 이 분기의 git 브랜치명
    status: str = "active"                  # "active" / "passed" / "failed" / "escalated"
    detail: str = ""
    timestamp: str

class Checkpoint(BaseModel):
    phase: Phase = Phase.NONE                # 기존 필드 (trunk용)
    detail: str = ""
    timestamp: str = Field(...)
    branches: list[BranchState] = []        # 신규, 비어있으면 단일 분기
```

**왜 호환되나**: 옛 `.harness-checkpoint`에 `branches` 키 없어도 빈 리스트로 로드 → 옛 동작 동일.

### 단계 2. git worktree 관리 모듈 + auto-commit 정책

#### 2-1. 신규 파일 `src/forge/worktree.py`

```python
def create_branch_worktrees(
    project_root: Path,                     # trunk worktree 위치
    sprint_num: int,                         # 스프린트 번호
    branch_ids: list[str],                  # ["branch-1", "branch-2", ...]
    base_ref: str = "HEAD",                 # 분기 시작점 git ref
) -> list[BranchWorktree]:
    """sprint 시작 시 분기 워크트리 N개 생성.

    각 분기에 대해:
    1. git worktree add .worktrees/sprint-{N}-{branch_id} -b forge/sprint-{N}-{branch_id} {base_ref}
    2. .worktrees/ 폴더는 .gitignore에 추가 (기존 _ensure_gitignore 확장)
    """

def auto_commit_worktree(
    worktree_path: Path,
    branch_id: str,
    sprint_num: int,
    turn_kind: str,                          # "generator" 또는 "evaluator"
) -> CommitResult:
    """generator/evaluator subprocess 종료 직후 호출.

    동작:
    1. git -C {worktree} add -A
    2. 변경 없으면 (`git diff --cached --quiet`) skip + status="no_changes"
    3. 변경 있으면 git -C {worktree} commit -m "forge: sprint-{N}-{branch_id} {turn_kind} turn"
    """

def auto_commit_trunk_artifacts(
    trunk_root: Path,
    turn_kind: str,                          # "planner-spec" / "planner-contract" / "finalizer-merge" 등
    sprint_num: int,
) -> CommitResult:
    """planner/finalizer subprocess가 trunk artifacts 시스템 산출물을 쓴 직후 호출.

    동작:
    1. git -C {trunk_root} add artifacts/spec.md artifacts/sprint-contract.md artifacts/plan-review.md
       (사용자 코드 src/, tests/ 등은 손대지 않음 — pathspec 명시)
    2. 변경 없으면 skip + status="no_changes"
    3. 변경 있으면 git commit -m "forge: {turn_kind} sprint-{N}"

    호출 시점:
    - planner subprocess 종료 직후 (spec/contract/plan-review 갱신을 worktree로 전파해야 함)
    - finalizer가 trunk 머지를 끝내고 sprint-N-done.md를 sync 가능 영역에 쓴 직후

    안전: pathspec을 명시해서 src/, tests/ 같은 사용자 영역은 절대 stage하지 않음.
    """

def remove_branch_worktrees(
    project_root: Path,
    worktrees: list[BranchWorktree],
) -> None:
    """sprint 종료 후 분기 워크트리 정리. git worktree remove {path} --force"""

def merge_into_trunk(
    project_root: Path,
    branch_refs: list[str],                  # 머지할 분기 브랜치들
    strategy: str = "no-ff",                 # --no-ff (분기 흔적 보존)
) -> MergeResult:
    """trunk로 분기들을 차례 머지 (--no-commit 옵션).
    충돌 시 conflict_files를 반환만 하고 abort는 finalizer가 결정.
    """

def verify_finalizer_merge_scope(
    project_root: Path,
    expected_conflict_files: set[str],       # finalizer가 편집했어야 하는 파일 집합
) -> ScopeViolation | None:
    """finalizer 머지 commit 직후 자동 위반 감지.

    동작:
    1. git diff --stat HEAD~1 로 변경 파일 집합 X 수집
    2. X - expected_conflict_files 에 포함된 파일 = scope 위반
    3. 위반 있으면 ScopeViolation(파일목록) 반환, 없으면 None
    4. 호출자가 위반 발견 시 git revert + 사용자 게이트 발사
    """
```

#### 2-2. auto-commit 정책 (forge 정신과의 충돌 명시)

**실측 사실**: `scaffold/agents/journal.md`에 "git commit도 하지 마라, 사용자가 직접 결정"이 명시되어 있다. 즉 forge의 기존 정신은 **"trunk에서 자동 커밋 금지"**다.

**병렬 모드 정책 분리** (둘이 충돌하지 않게 영역 나눔):

| 영역 | 커밋 주체 | 근거 |
|---|---|---|
| trunk **사용자 코드** (`src/`, `tests/` 등 git 추적) | **사용자 결정 유지** (기존 forge 정신) | journal.md 정신 보존, 사용자 코드는 손 안 댐 |
| trunk **시스템 산출물** (`artifacts/spec.md`, `sprint-contract.md`, `plan-review.md`) | **orchestrator 자동 커밋** (신규 정책) | planner가 sprint-contract.md를 쓴 직후 git에 반영되어야 worktree 생성 시 신규 내용이 sync됨. 안 그러면 분기 워크트리가 옛 contract를 봄 |
| `.worktrees/sprint-*` (병렬 분기, 임시 작업 공간) | **orchestrator 자동 커밋** (신규 정책) | finalizer가 머지하려면 분기 ref에 commit이 있어야 함 |
| trunk로의 머지 (finalizer 작업) | finalizer가 머지 커밋 생성 (`--no-ff`) | sprint 결과를 trunk에 영구 반영, 사용자 게이트로 승인 |

**핵심 원칙**: **사용자 코드는 손 안 댐. 시스템 산출물만 자동 커밋.**

비유: **공장에서 작업자의 노트(사용자 코드)는 본인 결재 후 캐비넷 보관. 본사 사무직(시스템)이 쓴 보고서/계획서는 시스템 도장으로 즉시 보관.**

비유: **공장 안의 임시 작업대(.worktrees)는 자동 도장 찍는다. 정식 출고대(trunk)는 사용자 결재 후 도장.**

#### 2-3. .gitignore 정책

`cli.py::_ensure_gitignore` 확장으로 추가할 항목 (단계 3의 artifacts 정책과 일치):
```
.worktrees/                              # git worktree 임시 폴더
artifacts/branches/                       # 분기별 progress-log/qa-report 격리
artifacts/sprint-*-done.md                # finalizer 통합 보고서
artifacts/.merge-decisions/               # 충돌 해결 기록
```

git 추적 유지하는 artifacts/ 파일 (단계 3에서 다시 다룸): `spec.md`, `sprint-contract.md`, `plan-review.md`, `cost-log.jsonl`, `.harness-checkpoint`.

#### 2-4. 근거 (신규 모듈 정당화)

신규 모듈 `worktree.py`를 만드는 이유: git 관련 책임이 한 곳에 모이는 게 응집도 높음. 기존 `cli.py::_ensure_gitignore` 같은 git 흔적이 분산되어 있어서 통합. forge가 git 명령 직접 호출하는 정책 위배를 **이 1개 모듈에 격리**.

### 단계 3. artifacts/ 폴더 + paths 헬퍼 확장 (하이브리드 c 정책)

#### 3-1. 디렉토리 구조와 git 추적 영역

```
프로젝트 root/                                  ← trunk worktree (사용자가 보는 메인 폴더)
  src/, tests/, ...
  artifacts/
    spec.md                          [git 추적]   ← trunk SSoT, worktree 자동 sync
    sprint-contract.md               [git 추적]   ← trunk SSoT
    plan-review.md                   [git 추적]   ← trunk SSoT
    cost-log.jsonl                   [git 추적]   ← 기존과 동일
    .harness-checkpoint              [git 추적]   ← 기존과 동일
    branches/                        [.gitignore] ← trunk만 사용, worktree에는 없음
      branch-1/
        progress-log.md
        qa-report.md
        whisper-queue.jsonl                       ← 단계 9
      branch-2/
        ...
    sprint-1-done.md                 [.gitignore] ← finalizer 산출물
    .merge-decisions/                [.gitignore] ← 충돌 해결 기록
  .worktrees/                        [.gitignore] ← git worktree (단계 2)
    sprint-1-branch-1/
      src/, tests/                                 ← 분기 자기 코드 트리 (격리)
      artifacts/
        spec.md                                    ← git이 자동 sync (trunk SSoT 카피)
        sprint-contract.md                         ← git이 자동 sync
        plan-review.md                             ← git이 자동 sync
        (branches/, sprint-*-done.md 없음 — .gitignore되어 있음)
```

#### 3-2. 왜 하이브리드인가 (사용자 채택 옵션 c)

**git 추적 유지 영역** = "모든 분기가 같은 정보를 읽어야 하는 SSoT":
- `spec.md`: 프로젝트 본질 axioms, 모든 분기가 참조
- `sprint-contract.md`: 분기 분할 정보 포함, 모든 분기가 자기 spec 부분을 읽음
- `plan-review.md`: planner 검토 결과, 모든 분기가 참조

→ trunk에서 변경하면 git이 모든 worktree로 자동 sync. generator/evaluator는 자기 cwd의 `artifacts/spec.md`를 상대 경로로 읽으면 됨.

**`.gitignore` 영역** = "분기별 또는 sprint별로 격리되어야 하는 산출물":
- `artifacts/branches/`: 각 분기가 자기 progress-log/qa-report 작성, 다른 분기와 무관
- `artifacts/sprint-*-done.md`: finalizer가 trunk에서만 생성
- `artifacts/.merge-decisions/`: 충돌 해결 기록, trunk에서만

→ 이 영역은 worktree에 없으니, generator/evaluator가 **trunk의 절대 경로를 알아야** 쓸 수 있다. 단계 6의 prompt 주입에서 처리.

#### 3-3. `ProjectPaths` 확장 (`config.py`)

```python
class ProjectPaths(BaseModel):
    # 기존 필드들 그대로 (회귀 0)
    project_root: Path
    artifacts: Path
    spec: Path                                # = artifacts / "spec.md"
    sprint_contract: Path                     # = artifacts / "sprint-contract.md"
    plan_review: Path                         # = artifacts / "plan-review.md"
    progress_log: Path                        # = artifacts / "progress-log.md"  ← trunk 모드
    qa_report: Path                           # = artifacts / "qa-report.md"     ← trunk 모드
    whisper_queue: Path                       # = artifacts / ".whisper-queue.jsonl"

    # 신규 헬퍼
    @property
    def trunk_root(self) -> Path:
        """trunk worktree의 절대 경로 (worktree에서도 trunk를 가리킴).
        git rev-parse --git-common-dir 의 부모 디렉토리로 계산.
        """

    def branch_paths(self, branch_id: str, *, in_worktree: bool = False) -> "ProjectPaths":
        """분기별 paths.
        
        branch_id="trunk" → 자기 자신 반환 (회귀 0).
        in_worktree=True → worktree cwd 기준 경로 (generator/evaluator subprocess가 사용).
        in_worktree=False → trunk 절대 경로 기준 (orchestrator/finalizer가 사용).
        
        분기별 progress-log/qa-report/whisper-queue는 항상 **trunk 절대 경로**
        (artifacts/branches/{branch_id}/...)를 가리킴. spec/sprint-contract는
        in_worktree에 따라 worktree 또는 trunk.
        """
```

#### 3-4. generator/evaluator prompt에 절대 경로 주입

generator subprocess가 `cwd=.worktrees/sprint-1-branch-1`로 떠 있어도, **자기 progress-log/qa-report는 trunk artifacts/branches/branch-1/에 써야 한다** (.gitignore 영역이라 worktree에 없음).

`run_agents_parallel`이 build_prompt 단계에서 절대 경로 주입:
```python
prompt = f"""
당신은 분기 {spec.id}의 generator다.
- sprint-contract.md는 자기 cwd 안의 artifacts/sprint-contract.md (자동 sync)
- 자기 진행 로그는 **{trunk_absolute_path}/artifacts/branches/{spec.id}/progress-log.md**
- 자기 작업 영역: files_owned = {spec.files_owned}
- 자기 영역 외 파일 수정 금지
"""
```

비유: **공용 도면(spec)은 모든 작업대에 자동 복사되지만, 작업 일지는 본부 캐비넷의 자기 칸에만 쓴다.**

### 단계 4. Planner 출력 + 파서 모듈

**신규 파일** `src/forge/contract.py`:

**근거 (parse_branches 위치)**: 실측 grep 결과 `sprint-contract` 파싱이 현재 `orchestrator.py`, `planner.py`, `judgment.py`에 분산. 명시적 파서 모듈은 없음. 신규 모듈로 분리해 응집도 ↑ + 단위 테스트 용이. 대안(planner.py에 함수 추가)도 유효하나, contract 자체가 spec/planner와 별개 개념이라 분리가 자연스러움.

```python
@dataclass
class BranchSpec:
    id: str                                    # "branch-1"
    title: str                                 # "Auth module"
    tasks: list[str]
    depends_on: list[str]
    files_owned: list[str]                    # glob 패턴

def parse_branches(sprint_contract_text: str) -> list[BranchSpec]:
    """sprint-contract.md의 'Parallel Task Graph (YAML)' 섹션 파싱.
    섹션 부재 시 [BranchSpec(id="trunk", ...)] 1개 반환 (회귀 보호).
    """
```

**Planner 시스템 프롬프트 확장** (`scaffold/agents/planner.md` + `.claude/agents/planner.md`):
- "병렬화 가능성 판단 절차" 섹션 신설
- 독립성 3 기준: 파일 충돌 없음 / 의존성 DAG 위에서 동시 가능 / 인터페이스 명시
- 충족 시 `## Parallel Task Graph (YAML)` 섹션 추가:
  ```yaml
  branches:
    - id: branch-1
      title: "인증 모듈"
      tasks: [...]
      depends_on: []
      files_owned: ["src/auth/*", "tests/auth/*"]
  ```
- 1개만이면 섹션 생략 가능 → parse_branches 폴백

### 단계 5. 동시 N개 실행 함수 신설

**`run_agent_sync`는 변경 없이 보존** (단일 분기 + Finalizer 경로에서 그대로 사용).

**신규 함수** `runner.py::run_agents_parallel`:

```python
async def _gather(branch_specs, project_paths, config, agent_kind):
    sem = asyncio.Semaphore(config.max_parallel_branches)
    # 세마포어 = 동시 통과 인원 제한기

    async def _run_one(spec):
        async with sem:
            bp = project_paths.branch_paths(spec.id)
            # 자기 worktree의 cwd를 받음 (단계 2에서 생성됨)
            worktree_cwd = project_paths.worktree_path_for(spec.id)
            
            session = ClaudeCliSession(
                agent=agent_kind,
                cwd=worktree_cwd,                       # 분기 worktree (격리)
                # session_id 자동 uuid (cli_session.py:81)
                # env 자동 정화 (cli_session.py:42, OAuth만)
            )
            runner_inst = ForgeAgentRunner(
                session,
                whisper_queue_path=bp.whisper_queue,    # 분기별 큐 (단계 9)
                notifier=_prefixed_notifier(notifier, spec.id),  # 단계 9
            )
            return await runner_inst.run(build_prompt(spec, bp))
    
    return await asyncio.gather(*[_run_one(s) for s in branch_specs])
```

**왜 cli_session 자체는 변경 0**: 이미 비동기 + uuid 자동 + env 자동 정화로 동시 실행 안전성이 코드 자체에 내장되어 있음.

### 단계 6. Orchestrator 분기 선택 + Finalizer 호출 + Evaluator 입력 경로 주입

**Orchestrator sprint 루프 변경** (`run_agent_sync("generator", ...)` 호출 지점 주변):

```python
# === Phase 3-4 (Generating + Evaluating) 분기 선택 ===
sprint_contract_text = paths.sprint_contract.read_text(encoding="utf-8")
branches = parse_branches(sprint_contract_text)

if len(branches) == 1:
    # === 단일 분기 모드 (회귀 0) ===
    # 기존 코드 그대로
    result = run_agent_sync("generator", paths.project_root, ...)
    result = ev.run_evaluate(config, paths, notifier=notifier)
else:
    # === 다중 분기 모드 ===
    # 0. planner가 sprint-contract.md를 쓴 직후 trunk artifacts 자동 커밋
    #    (worktree 생성 전이라야 신규 contract가 worktree로 sync됨)
    auto_commit_trunk_artifacts(paths.project_root, "planner-contract", sprint_num)
    
    # 1. worktree 생성 (이제 신규 sprint-contract.md를 가진 trunk에서 분기)
    worktrees = create_branch_worktrees(paths.project_root, sprint_num, [b.id for b in branches])
    cp.branches = [BranchState(branch_id=b.id, phase=Phase.GENERATING, ...) for b in branches]
    cp.save(paths.checkpoint_file)
    
    # 2. N개 generator 동시 실행
    gen_results = run_agents_parallel(branches, paths, config, "generator")
    
    # 2.5 generator 종료 직후 worktree auto-commit (단계 2-2 정책)
    for spec, wt in zip(branches, worktrees):
        auto_commit_worktree(wt.path, spec.id, sprint_num, turn_kind="generator")
    cp.advance(Phase.GENERATING_DONE)
    
    # 3. N개 evaluator 1:1 동시 실행 (paths 분기별 주입)
    eval_results = run_evaluators_parallel(branches, paths, config)
    
    # 3.5 evaluator 종료 직후 worktree auto-commit (qa-report는 .gitignore라
    # 사실 evaluator는 worktree commit할 게 적지만, src 추가 수정이 있으면 잡힘)
    for spec, wt in zip(branches, worktrees):
        auto_commit_worktree(wt.path, spec.id, sprint_num, turn_kind="evaluator")
    cp.advance(Phase.EVALUATING_DONE)
    
    # 4. Finalizer 호출 (단계 7). 머지 시점에 분기 ref에 commit이 있음을 보장.
    finalize_result = run_finalize(config, paths, branches, worktrees, notifier=notifier)
    
    # 5. 결과 분기 처리 (성공 / 부분 머지 + escalation / 충돌)
    if finalize_result.status == "merged":
        # 정상 흐름: 전체 머지 성공 → 모든 worktree 정리
        remove_branch_worktrees(paths.project_root, worktrees)
        auto_commit_trunk_artifacts(paths.project_root, "finalizer-merge", sprint_num)
    elif finalize_result.status == "needs_escalation":
        # PASS 분기 부분 머지 (단계 8-2)
        pass_specs = [b for b in branches if ev.is_pass(paths, branch_id=b.id)]
        if pass_specs:
            run_finalize(
                config, paths, pass_specs,
                [wt for wt in worktrees if wt.branch_id in {b.id for b in pass_specs}],
                partial=True, notifier=notifier,
            )
            # PASS worktree만 정리, FAIL worktree는 보존 (디버깅 + 다음 라운드 참조)
            remove_branch_worktrees(paths.project_root, [wt for wt in worktrees if wt.branch_id in {b.id for b in pass_specs}])
            auto_commit_trunk_artifacts(paths.project_root, "finalizer-partial-merge", sprint_num)
        # Planner 재호출 (단계 8-2의 4단계)
        run_planner_replan(paths, branches, trunk_diff=...)
        auto_commit_trunk_artifacts(paths.project_root, "planner-replan", sprint_num)
    elif finalize_result.status == "merge_conflict":
        # worktree 보존, 사용자 게이트 발사 (단계 7 finalizer 처리)
        pass
```

**Evaluator 변경 명세** (`evaluator.py::run_evaluate`):
사용자 지적 정확: 현재 `paths.whisper_queue`, `paths.qa_report` 직접 참조 → branch별로 분리 필요. **0줄 변경 아님**.

```python
def run_evaluate(
    config: ForgeConfig,
    paths: ProjectPaths,
    *,
    notifier=None,
    branch_id: str = "trunk",                 # 신규 인자, 기본 trunk (회귀 0)
) -> RunResult:
    bp = paths.branch_paths(branch_id)         # 신규
    prompt = (
        "artifacts/sprint-contract.md의 각 항목에 대해 현재 구현을 평가하라. "
        f"artifacts/branches/{branch_id}/qa-report.md에 보고서를 작성하라. "  # 분기별 경로
        "종합 판정은 PASS 또는 FAIL 중 하나여야 한다."
    ) if branch_id != "trunk" else (
        # 기존 프롬프트 그대로 (회귀 0)
        "artifacts/sprint-contract.md의 각 항목에 대해 현재 구현을 평가하라. "
        "artifacts/qa-report.md에 보고서를 작성하라. "
        "종합 판정은 PASS 또는 FAIL 중 하나여야 한다."
    )
    return run_agent_sync(
        "evaluator",
        bp.project_root,
        prompt,
        max_turns=config.evaluator_max_turns,
        whisper_queue_path=bp.whisper_queue,    # 분기 큐
        notifier=notifier,
    )
```

`is_pass`, `validate_qa_report`도 `branch_id` 인자 추가.

### 단계 7. Finalizer 에이전트 신설

**신규 파일**:
- `c:\1.Project\THE_FORGE\scaffold\agents\finalizer.md` (배포 원본)
- `c:\1.Project\THE_FORGE\.claude\agents\finalizer.md` (운영 카피)
- `c:\1.Project\THE_FORGE\src\forge\agents\finalizer.py` (호출 함수)

**시스템 프롬프트 골자** (`finalizer.md`):

```yaml
---
name: finalizer
tools: [Read, Edit, Bash]                      # Edit 허용 (충돌 마커 편집용), Write 차단
---
```

- **입력**: 모든 `artifacts/branches/branch-*/qa-report.md`, 각 분기 git ref, trunk `sprint-contract.md`, trunk `spec.md`
- **작업**:
  1. 각 분기 qa-report.md 종합 판정 확인. **FAIL 분기가 있으면 부분 머지 모드로 전환** (단계 8-2 참조). 전부 PASS면 정상 모드.
  2. `git merge forge/sprint-{N}-{branch_id} --no-ff --no-commit` 차례 시도 (`--no-commit`은 충돌 확인 후 결정하기 위함)
  3. **충돌 발생 시 분기**:
     - 충돌 파일들의 충돌 마커 (`<<<<<<<` / `=======` / `>>>>>>>`) 범위 안에서만 Edit으로 해결 시도
     - 해결 결정마다 `artifacts/.merge-decisions/decision-{NNN}.md` 작성 ("어느 분기 채택 / 다른 분기 무엇 버림 / 이유")
     - 의미적 충돌이라 풀 수 없으면 `git merge --abort` + 사용자 게이트로 escalate
     - 해결 가능하면 `git commit`으로 머지 마무리
  4. 머지 commit 직후 **자동 위반 감지** (`verify_finalizer_merge_scope`): `git diff --stat HEAD~1`로 변경 파일이 충돌 파일 집합에 포함되는지 확인. 위반 시 `git revert` 후 사용자 게이트
  5. 성공 시 `artifacts/sprint-{N}-done.md` 통합 보고서 작성. 사용된 decision-NNN 목록과 한 줄 요약 노출 (사용자 사후 검토용)
- **편집 허용 범위** (시스템 프롬프트로 강제):
  - **허용**: `git status`가 unmerged로 표시한 파일의 충돌 마커 범위 안만
  - **금지**: qa-report.md 수정 (FAIL→PASS 바꿔치기), 충돌 안 난 파일 수정 ("이왕 보는 김에..." 차단), 새 기능 추가 (어느 분기에도 없던 코드)

**부분 머지 모드** (escalation 시, 단계 8-2 호출):
- orchestrator가 `partial=True` + `merge_only_branch_ids=[...PASS만...]` 인자로 호출
- finalizer는 그 부분집합만 trunk로 머지, 나머지 worktree와 ref는 그대로 보존
- 부분 머지 완료 시 `artifacts/sprint-{N}-partial-{round}.md` 보고서 작성 (sprint-N-done.md와 구분)

**코드 구현**:
```python
def run_finalize(
    config: ForgeConfig,
    paths: ProjectPaths,
    branches: list[BranchSpec],
    worktrees: list[BranchWorktree],
    *,
    notifier=None,
) -> FinalizeResult:
    # 1. qa-report.md FAIL 사전 검사 (LLM 호출 전 빠른 검사)
    fail_branches = [b.id for b in branches if not ev.is_pass(paths, branch_id=b.id)]
    if fail_branches:
        return FinalizeResult(status="needs_escalation", fail_branches=fail_branches)
    
    # 2. finalizer LLM 세션
    prompt = build_finalize_prompt(branches, worktrees)
    return run_agent_sync("finalizer", paths.project_root, prompt, notifier=notifier)
```

### 단계 8. FAIL 단계 격상 + 일괄 알림 UX

**branch별 FAIL 처리 정책** (1-D 하이브리드):

```
각 분기 evaluator 결과 ⤵
├─ PASS → cp.branches[i].status = "passed"
└─ FAIL 
   ├─ cp.branches[i].consecutive_fails += 1
   ├─ 임계점 미만 (< branch_fail_escalate_threshold) 
   │   └─ 같은 분기에서 generator 재시도 (사용자 알림 X, 자동)
   └─ 임계점 도달
       ├─ cp.branches[i].status = "escalated"
       ├─ Planner 재호출 → 새 sprint-contract.md 작성
       └─ plan-review 게이트 우회
```

#### 8-2. PASS 분기 부분 머지 (escalation 발생 시)

사용자 추천 A2: **escalation이 발생하면 PASS 분기 결과는 버리지 않고 trunk로 먼저 머지**한다. Planner가 재호출될 때 PASS된 작업을 인지하고 그 위에서 FAIL 영역만 재분할.

**예외 흐름 (단계 6 다중 분기 모드의 "원래는 모든 분기 끝나면 finalizer가 한 번에 합친다" 정책의 예외)**:

```
모든 분기 evaluator 끝남
└─ FAIL 분기 중 escalation 임계점 도달한 게 있나?
   ├─ 없음 (모두 PASS 또는 재시도 중)
   │   └─ 정상 흐름: finalizer가 4개 모두 한 번에 머지 (단계 7)
   └─ 있음 (escalation 발생)
       ├─ 1단계: orchestrator가 finalizer에게 PASS 분기만 머지 요청
       │   └─ finalizer가 PASS branch만 git merge --no-ff 차례 실행
       │       (실패 분기 worktree와 ref는 보존)
       ├─ 2단계: PASS 분기들의 worktree 정리 (`git worktree remove`)
       ├─ 3단계: trunk artifacts 자동 커밋 (PASS 분기 결과 + 잔존 FAIL 상태)
       ├─ 4단계: Planner 재호출
       │   └─ 프롬프트에 "다음을 인지하라" 컨텍스트 주입:
       │       - PASS 완료된 분기들과 무엇이 trunk에 머지됐는지
       │       - escalation된 분기들이 무엇을 시도했는지 (qa-report.md 인용)
       │       - files_owned는 어디까지 안전한지
       └─ 5단계: 새 sprint-contract.md 작성 → 다음 sprint 라운드 진입
```

**왜 예외인가**: 원래 정책("모든 분기 완료 후 한 번에 합친다")이 가지는 가치는 "trunk가 sprint 단위로 깔끔하게 진행됨". 이 예외는 깨끗함을 깨지만, 합격한 작업을 버리는 손실보다 작다.

**리스크**: PASS 분기 부분 머지 후 Planner가 트렁크 상태를 정확히 인지 못하면 다음 분할에서 충돌. 방어: Planner 프롬프트에 trunk diff 요약 주입.

비유: **4명 중 2명 합격, 2명 실패. 합격 2명 결과는 본사로 옮겨두고, 기획자에게 "2명분은 끝났으니 나머지 영역만 새로 짜라" 지시.**

**FAIL 알림 (병렬 UX)** - `_notify_fail_with_options` 수정:

사용자 지적: 현재 1 sprint = 1 FAIL 알림 가정. 병렬 N FAIL 시 어떻게?

**채택안: 일괄 통보 + escalation 시점만 알림**:
- consecutive_fails 임계점 미만 → 자동 재시도 (사용자 알림 X)
- 임계점 도달한 분기가 1개 이상 → 1번의 일괄 알림 발사:
  ```
  Sprint 1 ESCALATION
  
  분기별 점수:
  • branch-1: PASS
  • branch-2: FAIL (2/2 escalated)
  • branch-3: FAIL (2/2 escalated)
  
  → Planner 재호출 예정. 게이트:
  /resume  — Planner 재호출 진행 (기본)
  /skip    — 이대로 다음 sprint
  /stop    — 중단
  ```
- 1 sprint = 최대 1 알림 (현 forge UX와 동형)

### 단계 9. Whisper 라우팅 + 알림 prefix

**현재 모습**: `paths.whisper_queue = artifacts / ".whisper-queue.jsonl"` 단일 파일. Slack receiver가 사용자 평문 메시지를 한 줄씩 append.

**병렬 모드 라우팅 규칙**:

| 사용자 메시지 형태 | 라우팅 |
|---|---|
| `@branch-2 메시지` | `artifacts/branches/branch-2/whisper-queue.jsonl`에만 push |
| 일반 메시지 (prefix 없음) | **trunk whisper-queue.jsonl로 push** (= 다음 finalizer 또는 다음 sprint planner가 받음) |
| `@all 메시지` | 모든 활성 분기 큐에 broadcast |

**왜 prefix 라우팅?**: 자동 추론(가장 활성 분기 등)은 비결정적 → 사용자가 어디로 가는지 모른다. 명시적 prefix가 forge의 "사용자가 직접 결정" 정신과 일치.

**알림 prefix 태깅**:
- N개 분기 동시 알림 → 단일 채널에 `[branch-1] generator 시작` 형태
- `notifier.notify` 시그니처 그대로, 호출부에서 prefix prepend
- Slack rate limit 보호: 동시 발사 N개 → 0.5초 간격 큐잉 (간단한 토큰 버킷)

---

## 5. 재사용 가능 기존 도구

| 도구 | 변경? |
|---|---|
| `ClaudeCliSession` | **0줄** (이미 비동기, uuid 자동, env 정화) |
| `ForgeAgentRunner` | 0줄 (그대로 N개 인스턴스화) |
| `run_agent_sync` | 0줄 (단일 분기 + finalizer가 호출) |
| `Checkpoint.load/save` | 필드 1개 추가 (BranchState 리스트) |
| `evaluator.run_evaluate` | **branch_id 인자 추가** (사용자 지적대로 0줄 아님) |
| `evaluator.is_pass` / `validate_qa_report` | branch_id 인자 추가 |
| `notifier.notify` | 0줄 (호출부에서 prefix prepend) |
| `build_child_env` | 0줄 |
| `cli.py::_ensure_gitignore` | `.worktrees/` 항목 추가 |

---

## 6. 검증 방법

테스트 경로: `c:\1.Project\THE_FORGE_TEST` (코드와 분리).

| 시나리오 | 조건 | 통과 기준 |
|---|---|---|
| 1. 회귀 (N=1) | `FORGE_MAX_PARALLEL_BRANCHES=1` 기본 | 기존 골든과 byte-level 일치, `.worktrees/` 미생성, `artifacts/branches/` 미생성 |
| 2. 병렬 골든 (N=2) | spec.md를 `auth/` + `db/` 독립 모듈 | 두 worktree 생성, 두 generator 동시 실행, finalizer 머지 성공, `sprint-1-done.md` 생성, `.worktrees/` 정리됨 |
| 3. FAIL 격상 | branch-2 일부러 FAIL, 임계점 2 | 2회 FAIL 후 Planner 재호출, 새 sprint-contract 생성, 일괄 알림 1건 |
| 4. 머지 충돌 → 자체 해결 | 두 분기가 같은 파일의 다른 라인 수정 | finalizer가 충돌 마커 범위 안에서 Edit으로 해결 + `decision-NNN.md` 기록 + 머지 commit 성공 |
| 4-2. 의미적 충돌 → escalate | 두 분기가 같은 파일의 같은 의미를 다르게 처리 | finalizer가 `git merge --abort` + `decision-NNN.md`에 "풀 수 없음" 기록 + 사용자 게이트 |
| 4-3. scope 위반 감지 | finalizer가 충돌 안 난 파일을 수정한 경우 (가설 시나리오) | `verify_finalizer_merge_scope`가 위반 발견 → 자동 `git revert` + 사용자 게이트 |
| 4.5. auto-commit 동작 검증 | generator subprocess 종료 후 | `.worktrees/sprint-1-branch-1` 에 `forge: sprint-1-branch-1 generator turn` 커밋 1건 존재. 변경 없으면 커밋 0건 (no_changes 처리) |
| 4.6. 하이브리드 artifacts 검증 | trunk에서 `spec.md` 수정 → generator 시작 | worktree의 `artifacts/spec.md`가 자동 sync된 같은 내용. `artifacts/branches/`는 worktree에 미존재, trunk에만 있음 |
| 4.7. trunk artifacts 자동 커밋 | planner가 sprint-contract.md를 쓴 직후 worktree 생성 | worktree 생성 시 신규 sprint-contract.md가 sync됨 (옛 버전 X). git log에 `forge: planner-contract sprint-N` 커밋 존재. **src/ 변경은 stage 안 됨** (pathspec 안전성) |
| 4.8. PASS 분기 부분 머지 (escalation) | 2분기 PASS, 2분기 FAIL escalated | PASS 2분기만 trunk 머지, FAIL 2분기 worktree 보존, `sprint-1-partial-1.md` 작성, Planner 재호출, 새 sprint-contract 작성 |
| 5. self-rationalization 방어 | branch-1 FAIL인데 finalizer 호출 강제 | finalizer가 사전 검사에서 `needs_escalation` 반환, LLM 호출 자체 안 일어남 |
| 6. 세마포어 한도 | max=4인데 planner가 5개 출력 | 동시 4개 실행, 1개 대기 |
| 7. whisper prefix | `@branch-2 hello` 입력 | `artifacts/branches/branch-2/whisper-queue.jsonl`에만 append |
| 8. 단위 테스트 | parse_branches / BranchState / Checkpoint v1→v2 / worktree 함수 | 폴백 / round-trip / 옛 파일 호환 / git 명령 호출 검증 |

### 직접 확인 명령
```powershell
# 회귀 (N=1, 기본)
forge run "간단한 hello world"
# 통과 기준: .worktrees/ 폴더 미생성

# 병렬 (N=2)
$env:FORGE_MAX_PARALLEL_BRANCHES = "2"
forge run "auth 모듈과 db 모듈 동시 개발"
# 통과 기준: .worktrees/sprint-1-branch-1, sprint-1-branch-2 존재 후 정리
```

---

## 7. 확인 불가/리스크

| 리스크 | 문제 | 대응 |
|---|---|---|
| Max 쿼터 동시 세션 한도 명시 없음 | Anthropic 공식 문서 미명시 | 기본 1, 최대 4 캡. 운영 관측 |
| forge가 git 명령 호출 → 정책 변경 | "git 직접 X" 정신 위배 | `worktree.py` 1개 모듈에 집중 → 격리. 사용자 명시 채택 |
| auto-commit이 journal.md 정신과 충돌 | "사용자가 commit 결정" 가이드 vs orchestrator 자동 커밋 | 영역 분리 3분할: **사용자 코드는 사용자 결정 / 시스템 산출물(artifacts/spec, contract, plan-review) 자동 커밋 / .worktrees 자동 커밋**. journal.md에 명시 추가 |
| PASS 분기 부분 머지 후 Planner 인지 실패 | 재호출된 Planner가 trunk 변경 사항을 모르고 같은 task 재분할 | Planner 프롬프트에 trunk diff 요약 + PASS 분기 결과 명시 주입 |
| worktree의 artifacts/branches/ 부재로 generator 혼란 | worktree에 `.gitignore` 영역이 없으니 상대 경로로 못 씀 | prompt에 trunk 절대 경로 주입 (단계 3-4) |
| Finalizer self-rationalization | qa-report 재해석 또는 scope 위반 위험 | **방어 4종**: 시스템 프롬프트 범위 제한 + decision-NNN.md 의무 + 자동 위반 감지(`verify_finalizer_merge_scope`) + 사용자 사후 검토 |
| Finalizer가 단순 vs 의미적 충돌을 잘못 판정 | "이건 단순"이라고 자기 판단하면 무엇이든 단순으로 처리 가능 | decision-NNN.md에 "왜 단순으로 판단했는지" 강제 기록 + 사후 검토로 사용자가 잘못된 판정 발견 시 revert |
| 체크포인트 마이그레이션 | N≥2 sprint 중간에 down되면 worktree 잔존 | 첫 릴리스: 재시작 시 worktree 정리 + sprint 처음부터 |
| Slack rate limit | N개 동시 알림 | 0.5초 간격 큐잉 |
| Agent Teams 공식 기능 도입? | v2.1.32+ experimental + tmux 대화형 기반 | forge 비대화형 모델과 미스매치, 미도입 |
| "swarm" 명칭 | Anthropic 공식 명칭 아님 | 본 plan은 swarm 미사용 |

---

## 8. 구현 대상 핵심 파일

### 신설 5개
| 파일 | 무엇 |
|---|---|
| `c:\1.Project\THE_FORGE\src\forge\worktree.py` | git worktree 관리 (단계 2) |
| `c:\1.Project\THE_FORGE\src\forge\contract.py` | parse_branches 파서 (단계 4) |
| `c:\1.Project\THE_FORGE\src\forge\agents\finalizer.py` | Finalizer 호출 함수 (단계 7) |
| `c:\1.Project\THE_FORGE\scaffold\agents\finalizer.md` | Finalizer 시스템 프롬프트 (배포 원본, 단계 7) |
| `c:\1.Project\THE_FORGE\.claude\agents\finalizer.md` | Finalizer 운영 카피 (단계 7) |

### 수정 7개
| 파일 | 변경 | 단계 |
|---|---|---|
| `src/forge/config.py` | 변수 2개 + `ProjectPaths.branch_paths` 헬퍼 | 0, 3 |
| `src/forge/checkpoint.py` | `BranchState` + `branches` 필드 | 1 |
| `src/forge/agents/runner.py` | `run_agents_parallel` 신규 함수 | 5 |
| `src/forge/agents/evaluator.py` | **`branch_id` 인자 추가** (사용자 지적 반영) | 6 |
| `src/forge/orchestrator.py` | 분기 선택 + Finalizer 호출 + FAIL 일괄 알림 | 6, 7, 8 |
| `scaffold/agents/planner.md` + `.claude/agents/planner.md` | Parallel Task Graph 섹션 가이드 | 4 |
| `src/forge/cli.py::_ensure_gitignore` | `.worktrees/`, `artifacts/branches/`, `artifacts/sprint-*-done.md`, `artifacts/.merge-decisions/` 추가 | 2, 3 |
| `scaffold/agents/journal.md` | "trunk는 사용자 결정 / .worktrees는 자동 커밋" 정책 분리 명시 추가 | 2-2 |
| `src/forge/notifier/base.py` 또는 호출부 | branch prefix 태깅 + 토큰 버킷 | 9 |
| `docs/USER_GUIDE.md` | 신규 환경변수 + worktree 동작 문서화 | 마무리 |

### 변경 없음 (재사용)
- `src/forge/agents/cli_session.py` (이미 비동기 + uuid + env 정화 다 됨)

---

## 9. 구현 분할 전략 (L 레이어별 + 멀티 세션)

### 9-1. 분할 그림

```
세션 A (기반)               세션 B (엔진)              세션 C (Finalizer/UX)
──────────────────         ──────────────────         ──────────────────
단계 0: 설정 변수            단계 4: contract.py        단계 7: finalizer.py + md
단계 1: BranchState         단계 5: run_agents_parallel 단계 8: FAIL 격상 + 부분 머지
단계 2: worktree.py         단계 6: orchestrator 분기  단계 9: whisper 라우팅 + prefix
단계 3: paths.branch_paths   + evaluator branch_id 주입
   │
   ▼ (A 완료 후 B,C 동시)
시간 ─────────────────────────────────────────────────────────────────►
```

- **세션 A**가 먼저 끝나야 B, C가 시작 (의존성 자연 순서)
- **세션 B와 C는 A 완료 후 동시 진행**
- **현 세션(나)는 오케스트레이터**: A → B/C 완료 후 통합 + 검증 시나리오 6 (회귀) 실행 + sprint-1-done.md 형식의 통합 보고서 작성

### 9-2. 저장 위치 + 첫 액션

ExitPlanMode 직후 첫 액션:
1. `C:\Users\immor\.claude\plans\planner-shimmying-wave.md` 내용을 `c:\1.Project\THE_FORGE\docs\parallel-branches-design.md`로 복사 (3개 세션이 동일 경로로 읽을 수 있게)
2. 본 plan 파일은 메타 plan으로 보존
3. git branch `feature/parallel-branches`를 base로 세션별 sub-branch 생성:
   - `feature/parallel-foundation` (세션 A)
   - `feature/parallel-engine` (세션 B, A에서 분기)
   - `feature/parallel-finalizer` (세션 C, A에서 분기)

### 9-3. 세션 A 프롬프트 (기반 레이어)

```
# 세션 A: THE FORGE 병렬 분기 기반 레이어 구현

## 컨텍스트
- 메인 plan: c:\1.Project\THE_FORGE\docs\parallel-branches-design.md (전체 9단계 설계서, 정독 필수)
- 너의 책임: 단계 0, 1, 2, 3 (기반 구조). 다른 세션 B/C가 너의 산출물 위에서 동시 진행한다.
- base 브랜치: feature/parallel-branches에서 분기한 feature/parallel-foundation
- 작업 디렉토리: c:\1.Project\THE_FORGE (코드), c:\1.Project\THE_FORGE_TEST (테스트 실행)

## 단계 0: 설정 변수 (단계 0 명세 그대로)
- src/forge/config.py::ForgeConfig 에 다음 추가:
  - max_parallel_branches: int = 1
  - branch_fail_escalate_threshold: int = 2
- 1 <= N <= 4 캡 강제
- 환경변수: FORGE_MAX_PARALLEL_BRANCHES, FORGE_BRANCH_FAIL_ESCALATE_THRESHOLD

## 단계 1: BranchState + Checkpoint.branches
- src/forge/checkpoint.py 에 BranchState(BaseModel) 신설
- Checkpoint 에 branches: list[BranchState] = [] 필드 추가
- 직렬화 round-trip 단위 테스트 + 옛 .harness-checkpoint(branches 키 없음) 로드 호환 검증

## 단계 2: worktree.py 신설 + auto-commit 정책
- src/forge/worktree.py 신설. 함수:
  - create_branch_worktrees(project_root, sprint_num, branch_ids, base_ref) -> list[BranchWorktree]
  - auto_commit_worktree(worktree_path, branch_id, sprint_num, turn_kind) -> CommitResult
  - auto_commit_trunk_artifacts(trunk_root, turn_kind, sprint_num) -> CommitResult
    (pathspec 명시: artifacts/spec.md, sprint-contract.md, plan-review.md만 stage)
  - remove_branch_worktrees(project_root, worktrees) -> None
  - merge_into_trunk(project_root, branch_refs, strategy="no-ff") -> MergeResult
    (--no-commit 옵션, 충돌 시 abort는 호출자 결정)
  - verify_finalizer_merge_scope(project_root, expected_conflict_files) -> ScopeViolation | None
- src/forge/cli.py::_ensure_gitignore 확장: .worktrees/, artifacts/branches/, artifacts/sprint-*-done.md, artifacts/.merge-decisions/
- scaffold/agents/journal.md 에 영역 분리 정책 명시 추가 ("trunk 사용자 코드는 사용자 결정 / 시스템 산출물 자동 / .worktrees 자동")

## 단계 3: ProjectPaths.branch_paths + trunk_root
- src/forge/config.py::ProjectPaths 에 헬퍼:
  - trunk_root @property (git rev-parse --git-common-dir 의 부모)
  - branch_paths(branch_id, *, in_worktree=False) -> ProjectPaths
    (branch_id="trunk"이면 self 반환, 회귀 0)

## 산출물
- git branch feature/parallel-foundation 에 commit
- 단위 테스트 통과 (BranchState round-trip, branch_paths 폴백, worktree 함수 모킹)
- **회귀 테스트 1번 시나리오 통과**: FORGE_MAX_PARALLEL_BRANCHES=1 기본값에서 기존 forge E2E 결과가 byte-level 일치

## 금지
- 단계 4-9 영역 손대지 마라 (다른 세션 영역)
- src/forge/orchestrator.py, runner.py, evaluator.py, planner.py 손대지 마라

## 완료 보고
- PR 본문에 (a) 추가/수정한 파일 목록, (b) 단위 테스트 결과, (c) 회귀 시나리오 1번 통과 증거, (d) 미해결 의문점
```

### 9-4. 세션 B 프롬프트 (병렬 실행 엔진)

```
# 세션 B: THE FORGE 병렬 실행 엔진 구현

## 컨텍스트
- 메인 plan: c:\1.Project\THE_FORGE\docs\parallel-branches-design.md (정독 필수)
- 너의 책임: 단계 4, 5, 6 (병렬 실행 엔진)
- base 브랜치: feature/parallel-foundation 완료 후 feature/parallel-engine 으로 분기
- 의존성: 세션 A가 만든 worktree.py, BranchState, ProjectPaths.branch_paths 사용

## 단계 4: contract.py + planner.md 확장
- src/forge/contract.py 신설:
  - BranchSpec dataclass
  - parse_branches(sprint_contract_text) -> list[BranchSpec]
    (Parallel Task Graph (YAML) 섹션 파싱, 부재 시 [BranchSpec(id="trunk", ...)] 1개)
- scaffold/agents/planner.md + .claude/agents/planner.md 에 "병렬화 가능성 판단 절차" 섹션 추가
  (독립성 3 기준, Parallel Task Graph YAML 형식)

## 단계 5: runner.py::run_agents_parallel
- src/forge/agents/runner.py 에 신규 함수:
  - run_agents_parallel(branch_specs, project_paths, config, agent_kind) -> list[RunResult]
  - asyncio.Semaphore로 max_parallel_branches 한도 강제
  - 각 ClaudeCliSession에 cwd=worktree, whisper_queue_path=branch별 큐 주입
- run_agent_sync는 변경 없이 그대로 (단일 분기 + finalizer가 사용)

## 단계 6: orchestrator 분기 선택 + evaluator.py 변경
- src/forge/orchestrator.py 의 sprint 루프(generator/evaluator 호출 지점) 다음 로직으로 감싼다:
  branches = parse_branches(sprint_contract_text)
  if len(branches) == 1: 기존 코드 그대로 (회귀 0)
  else: auto_commit_trunk_artifacts → create_branch_worktrees → run_agents_parallel("generator")
        → auto_commit_worktree 루프 → run_agents_parallel("evaluator") → status 분기 처리
- src/forge/agents/evaluator.py::run_evaluate 시그니처 변경:
  branch_id: str = "trunk" 인자 추가 (기본값으로 회귀 0)
  branch_id != "trunk" 시 paths.branch_paths(branch_id) 사용, prompt 절대 경로 주입
  is_pass, validate_qa_report 도 branch_id 인자 추가

## 산출물
- git branch feature/parallel-engine
- 단위 테스트: parse_branches (섹션 부재/단일/2-4 branch/잘못된 YAML)
- **회귀 테스트 1번 통과 (단일 분기 모드 byte-level 일치)**
- **병렬 골든 패스 2번 통과 (N=2 시나리오)**

## 금지
- 단계 7-9 영역 (finalizer.py, finalizer.md, FAIL UX 정정, whisper 라우팅) 손대지 마라

## 완료 보고
- PR 본문에 단위 + 회귀 + 골든 패스 통과 증거
```

### 9-5. 세션 C 프롬프트 (Finalizer + UX)

```
# 세션 C: THE FORGE Finalizer + 병렬 모드 UX 구현

## 컨텍스트
- 메인 plan: c:\1.Project\THE_FORGE\docs\parallel-branches-design.md (정독 필수)
- 너의 책임: 단계 7, 8, 9 (Finalizer 에이전트 + FAIL 격상 + Whisper/알림)
- base 브랜치: feature/parallel-foundation 완료 후 feature/parallel-finalizer 으로 분기
- 의존성: 세션 A의 worktree.py(auto_commit, merge_into_trunk, verify_finalizer_merge_scope), 세션 B의 run_agents_parallel

## 단계 7: Finalizer 에이전트 + 자동 위반 감지
- 신규 파일:
  - scaffold/agents/finalizer.md (배포 원본)
  - .claude/agents/finalizer.md (운영 카피)
    - frontmatter: tools: [Read, Edit, Bash] (Edit 허용, Write 차단)
    - 시스템 프롬프트 본문: 충돌 마커 범위 편집만 허용, qa-report read-only, decision-NNN.md 의무, 부분 머지 모드 지원
  - src/forge/agents/finalizer.py
    - run_finalize(config, paths, branches, worktrees, *, partial=False, notifier) -> FinalizeResult
    - FAIL 분기 사전 검사 → needs_escalation 반환
    - merge_into_trunk 호출 → 충돌 시 finalizer LLM 세션
    - 머지 commit 후 verify_finalizer_merge_scope 호출
    - 위반 시 git revert + 사용자 게이트

## 단계 8: FAIL 격상 + PASS 부분 머지
- src/forge/orchestrator.py 의 sprint 루프에 단계 8-2 흐름 구현:
  - branch별 consecutive_fails 추적
  - 임계점 도달 시 Planner 재호출 + 새 sprint-contract.md (plan-review 게이트 우회)
  - 부분 머지 흐름: PASS 분기만 finalizer가 머지(partial=True), FAIL worktree 보존
- _notify_fail_with_options 정정:
  - 일괄 통보 (1 sprint = 최대 1 알림)
  - escalation 시점에만 알림 (임계점 미만 자동 재시도는 알림 X)
  - 메시지에 분기별 점수 노출

## 단계 9: Whisper 라우팅 + 알림 prefix
- 라우팅 규칙 구현:
  - @branch-2 prefix → artifacts/branches/branch-2/whisper-queue.jsonl 로
  - 일반 메시지 → trunk whisper-queue.jsonl
  - @all → 모든 활성 분기 broadcast
- src/forge/notifier/base.py 또는 호출부에 prefix 태깅 (예: "[branch-1] generator 시작")
- Slack rate limit 보호: 0.5초 간격 토큰 버킷

## 산출물
- git branch feature/parallel-finalizer
- **회귀 테스트 1번 통과**
- **검증 시나리오 3, 4, 4-2, 4-3, 4.8 통과** (FAIL escalation, 머지 충돌 자체 해결, 의미적 충돌 abort, scope 위반 감지, PASS 부분 머지)

## 금지
- 세션 A 영역(config.py 변수, BranchState, worktree.py) 손대지 마라
- 세션 B 영역(contract.py, run_agents_parallel, evaluator.py branch_id) 손대지 마라
- 충돌 시 orchestrator.py를 동시에 편집해야 한다면 세션 B와 마지막에 통합 시점에 머지

## 완료 보고
- PR 본문에 단위 + 회귀 + 검증 시나리오 3, 4, 4-2, 4-3, 4.8 통과 증거
```

### 9-6. 오케스트레이터(나) 통합 체크리스트

| 단계 | 무엇 | 통과 기준 |
|---|---|---|
| 1 | 세션 A 산출물 검토 | 회귀 테스트 1번 통과 + 단위 테스트 통과 |
| 2 | 세션 A를 feature/parallel-branches 에 머지 | 충돌 0건 |
| 3 | 세션 B, C 동시 시작 (이미 A 위에서 분기) | 진행 모니터링 |
| 4 | 세션 B 산출물 검토 | 회귀 1번 + 골든 2번 통과 |
| 5 | 세션 C 산출물 검토 | 회귀 1번 + 검증 3, 4, 4-2, 4-3, 4.8 통과 |
| 6 | 세션 B와 C를 feature/parallel-branches 에 머지 | orchestrator.py 머지 충돌 가능성 ↑ → 사용자가 결정 |
| 7 | 통합 후 전체 검증 시나리오 (1-8) 재실행 | 모두 통과 |
| 8 | docs/USER_GUIDE.md 신규 환경변수 문서화 | 사용자 검토 |
| 9 | sprint-1-done.md 형식의 통합 보고서 작성 | 사용자 사후 검토용 |

### 9-7. 멀티 세션 운영 시 주의 사항

- **plan 파일 위치**: `c:\1.Project\THE_FORGE\docs\parallel-branches-design.md` (3 세션 모두 동일 경로로 읽음)
- **세션 간 통신은 git만**: Slack/메모리 공유 없음. 각 세션이 자기 branch에 commit + push, 나는 fetch + merge로 통합
- **자기 영역 외 수정 금지**: 위 프롬프트의 "금지" 항목 위반 시 통합 단계에서 revert
- **세션 B와 C가 동시에 orchestrator.py를 건드릴 위험**: 단계 6은 세션 B 책임, 단계 8 흐름은 세션 C 책임 → 가능하면 함수 단위로 분리해서 충돌 회피. 충돌 시 사용자가 결정

---

## 마지막 한마디 요약

**"git worktree로 분기를 진짜 격리하고, finalizer는 git 명령만 다루는 좁은 에이전트로 두고, N=1 기본값에서는 모든 신규 코드가 0의 영향력을 갖도록 설계한다."**

핵심 약속:
- N=1 → 회귀 0건
- 라인 번호 의존 최소화 (심볼명 우선)
- self-rationalization 방어 4종 (프롬프트 범위 제한 + decision-NNN.md 의무 + 자동 위반 감지 + 사용자 사후 검토)
- 충돌 마커 범위 편집 허용 (단순 충돌 자체 해결), 의미적 충돌만 사용자 게이트로 escalate
- git 명령은 `worktree.py` 1개 모듈에 집중 (forge의 git 정신 위배를 한 곳에 격리)
- auto-commit 영역 3분할: **사용자 코드는 손 안 댐 / 시스템 산출물 자동 커밋 / .worktrees 자동 커밋**
- artifacts 하이브리드 (c): SSoT는 git sync / 분기별 격리는 .gitignore + 절대 경로 주입
- PASS 분기 부분 머지 (escalation 예외): 합격한 작업 안 버림, FAIL만 재분할
- 모든 사용자 지적 사항 명세 채움 (라인 / git 머지 / auto-commit / trunk-side auto-commit / artifacts 경로 / PASS 분기 처리 / whisper 라우팅 / evaluator 경로 / FAIL UX / parse_branches 위치)
- **plan을 plan으로 구현**: 세션 A → 세션 B+C 동시 (메인 plan의 L 분할 패턴을 plan 구현 자체에 적용)
