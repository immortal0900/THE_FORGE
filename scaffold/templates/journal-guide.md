# Journal 작성 가이드

`forge journal`이 호출하는 `journal` 서브에이전트가 참고하는 양식·톤·링크 규칙 가이드.
에이전트 본체 지시는 `.claude/agents/journal.md`에 있다. 이 파일은 **작성 예시와 실전 팁**.

## 엔트리 예시 (짧은 스프린트)

```markdown
## 2026-04-17 — obsidian_sync — Sprint 1

### Errors & Root Causes

- **`forge init` 후 `forge run` 시 scaffold/ 디렉토리를 찾을 수 없다는 에러**
  - 원인: `pyproject.toml`의 hatch wheel 빌드 설정에 scaffold/ 가 포함돼 있지 않아 설치본에 빠졌다
  - 해결: [pyproject.toml force-include 추가](../pyproject.toml) + [_scaffold_dir() 후보 경로 확장](../src/forge/cli.py#L190)
  - 교훈: `uv tool install .` 대상에는 반드시 scaffold가 포함됐는지 `site-packages` 확인

- **`claude` 서브프로세스 호출 시 FileNotFoundError (Windows)**
  - 원인: npm 전역 설치는 `claude.cmd` 배치 래퍼인데 Python subprocess는 PATHEXT 자동 탐색을 안 한다
  - 해결: [shutil.which("claude")로 전체 경로 해석](../src/forge/agents/planner.py#L20)
  - 교훈: 크로스플랫폼 서브프로세스는 `shutil.which` 필수

### Decisions

- **Generator를 interactive → `claude -p` 모드로 전환** (근거: 자동 루프에서 사용자 `/exit` 대기가 병목)
  - 고려안: (A) interactive 유지 + 자동 exit 프롬프트, (B) stdin에 `/exit` 주입, (C) `-p` 모드
  - 선택: C — 기능 동일(서브에이전트 Task 호출 지원), 자동 종료 보장
  - 영향: [orchestrator.py:488](../src/forge/orchestrator.py#L488)

### Tips & Gotchas

- **`bypassPermissions` 없이는 `claude -p` 모드에서 Write/Bash가 조용히 거부**된다 — Telegram에 "생성됨" 알림은 오지만 실제 파일은 없음
- **`uv tool install . --force`는 재빌드 보장이 아니다** — 소스 변경 반영하려면 `uv cache clean` 병행

### Performance Notes

- 이번 스프린트 누적 10분 4초 / 입력 1.2M 토큰 — 정상 범위
```

## 안 좋은 엔트리 예시 (피해야 할 것)

```markdown
### Errors & Root Causes

- 토큰이 0으로 나옴        # ❌ 증상만 있고 근본 원인/해결 없음
  - 뭔가 이상함              # ❌ 정보 없음
  - src/cost_tracker.py 에서 # ❌ 링크 아님, 라인 번호 없음
```

## 톤

- 짧고 단정적. "우리가 발견했다" 대신 "발견됐다".
- 미래 재발 방지를 목표로 — 미래의 자신이 검색할 키워드를 한 줄 요약에 포함.
- 비즈니스 로직 세부 (예: "userId가 null일 때 A 필드 대신 B 필드 쓴다")는 **프로젝트 내 스펙/decisions**에 남기고, journal에는 **범용 재사용 가능한 지식**만.

## 중복/덮어쓰기

- 기존 `docs/journal.md` 읽고, 동일 날짜/범위 엔트리가 이미 있으면 **기존을 업데이트**.
- 완전히 새 기간이면 **최상단에 새 엔트리 추가**.
- 오래된 엔트리는 절대 삭제/수정하지 마라.

## 링크 체크리스트

- [ ] 모든 파일 참조가 `[label](path)` 형태인가
- [ ] 함수 참조가 `()` 포함해 함수임을 명시하는가 (예: `apply_changes()`)
- [ ] 라인 번호 `#L42`를 붙였으면 실제 그 라인에 해당 심볼이 있는가
- [ ] 상대 경로가 `docs/journal.md` 기준으로 올바른가 (`../src/...`, `../artifacts/...`)

## 금지

- 코드나 artifacts/* 수정
- 평문 파일 경로 (링크 없이)
- 검증 없는 추측 (`아마도`, `대략`) — 확신 없으면 `(추정)` 꼬리표
- 프로젝트 밖 사용자 시스템 관련 내용
