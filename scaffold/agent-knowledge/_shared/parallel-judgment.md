# 병렬/직렬 판단

**자동 default 없음**. 매 sprint 마다 P0 항목 보고 분할/직렬 스스로 판단. forge는 worktree+finalizer 인프라 제공하지만 "기본 분할" 아님 — 작은 sprint면 직렬이 옳다.

## 판단 측면 (각 sprint 마다 종합)

A. **물리적 영역 분리도** — P0들의 파일·디렉토리·함수 영역 겹침 정도. 명확히 갈라지면 분할 유리. 같은 함수·인접 라인이면 머지 충돌 비용 큼 → 직렬.

B. **논리적 의존성** — P0 A가 P0 B의 산출물(반환값·타입) 직접 import 필요? 의존 있으면 같은 sprint 동시 불가능 (후속 P0를 다음 sprint로 미루거나 `depends_on` 명시, 이때 진짜 동시 아님). 의존 없으면 동시 가능.

C. **작업 규모와 P0 개수** — 매우 작은 프로젝트(파일 < 3개) / P0 1개 / 모든 P0가 한 함수 안이면 분할 무의미. worktree·generator·evaluator·finalizer 각 N배 오버헤드 > 직렬 시간.

D. **공유 인터페이스 사전 명시 가능성** — 분기들이 공유할 함수 시그니처·타입·스키마를 sprint-contract.md에 미리 박을 수 있나? 박을 수 있으면 분할 안전. 사전 명시 불가능/너무 많으면 분할 위험.

E. **finalizer 머지 비용 vs 분기 시간 절약** — A-D 종합 judgment call. 시간 절약 > 머지 비용이면 분할, 반대면 직렬.

## 결정 표기 (필수)

판단 결과를 **sprint-contract.md 본문에 한 문단 명시** (사용자가 capability card 받기 전 검토 가능하게):

- 분할: "이번 sprint는 분할로 결정. 이유: A(영역 명확), D(인터페이스 사전 박힘) 충족. 예상 시간 절약 > 머지 비용."
- 직렬: "이번 sprint는 직렬로 결정. 이유: 모든 P0가 stopwatch.py 한 파일의 인접 영역 (A 위반) + 작업 규모 작음 (C). 분할 오버헤드 > 직렬 시간."

## 분할 결정 시: Parallel Task Graph (YAML) 형식

sprint-contract.md 본문 어딘가에 추가:

```markdown
## Parallel Task Graph (YAML)

​```yaml
branches:
  - id: branch-1
    title: "인증 모듈"
    tasks: ["OAuth2 콜백 핸들러", "세션 토큰 저장"]
    depends_on: []
    files_owned: ["src/auth/*", "tests/auth/*"]
  - id: branch-2
    title: "데이터베이스 레이어"
    tasks: ["마이그레이션 스크립트", "ORM 모델 정의"]
    depends_on: []
    files_owned: ["src/db/*", "migrations/*"]
​```
```

규칙:
- `id`: 영문/숫자/밑줄/하이픈만. `trunk`는 예약어
- 분기 수: 2 <= N <= 4 (분할 의도일 때)
- 직렬 결정이면 섹션 자체 생략 → parse_branches가 단일 trunk로 폴백
- `files_owned`는 generator에 prompt 주입되어 "자기 영역 외 수정 금지" 근거
- `depends_on`: 같은 sprint 내 보통 빈 list. 명시하면 finalizer가 순서 존중 머지
