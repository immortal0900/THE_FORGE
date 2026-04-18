# THE FORGE — 사용자 가이드

> 처음 clone 받은 사람, 폴더만 복사받은 사람, 이미 구동 중인 프로젝트의 운영자 — 모두가 한 파일로 시작·실행·복구까지 끝낼 수 있도록 구성한 통합 가이드.
> 대상 버전: **v2.3.0** (pyproject.toml 기준). 코드 경로는 `c:/1.Project/THE_FORGE/` 기준.

---

## 0. 이 문서에 대해

### 0.1 이 문서가 다루는 것

| 섹션 | 내용 |
|---|---|
| 1 | 사전 요구사항 · 토큰 발급 절차 |
| 2 | **경로 A** — `git clone` 후 전역 설치 |
| 3 | **경로 B** — 폴더를 그대로 복사한 경우 |
| 4 | `forge setup` — 전역 설정 마법사 |
| 5 | `forge init` — 프로젝트 부트스트랩 |
| 6 | 설정 우선순위 · 환경 변수 전체 표 |
| 7 | `forge run` — 실행 진입 패턴 4가지 |
| 8 | 실행 중 사용자 개입 (Telegram/Slack 버튼·Slash Commands·Revise 모달·시그널·stdin) |
| 9 | QA 결과별 분기 |
| 10 | `artifacts/` 생성물 수명주기 |
| 11 | 관측 · 저널 (`forge status`, `forge journal`, Langfuse) |
| 12 | 보조 명령 (`eval`, `notify`, `update-*`, `version`) |
| 13 | 크래시 복구 시나리오 A / B / C |
| 14 | 트러블슈팅 FAQ |
| 15 | 개발자 메모 (테스트, 린트) |
| 부록 | 파일 지도 · 시그널 · CLI · 에러 매트릭스 |

### 0.2 표기 규약

- `forge run` — 셸에서 입력하는 명령.
- `artifacts/spec.md` — 파일 경로는 프로젝트 루트 기준.
- `FORGE_PROJECT_NAME` — 환경 변수는 전부 대문자 + 언더스코어.
- `Phase.GENERATING` — 코드 식별자 원문 유지.
- ⚠️ / ✅ / 🚨 — 주의, 성공, 에러 아이콘.

---

## 1. 사전 요구사항

### 1.1 필수

| 항목 | 최소 버전 | 확인 명령 |
|---|---|---|
| Python | **3.12 이상** | `python --version` 또는 `py -V` (Windows) |
| uv | 최신 | `uv --version` |
| Claude Code CLI | Max 플랜 구독 | `claude --version` |
| Git | 최신 | `git --version` |

- **uv 설치** — macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`. Windows PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
- **Claude Code CLI** — `claude.com/code`에서 설치. 로그인 후 `claude --version`이 동작해야 함.
- **Max 플랜** — THE FORGE는 `subprocess`로 공식 `claude` CLI를 호출하므로 Pro/Max 구독 쿼터로 동작한다. API 키가 아니라 CLI 로그인 세션이 기준이다.

### 1.2 선택

- **Node.js 18+** — Playwright E2E 자동 실행 시 필요. `pyproject.toml [tool.forge]`의 `playwright_enabled = true` 기본값. `playwright.config.*` 파일이 프로젝트에 있을 때만 실행된다.
- **Langfuse 계정** — LLM 호출 트레이싱을 원할 때. 키가 없으면 `SprintTracer`가 자동 **no-op**으로 동작하므로 미설치/미연결이 에러가 되지 않는다 (`src/forge/cost_tracker.py`).
- **Slack 워크스페이스** 또는 **Telegram 계정** — 원격 승인·알림 채널. 둘 중 하나만 선택.

### 1.3 토큰 발급 절차

#### Slack (권장, 전역 공유에 유리)

1. `api.slack.com/apps`에서 **From scratch**로 새 앱 생성.
2. **OAuth & Permissions → Scopes → Bot Token Scopes**: `chat:write`, `files:write`, `chat:write.customize` 추가.
3. **Socket Mode** 활성화 → **App-Level Tokens**에서 `connections:write` 권한으로 App Token 발급 (`xapp-...`).
4. 워크스페이스에 설치 → **Bot User OAuth Token** 복사 (`xoxb-...`).
5. 대상 채널에 앱 초대 → 채널 ID 복사 (`C01ABC...`, 채널 URL 마지막 세그먼트).

> 획득물: `xoxb-...` (Bot Token), `xapp-...` (App Token), `C01ABC...` (Channel ID). 이 3종을 4절 `forge setup`에서 입력한다.

#### Telegram (간단, 봇당 1 인스턴스 제약)

1. Telegram에서 `@BotFather` 대화 열기 → `/newbot` → 이름/사용자명 지정 → Bot Token 발급 (`123456:ABC-DEF...`).
2. 본인의 개인 채팅에서 봇에게 `/start` 한 번 전송.
3. 브라우저에서 `https://api.telegram.org/bot<TOKEN>/getUpdates` 열어 `"chat": {"id": ...}` 값 확인 → 이것이 `TELEGRAM_CHAT_ID`.

> 획득물: `FORGE_TELEGRAM_BOT_TOKEN`, `FORGE_TELEGRAM_CHAT_ID`. Telegram은 **봇당 동시 1 receiver**만 가능하므로 여러 프로젝트를 동시에 돌릴 때는 봇을 여러 개 만들거나 Slack을 쓰는 편이 낫다.

#### Langfuse (선택)

1. `cloud.langfuse.com` 가입 → 프로젝트 생성.
2. Settings → API Keys에서 `pk-lf-...` (Public), `sk-lf-...` (Secret) 발급.
3. 자체 호스팅이면 `FORGE_LANGFUSE_HOST`도 별도 지정 (기본: `https://cloud.langfuse.com`).

---

## 2. 설치 경로 A — `git clone` 후 전역 설치 (권장)

### 2.1 단계별 명령

```bash
# 1. 저장소 clone
git clone https://github.com/HWAIN/THE_FORGE.git
cd THE_FORGE

# 2. 의존성 설치 + 가상환경 동기화 (.venv 자동 생성)
uv sync

# 3. forge 명령을 전역 도구로 설치
uv tool install .
```

이후 아무 터미널에서나 `forge`를 바로 호출할 수 있다.

### 2.2 `forge` 명령이 PATH에 등록되는 원리

- `pyproject.toml`의 `[project.scripts]`에 `forge = "forge.cli:app"`이 선언되어 있다.
- `uv tool install .`은 hatchling 빌드 백엔드로 휠(wheel)을 만든 뒤, uv 전역 도구 저장소(`~/.local/share/uv/tools/the-forge/`)에 격리된 가상환경을 만들고 거기의 `bin/forge` (Windows: `Scripts/forge.exe`)를 `uv tool`의 bin 디렉토리(`~/.local/bin` 또는 `%USERPROFILE%\.local\bin`)에 링크한다.
- `uv tool install .`이 처음이면 다음과 같은 메시지가 나올 수 있다: `"~/.local/bin" is not on your PATH`. 이때 안내되는 export 라인을 셸 rc 파일(`.bashrc`, `.zshrc`, Windows는 환경 변수 UI)에 추가하고 새 터미널을 열어야 `forge`가 잡힌다.

### 2.3 설치 검증

```bash
forge version              # THE FORGE v2.3.0
forge --help               # 전체 명령 목록
which forge                # macOS/Linux — uv tool bin 경로
where forge                # Windows — 설치 경로
```

설치 직후 `forge --help`가 뜨면 성공. `command not found`면 **14.2**의 PATH 복구 절차로.

### 2.4 업그레이드 (원격 업데이트 반영)

```bash
cd THE_FORGE
git pull
uv tool install . --force   # 기존 전역 설치 덮어쓰기
```

- `scaffold/`가 업데이트되었으면 프로젝트 쪽도 반영해야 한다 → 해당 프로젝트 디렉토리에서 `forge update-templates`, `forge update-agents` 실행 (기존 파일은 `artifacts/.backup/`에 백업).
- `uv tool install . --reinstall`도 동일 효과.

### 2.4.1 `forge-deploy` — 원-커맨드 재배포 (alias)

`forge-deploy` 한 번으로 `src/` `__pycache__` 정리 + `uv tool install --force --reinstall` 수행. 코드 수정을 전역 `forge.exe`에 반영할 때 사용. 등록 위치: Git Bash는 `~/.bashrc`의 alias, cmd/PowerShell은 `%USERPROFILE%\.local\bin\forge-deploy.bat`.

### 2.5 제거

```bash
uv tool uninstall the-forge
```

- 이 명령은 CLI만 제거한다. `~/.forge/config.env`, `~/.forge/registry.json`은 그대로 남는다.
- 완전 삭제: `rm -rf ~/.forge` (macOS/Linux) 또는 `Remove-Item -Recurse $env:USERPROFILE\.forge` (Windows PowerShell).

---

## 3. 설치 경로 B — 폴더를 그대로 복사했을 때

외장 SSD·USB·사내 공유로 받거나 다른 머신에서 ZIP으로 풀어놓은 경우. `.git`이 누락될 수 있고, `.venv/`는 절대경로가 박혀 있어 그대로 쓸 수 없다.

### 3.1 폴더 복사 시 "빠지는 것"

| 빠지는 것 | 증상 | 복구 |
|---|---|---|
| PATH 등록 | `forge` 명령이 어디에서도 안 잡힘 | 3.2 또는 3.3 선택 |
| `.venv/` 재사용 | Python 경로 불일치로 실행 실패 | `uv sync`로 재생성 |
| `.git/` (경우에 따라) | `git pull` 업데이트 불가 | clone으로 다시 받거나 git init 후 remote 연결 |
| `scaffold/` 탐색 | 설치본과 경로가 다름 | **3.4** 참조, 이 프로젝트에선 문제 없음 |

### 3.2 선택지 1 — 전역 설치 없이 로컬에서 `uv run`으로 쓰기 (개발자용)

```bash
cd /path/to/복사된/THE_FORGE

# 가상환경 + 의존성 재생성 (기존 .venv는 삭제 또는 무시)
uv sync

# forge 명령을 uv가 만든 .venv의 bin으로 실행
uv run forge --help
uv run forge version
uv run forge setup
uv run forge init --root /path/to/my-project
uv run forge run "첫 요청" --root /path/to/my-project
```

- 장점: 소스 수정 즉시 반영, 격리됨, 전역 오염 없음.
- 단점: 항상 `uv run` 접두어 필요. 프로젝트 작업 디렉토리에서 쓰려면 `cd`가 불편 → `--root`로 대상 프로젝트 지정.

### 3.3 선택지 2 — 복사한 폴더를 전역 도구로 승격

```bash
cd /path/to/복사된/THE_FORGE
uv sync
uv tool install .
forge version
```

- 경로 A와 동일하게 어디서나 `forge`가 잡힌다.
- `git pull`이 안 되는 경우, 원본 머신에서 최신을 받아 다시 복사하고 `uv tool install . --force`로 갱신해야 한다.

### 3.4 `scaffold/` 위치 감지 원리

`src/forge/cli.py`의 `_scaffold_dir()`이 다음 순서로 `scaffold/CLAUDE.md`를 찾는다:

1. `<설치위치>/forge/scaffold/` — `uv tool install`로 설치된 패키지의 force-include 대상. `pyproject.toml`의 `[tool.hatch.build.targets.wheel.force-include]`에 의해 휠 내부로 복사됨.
2. `<소스루트>/src/forge/../../scaffold/` = `<소스루트>/scaffold/` — `uv run`으로 실행할 때의 개발 모드 경로.
3. `<현재디렉토리>/scaffold/` — 마지막 폴백.

결과: **경로 A · 경로 B 어느 쪽이든** 이 프로젝트는 `scaffold/`를 올바르게 찾아낸다. 만약 `scaffold/ 디렉토리를 찾을 수 없습니다` 에러가 나면 14.8 참조.

### 3.5 Windows에서 복사 시 주의

- `.venv/`는 폴더 복사로 이식 불가 → `uv sync`로 재생성.
- 한글 콘솔(cp949)에서 유니코드 출력이 깨질 수 있지만 `src/forge/cli.py:20-25`의 `stream.reconfigure(encoding="utf-8")`가 자동 처리하므로 거의 문제 없음.
- stdin 감지는 `msvcrt.kbhit` 분기(`src/forge/orchestrator.py:30-48`)가 Windows를 자동 인식한다.

### 3.6 두 경로 비교표

| 항목 | 경로 A (clone + `uv tool install .`) | 경로 B ① (`uv run`) | 경로 B ② (복사본을 tool install) |
|---|---|---|---|
| `forge` 명령 | 전역 PATH | 프로젝트 내부만 (`uv run forge`) | 전역 PATH |
| 소스 편집 반영 | 재설치 필요 (`install . --force`) | 즉시 반영 | 재설치 필요 |
| 업데이트 | `git pull && uv tool install . --force` | `git pull` + `uv sync` | 원본 복사 + `install . --force` |
| 격리성 | uv tool 전용 가상환경 | 프로젝트 `.venv` | uv tool 전용 가상환경 |
| 여러 버전 공존 | 곤란 (tool은 하나만) | 가능 (폴더별 .venv) | 곤란 |

권장: **일반 사용자 → 경로 A**, **코드 기여자 → 경로 B ①**.

---

## 4. 최초 1회 전역 설정 — `forge setup`

### 4.1 무엇을 하는가

```bash
forge setup
```

대화형 마법사가 실행되어 `~/.forge/config.env`를 생성/갱신한다 (`src/forge/setup_wizard.py`). 이후 **모든 프로젝트**의 `ForgeConfig`가 이 파일을 자동으로 읽는다. 즉 토큰은 한 번만 입력하면 된다.

기존 값이 있으면 테이블로 표시되고, 빈 엔터를 치면 값이 유지된다. 새 값을 입력하면 덮어쓴다.

### 4.2 질문 순서와 저장 키

| 순서 | 라벨 | 저장 키 | 필수? | 기본값 |
|---|---|---|---|---|
| 1 | Notifier 백엔드 | `FORGE_NOTIFIER_BACKEND` | 예 | `slack` |
| 2 | Slack Bot Token | `FORGE_SLACK_BOT_TOKEN` | 백엔드가 slack이면 | — |
| 3 | Slack App-Level Token | `FORGE_SLACK_APP_TOKEN` | 백엔드가 slack이면 | — |
| 4 | Slack Channel ID | `FORGE_SLACK_CHANNEL` | 백엔드가 slack이면 | — |
| 5 | Langfuse Public Key | `FORGE_LANGFUSE_PUBLIC_KEY` | 아니오 | — |
| 6 | Langfuse Secret Key | `FORGE_LANGFUSE_SECRET_KEY` | 아니오 | — |
| 7 | Langfuse Host | `FORGE_LANGFUSE_HOST` | 아니오 | `https://cloud.langfuse.com` |

Telegram 토큰은 마법사 항목이 아니다. **프로젝트별로 다르게 쓰는 경우가 많기 때문에 프로젝트의 `.env`에 넣는 것이 표준**이다.

### 4.3 재입력 / 초기화

```bash
forge setup           # 기존 값 유지하며 일부만 갱신
forge setup --reset   # 기존 값 전부 무시하고 처음부터 다시
```

`--reset`은 파일을 덮어쓰므로, 백업이 필요하면 먼저 복사해두자.

### 4.4 생성 파일 권한

- 마법사는 `os.chmod(path, 0o600)`을 시도한다 (POSIX만). Windows는 OS 레벨 파일 권한이 다르므로 효과 없지만 에러가 나지 않는다.
- 내용에 토큰이 담기므로 **이 파일은 절대 Git에 커밋하지 말 것**. 기본 위치가 `~/.forge/`이므로 프로젝트 외부라 일반적으로 커밋될 일은 없다.

### 4.5 생성 결과 예시

```env
# ~/.forge/config.env
# THE FORGE 전역 설정 — forge setup으로 생성/갱신

FORGE_NOTIFIER_BACKEND="slack"
FORGE_SLACK_BOT_TOKEN="xoxb-..."
FORGE_SLACK_APP_TOKEN="xapp-..."
FORGE_SLACK_CHANNEL="C01ABC..."
FORGE_LANGFUSE_PUBLIC_KEY="pk-lf-..."
FORGE_LANGFUSE_SECRET_KEY="sk-lf-..."
FORGE_LANGFUSE_HOST="https://cloud.langfuse.com"
```

---

## 5. 프로젝트 초기화 — `forge init`

### 5.1 실행 위치

**대상 프로젝트 디렉토리로 이동한 뒤** 실행한다. `--root` 옵션으로 다른 디렉토리를 지정해도 된다.

```bash
cd /path/to/my-project
forge init
# 또는
forge init --root /path/to/my-project
```

### 5.2 자동 프로젝트명 추론

`src/forge/autoinfer.py`의 `infer_project_name()`이 디렉토리명을 snake_case로 정규화한다.

| 디렉토리명 | → 프로젝트명 |
|---|---|
| `obsidian-sync` | `obsidian_sync` |
| `My Project` | `my_project` |
| `서버` (비영문) | `project` (안전 폴백) |

표시용 봇 이름은 `Forge-{PascalCase}` 형태로 파생된다 (예: `Forge-ObsidianSync`).

### 5.3 이름 중복 시 대화형 변경

`~/.forge/registry.json`에 `{name, path}`가 기록된다. 같은 이름이 다른 경로로 이미 등록되어 있으면 경고가 뜬다:

```
⚠️ 프로젝트명 'obsidian_sync'는 이미 /home/user/old-path에 등록돼 있습니다.
   현재 경로: /home/user/new-path
새 이름을 입력하세요 (엔터 시 'obsidian_sync_parent' 사용):
```

엔터만 누르면 `{원래이름}_{상위폴더이름}` 형태로 자동 변경된다.

### 5.4 생성·병합되는 파일 전체 목록

다음 파일들이 프로젝트에 생성된다 (`src/forge/cli.py` `_copy_scaffold`, `_merge_claude_settings`, `_ensure_env_and_pyproject`, `_ensure_gitignore`).

| 경로 | 출처 | 동작 |
|---|---|---|
| `CLAUDE.md` | `scaffold/CLAUDE.md` | 복사. 기존 파일은 `artifacts/.backup/`에 백업 (--force 시) |
| `.claude/agents/planner.md` | `scaffold/agents/planner.md` | 복사 |
| `.claude/agents/generator.md` | `scaffold/agents/generator.md` | 복사 |
| `.claude/agents/evaluator.md` | `scaffold/agents/evaluator.md` | 복사 |
| `.claude/agents/journal.md` | `scaffold/agents/journal.md` | 복사 |
| `.claude/settings.json` | `scaffold/settings.json` | **병합**. 기존 hooks는 유지, 중복 command는 건너뜀 |
| `.mcp.json` | `scaffold/.mcp.json` | 복사 (Playwright + Context7 MCP) |
| `templates/INDEX.md` 외 10종 | `scaffold/templates/*.md` | 복사 |
| `.env` | 신규 | `FORGE_PROJECT_NAME="..."` 한 줄만. 이미 있으면 건드리지 않음 (--force 시 `.env.bak`으로 백업) |
| `pyproject.toml` | 기존 또는 미존재 | `[tool.forge]` 섹션을 **없을 때만** 추가. pyproject 파일이 아예 없으면 생성하지 않음 |
| `.gitignore` | 기존 또는 신규 | 12개 항목을 미존재 시에만 append |
| `artifacts/` | 디렉토리 | 없으면 생성 |
| `artifacts/specs/` | 디렉토리 | 없으면 생성 |
| `artifacts/decisions/` | 디렉토리 | 없으면 생성 |
| `artifacts/.backup/` | 디렉토리 | `--force` 시 백업 대상 |
| `docs/` | 디렉토리 | `journal.md` 부모 디렉토리로 생성 |

### 5.5 `.gitignore` 자동 추가 항목

```gitignore
# forge runtime
.env
artifacts/spec.md
artifacts/plan-review.md
artifacts/sprint-contract.md
artifacts/progress-log.md
artifacts/qa-report.md
artifacts/harness-cost-log.txt
artifacts/.harness-checkpoint
artifacts/.backup/
artifacts/specs/
artifacts/decisions/
artifacts/.approval-signal
artifacts/.skip-signal
artifacts/.continue-signal
artifacts/.exit-signal
artifacts/.eval-signal
artifacts/.stop-signal
```

**주의**: `sprint-N-done.md`는 ignore 대상이 아니다. 완료된 스프린트 아카이브는 Git에 들어가도록 설계되어 있다.

### 5.6 `--force` 옵션

```bash
forge init --force
```

기존 `CLAUDE.md`, `.claude/settings.json`, `.env` 등을 `artifacts/.backup/`에 백업한 뒤 덮어쓴다. `templates/`와 `.claude/agents/`의 파일들은 `scaffold/`의 현재 버전으로 교체된다.

### 5.7 비-Python 프로젝트

`pyproject.toml`이 없으면 `_ensure_env_and_pyproject()`는 **pyproject를 새로 만들지 않는다**. 대신 Node.js·Rust·Go 같은 비-Python 프로젝트에서도 `.env`와 scaffold 파일들이 설치된다. 공유 설정은 `pyproject.toml [tool.forge]` 대신 `forge.toml` 또는 환경 변수로 넣어야 한다 (6.1 우선순위 참조).

---

## 6. 설정 우선순위 완전 이해

### 6.1 7단 우선순위

값이 해석되는 순서(**위가 우선**, 먼저 나오는 비어있지 않은 값이 최종값):

1. **프로세스 환경 변수** — `FORGE_*`로 export된 값.
2. **프로젝트 `.env`** — 대상 프로젝트 루트의 `.env`.
3. **전역 `~/.forge/config.env`** — `forge setup`으로 저장된 파일.
4. **`forge.toml [forge]`** — 프로젝트 루트의 `forge.toml` (선택).
5. **`pyproject.toml [tool.forge]`** — 파이썬 프로젝트용 공유 설정.
6. **자동 추론** — `infer_project_name()` 등.
7. **Pydantic 필드 기본값** — `src/forge/config.py`의 `ForgeConfig`.

> 구현 세부: pydantic-settings의 `env_file=(global, project)` 튜플 순서에서 **뒤쪽이 우선**이므로 프로젝트 `.env`가 전역을 덮어쓴다 (`src/forge/config.py:24`).

### 6.2 어디에 값을 두어야 하는가

| 성격 | 권장 위치 | 예시 |
|---|---|---|
| 전역 공유 토큰 (변하지 않음) | `~/.forge/config.env` | `FORGE_SLACK_BOT_TOKEN`, `FORGE_LANGFUSE_*` |
| 프로젝트별 이름·봇 얼굴 | 프로젝트 `.env` | `FORGE_PROJECT_NAME`, `FORGE_BOT_DISPLAY_NAME`, `FORGE_BOT_EMOJI` |
| 프로젝트별 Telegram 봇 | 프로젝트 `.env` | `FORGE_TELEGRAM_BOT_TOKEN`, `FORGE_TELEGRAM_CHAT_ID` |
| 협업자가 공유할 타임아웃/턴수 | `pyproject.toml [tool.forge]` | `max_sprint_minutes`, `generator_max_turns` 등 |
| CI/일시 오버라이드 | 셸 환경 변수 | `FORGE_NOTIFIER_BACKEND=telegram forge run ...` |

### 6.3 모든 `FORGE_*` 환경 변수 전체표

출처: `src/forge/config.py:21-70` — `ForgeConfig` 모든 필드.

| 환경 변수 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `FORGE_PROJECT_NAME` | str | `""` → 디렉토리명 추론 | 식별자. snake_case. |
| `FORGE_BOT_DISPLAY_NAME` | str | `""` → `Forge-{PascalCase}` | Slack 메시지의 username. |
| `FORGE_BOT_EMOJI` | str | `:hammer_and_wrench:` | Slack 봇 아이콘. |
| `FORGE_NOTIFIER_BACKEND` | str | `telegram` | `telegram` \| `slack`. |
| `FORGE_TELEGRAM_BOT_TOKEN` | str | `""` | Bot 토큰. |
| `FORGE_TELEGRAM_CHAT_ID` | str | `""` | 대상 chat ID. |
| `FORGE_SLACK_BOT_TOKEN` | str | `""` | `xoxb-...`. |
| `FORGE_SLACK_APP_TOKEN` | str | `""` | `xapp-...`. |
| `FORGE_SLACK_CHANNEL` | str | `""` | 채널 ID `C01ABC...`. |
| `FORGE_LANGFUSE_PUBLIC_KEY` | str | `""` | 비어있으면 추적 no-op. |
| `FORGE_LANGFUSE_SECRET_KEY` | str | `""` | 동상. |
| `FORGE_LANGFUSE_HOST` | str | `https://cloud.langfuse.com` | 자체 호스팅 시 변경. |
| `FORGE_MAX_SPRINT_MINUTES` | int | `180` | 스프린트 시간 예산. |
| `FORGE_MAX_GENERATOR_MINUTES` | int | `120` | Generator subprocess 타임아웃. |
| `FORGE_PLANNER_MAX_TURNS` | int | `15` | Planner generate 턴 제한. |
| `FORGE_PLANNER_REVIEW_MAX_TURNS` | int | `10` | Planner review 턴 제한. |
| `FORGE_CONTRACT_MAX_TURNS` | int | `12` | Sprint Contract 생성 턴. |
| `FORGE_EVALUATOR_MAX_TURNS` | int | `20` | Evaluator QA 턴. |
| `FORGE_GENERATOR_MAX_TURNS` | int | `180` | Generator claude -p `--max-turns`. |
| `FORGE_JOURNAL_MAX_TURNS` | int | `80` | `forge journal` 에이전트 턴. |
| `FORGE_PLAYWRIGHT_ENABLED` | bool | `true` | Evaluator가 E2E 자동 실행할지. |
| `FORGE_PLAYWRIGHT_TIMEOUT_SECONDS` | int | `600` | `npx playwright test` 타임아웃. |
| `FORGE_MAX_TOTAL_MINUTES` | int | `1440` | 전체 누적 시간 상한 (24시간). |
| `FORGE_MAX_CONSECUTIVE_FAILS` | int | `3` | 연속 FAIL 허용 횟수. |
| `FORGE_MAX_TOTAL_SPRINTS` | int | `20` | 자동 루프 최대 스프린트. |
| `FORGE_APPROVAL_TIMEOUT_SECONDS` | int | `86400` | 승인 대기 타임아웃 (24시간). |

### 6.4 `pyproject.toml [tool.forge]` 예시

```toml
[tool.forge]
max_sprint_minutes = 180
max_generator_minutes = 120
planner_max_turns = 15
planner_review_max_turns = 10
contract_max_turns = 12
evaluator_max_turns = 20
generator_max_turns = 180
journal_max_turns = 120         # 오래 걸리는 저널 작업용
max_consecutive_fails = 3
max_total_sprints = 20
```

비어있는 문자열(`""`)은 파싱에서 무시된다 (`config.py:148`).

---

## 7. 실행 — `forge run`

### 7.1 진입 패턴 4가지

#### 패턴 A — 짧은 요청 (spec.md 없음)

```bash
forge run "LangGraph 기반 대화 에이전트 뼈대 만들어줘"
```

- `artifacts/spec.md`가 없으면 Planner가 요청 문자열을 기반으로 spec.md를 생성한다.

#### 패턴 B — 기획서 파일

```bash
forge run --plan ./my-plan.md
# 별칭
forge run -p ./my-plan.md
```

- `--plan FILE`로 지정한 마크다운 파일을 `artifacts/spec.md`로 복사한 뒤 Planner가 검토(run_review) 단계부터 시작한다.
- 이미 `artifacts/spec.md`가 있으면 덮어쓰지 않는다 (`orchestrator.py:366-371`).

#### 패턴 C — 체크포인트 자동 복구

```bash
forge run
```

- 인자 없이 실행하면 `artifacts/.harness-checkpoint`의 Phase를 읽어 이어서 진행한다.
- 체크포인트가 없으면 spec.md가 있어야 한다 (없으면 `spec.md가 없고 요청도 없습니다` 에러로 exit code 2).

#### 패턴 D — 특정 Phase부터 강제 시작

```bash
forge run --from contract
forge run --from generating
forge run --from evaluating
forge run --from planning
```

- `--from` 값을 Phase IntEnum의 `X-1` 값으로 체크포인트를 강제 재설정한다 (`orchestrator.py:376-379`).
- 허용값: `planning` \| `contract` \| `generating` \| `evaluating`. 대소문자 무관.

#### 루트 지정

```bash
forge run "요청" --root /path/to/other-project
forge run "요청" -r /path/to/other-project
```

### 7.2 5-Phase 사이클 개요

`Phase` IntEnum (`src/forge/checkpoint.py:13-23`): `NONE(0)` → `PLANNING(1)` → `PLANNING_DONE(2)` → `CONTRACT(3)` → `CONTRACT_DONE(4)` → `GENERATING(5)` → `GENERATING_DONE(6)` → `EVALUATING(7)` → `EVALUATING_DONE(8)`.

| Phase | 에이전트 | 호출 형태 | 생성물 |
|---|---|---|---|
| PLANNING | Planner | `claude -p --agent planner` (비대화형) | `spec.md`, `specs/*.md`, `plan-review.md` |
| CONTRACT | Planner | `claude -p --agent planner` | `sprint-contract.md` (sprint별 덮어씀) |
| GENERATING | Generator | `claude -p --agent generator --max-turns N --permission-mode bypassPermissions` | `progress-log.md`, `decisions/*.md`, 실제 소스 커밋 |
| EVALUATING | Evaluator | `claude -p --agent evaluator` (+ 선택적 Playwright) | `qa-report.md` |
| 판정 | — | Python 로직 | PASS → `sprint-N-done.md` 아카이브 / FAIL → 체크포인트 `CONTRACT_DONE`으로 리셋 |

### 7.3 v2.3 자동 스프린트 루프

**기본 동작 (옵션 없음)**: PASS + `has_next_sprint: true` (sprint-contract.md 프론트매터)이면 `/resume` 대기 후 자동으로 다음 스프린트를 시작. FAIL이면 `/resume` / `/eval` / `/stop` 선택.

```bash
forge run "처음 요청"                   # has_next_sprint가 false가 될 때까지 자동 진행
forge run --single-sprint "처음 요청"   # 1 스프린트만 돌고 종료 (v2.2 호환)
forge run --max-sprints 3 "처음 요청"   # 최대 3개만
```

### 7.4 안전장치 3종

다음 조건 중 하나라도 만족하면 자동 중단 (`orchestrator.py:454-467`):

| 조건 | 환경 변수 | 기본값 | 동작 |
|---|---|---|---|
| 누적 스프린트 수 ≥ | `FORGE_MAX_TOTAL_SPRINTS` 또는 `--max-sprints` | 20 | `auto_stop` 알림 후 종료 |
| 연속 FAIL ≥ | `FORGE_MAX_CONSECUTIVE_FAILS` | 3 | `auto_stop` 알림 + qa-report 첨부 |
| 누적 시간 > (분) | `FORGE_MAX_TOTAL_MINUTES` | 1440 (24h) | `budget_exceeded` 알림 + cost-log 첨부 |

이 중단은 체크포인트를 유지한 채 나가므로, 조건을 수정 후 `forge run`을 다시 호출하면 이어진다.

### 7.5 첫 스프린트 승인 게이트

- **PLANNING 완료 시**: Planner가 생성한 `plan-review.md` 상태에 따라 버튼이 다르다 (`orchestrator.py:420-432`):
  - 상태 `READY` → 버튼 `[/resume] [/exit]`.
  - 상태 `NEEDS_REVISION` → 버튼 `[/skip] [/resume] [/exit]`. `/skip`을 받아야 강제 진행, `/resume`만 누르면 중단된다 (`orchestrator.py:439-440`).
- **Sprint 1의 CONTRACT 완료 시**: `[/resume] [/exit]` 대기.
- **Sprint 2+ 의 CONTRACT**: 자동 진행 (승인 없음). 첫 승인만으로 전체 프로젝트에 대한 위임이 이루어진다.

### 7.6 종료 코드

`forge run`의 exit code:

| 코드 | 의미 |
|---|---|
| `0` | 정상 종료 (프로젝트 완료 / `/stop` / `/exit` / `--single-sprint` PASS) |
| `1` | `--single-sprint` 모드에서 FAIL |
| `2` | spec.md 없고 요청도 없음 |
| `3` | `claude: command not found` |
| `4` | `qa-report.md` 검증 실패 |

---

## 8. 실행 중 사용자 개입 방법

### 8.1 승인 게이트 위치

오케스트레이터가 멈춰 사용자 입력을 기다리는 시점:

1. **PLANNING 완료 후** — plan-review 검토.
2. **Sprint 1 CONTRACT 완료 후** — 첫 스프린트 범위 승인.
3. **PASS + has_next_sprint=true** — 다음 스프린트 진행 여부.
4. **FAIL** — 재시도·재평가·중단 선택.

이 외의 Phase 전이는 모두 자동이다.

### 8.2 Telegram/Slack 공통 명령어

출처: `src/forge/notifier/telegram/receiver.py:76-95`, `src/forge/notifier/slack/adapter.py:60-75`.

| 명령 | 한글 별칭 | 생성되는 시그널 | 효과 |
|---|---|---|---|
| `/resume` | `/계속`, `/진행`, `/approve` | `.approval-signal` | 승인 통과 / FAIL 후 Generator 재진입 |
| `/skip` | `/스킵`, `/무시` | `.skip-signal` (+ `.approval-signal`) | plan-review `NEEDS_REVISION` 강제 진행 |
| `/continue` | — | `.continue-signal` | 예약 (현재 미사용) |
| `/exit` | `/종료` | `.exit-signal` | PLANNING 단계 중단 |
| `/eval` | `/재평가` | `.eval-signal` | FAIL 후 Evaluator만 재실행 |
| `/stop` | `/중단` | `.stop-signal` | 자동 스프린트 루프 중단 |
| `/revise` | `/수정` | `.revise-signal` | **Slack 전용**: modal로 수정 지시 입력 → Planner Mode D 재실행 |
| `/status` | `/상태` | — | 현재 Phase/Sprint/누적시간 회신 |
| `/help` | `/도움` | — | 명령어 도움말 회신 |

Slack에서는 알림 메시지에 버튼이 붙으므로 타이핑 없이 클릭으로도 가능하다. 8.2.2의 `/revise` 버튼은 클릭 → 모달 입력 → 제출 순서.

### 8.2.1 Slack Slash Commands

Slack App → Features → Slash Commands에 등록. Request URL은 비워둠 (Socket Mode).

| 명령 | 인자 | 동작 |
|---|---|---|
| `/forge-status` | 없음 또는 `[project_name]` | 실행 중인 forge 프로세스의 상태 조회 (인자 없으면 전부, 있으면 일치하는 것만) |

### 8.2.2 `/revise` 버튼 (Slack 전용)

Planner 알림 메시지의 `[✏️ revise]` 클릭 → 입력 모달 → 수정 지시 제출 → Planner가 **Mode D**로 재실행되어 `spec.md`를 수정. 만족할 때까지 반복 가능.

### 8.3 시그널 파일 직접 생성 (네트워크 불가·비상시)

봇이 응답하지 않거나 네트워크가 막혔을 때:

```bash
# 승인
touch artifacts/.approval-signal
echo "resume" > artifacts/.approval-signal

# 재평가
echo "eval" > artifacts/.eval-signal

# 중단
echo "stop" > artifacts/.stop-signal

# 즉시 종료
echo "exit" > artifacts/.exit-signal
```

오케스트레이터는 2초 간격으로 시그널 파일을 폴링한다 (`orchestrator.py:60-76`). 파일은 감지 후 자동 삭제된다.

### 8.4 stdin 직접 입력

`forge run`을 실행한 터미널에 직접 엔터를 치면 `resume`으로 해석된다 (`orchestrator.py:74-75, 101-102`).

- Windows: `msvcrt.kbhit()`로 감지 — 아무 키 + Enter.
- macOS/Linux: `select.select([sys.stdin], ...)`로 감지 — Enter만.

이 방법은 Telegram/Slack 대신 CLI만으로 운용할 때 유용하다.

### 8.5 파일 첨부 업로드 (Telegram)

Telegram에서 파일을 보내며 caption을 `artifacts/<경로>` 형태로 적으면 해당 경로에 저장된다 (`receiver.py:97-132`):

```
(파일 첨부)
caption: artifacts/spec.md
```

- 기존 파일은 `artifacts/.backup/{원파일명}.bak`으로 이동.
- traversal 방어: `artifacts/` 밖으로 벗어나는 상대경로는 거부.
- 성공 시 `✅ artifacts/spec.md 저장 완료` 회신.

수정한 기획서를 모바일에서 덮어쓰고 `/resume`으로 다음 단계를 트리거할 수 있다.

### 8.6 Generator interactive 세션에서의 직접 개입

v2.3에서 Generator는 `claude -p` 비대화형 subprocess로 변경되었다. 실시간 개입은 다음 방식으로만 가능:

- **Ctrl+C** — subprocess가 즉시 종료되고 체크포인트가 `GENERATING`으로 남는다. `forge run`을 다시 돌리면 이어진다 (체크포인트 `should_run(GENERATING)` 조건).
- **타임아웃 대기** — `FORGE_MAX_GENERATOR_MINUTES` 초과 시 `TimeoutExpired` → `warning` 알림.
- **Generator 완료 후 수정** — 사용자가 `progress-log.md`/코드를 직접 고친 뒤 `/eval`로 Evaluator만 재검증.

---

## 9. QA 결과별 분기

### 9.1 PASS 분기

Evaluator가 `qa-report.md` 마지막 줄에 `PASS`를 기록하면 (`is_pass()` 체크):

- `artifacts/sprint-N-done.md`로 `qa-report.md` 복사 (아카이브).
- `sprint-contract.md`의 YAML frontmatter에서 `has_next_sprint` 값을 확인.

```yaml
---
sprint: 3
has_next_sprint: true
---
```

| 프론트매터 | 버튼 | 대기 |
|---|---|---|
| `has_next_sprint: true` | `[/resume] [/stop]` | 다음 스프린트 진행 승인 |
| `has_next_sprint: false` 또는 필드 없음 | 프로젝트 완료 알림 | 대기 없이 종료 |

`--single-sprint` 플래그가 있으면 PASS 즉시 종료.

### 9.2 FAIL 분기

- `consecutive_fails += 1`.
- 체크포인트를 `Phase.CONTRACT_DONE`으로 강제 리셋 (다음 `resume` 시 Generator가 다시 돌도록).
- 알림 버튼 `[/resume] [/eval] [/stop]`.

| 신호 | 동작 |
|---|---|
| `/resume` | Generator 재진입 (같은 sprint-contract 기준으로 다시 구현) |
| `/eval` | Evaluator만 재실행. 평가가 잘못된 경우. |
| `/stop` | 루프 중단. 체크포인트 유지. |
| 타임아웃 | `approval_timeout_seconds` 초과 시 타임아웃 처리. |

연속 FAIL이 `max_consecutive_fails`(기본 3) 이상이면 다음 반복 진입 직전에 자동 중단된다.

### 9.3 qa-report.md 검증 실패

파일 자체가 없거나 형식이 잘못된 경우 `validate_qa_report()`가 `ok=False`를 반환 → exit code 4로 종료. `forge eval`로 Evaluator를 재실행하거나 수동으로 파일을 수정 후 다시 진행할 수 있다.

---

## 10. `artifacts/` 생성물 수명주기

경로 정의: `src/forge/config.py:154-206` (`ProjectPaths`).

| 파일 | 생성자 | 수명 | Git |
|---|---|---|---|
| `artifacts/spec.md` | Planner (1회) | 프로젝트 수명 | .gitignore |
| `artifacts/specs/*.md` | Planner | 프로젝트 수명 | .gitignore |
| `artifacts/plan-review.md` | Planner | spec.md가 갱신되면 자동 무효화 (`_invalidate_stale_review`) | .gitignore |
| `artifacts/sprint-contract.md` | Planner | 스프린트마다 덮어씀 | .gitignore |
| `artifacts/progress-log.md` | Generator | 누적 (최상단에 추가) | .gitignore |
| `artifacts/qa-report.md` | Evaluator | 스프린트마다 덮어씀 | .gitignore |
| `artifacts/sprint-N-done.md` | 오케스트레이터 (PASS 시) | 영구 아카이브 | **추적됨** |
| `artifacts/harness-cost-log.txt` | SprintTracer | 누적 append | .gitignore |
| `artifacts/.harness-checkpoint` | 오케스트레이터 | 매 Phase save | .gitignore |
| `artifacts/decisions/*.md` | Generator | 영구 | .gitignore (기본) |
| `artifacts/.backup/` | init/update | 수동 삭제 전까지 유지 | .gitignore |
| `artifacts/.*-signal` | receiver / 사용자 | 오케스트레이터가 감지 후 삭제 | .gitignore |
| `docs/journal.md` | `forge journal` | 누적 (최상단에 추가) | **추적 권장** |

---

## 11. 관측 · 저널

### 11.1 `forge status`

```bash
forge status
forge status --root /path/to/other-project
```

출력 예 (`src/forge/cli.py:244-271`):

```
                    THE FORGE status — my_project                  
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Key               ┃ Value                                     ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ project_root      │ /home/user/my-project                     │
│ phase             │ GENERATING_DONE                           │
│ detail            │ generator finished                        │
│ timestamp         │ 2026-04-18T22:37:45                       │
│ sprint (next)     │ 3                                         │
│ 누적 시간         │ 142분                                     │
│ notifier_backend  │ slack                                     │
│ telegram_enabled  │ False                                     │
│ slack_enabled     │ True                                      │
│ langfuse_enabled  │ True                                      │
│ spec.md           │ OK                                        │
│ plan-review.md    │ OK                                        │
│ sprint-contract.md│ OK                                        │
│ qa-report.md      │ -                                         │
│ Sprint 1          │ ✅ PASS (archived)                        │
│ Sprint 2          │ ✅ PASS (archived)                        │
└───────────────────┴───────────────────────────────────────────┘
```

### 11.2 `forge journal`

엔지니어링 저널(`docs/journal.md`)을 누적 생성한다.

```bash
forge journal                          # 마지막 엔트리 이후 변경사항만
forge journal --sprint 3               # 특정 스프린트
forge journal -s 3                     # 별칭
forge journal --sprints 1-4            # 범위
forge journal --sprints 1,3,5          # 목록
forge journal --sprints 1-3,5          # 혼합
forge journal --since 2026-04-01       # 날짜 이후 변경사항
forge journal --root /other/project
```

- 세 옵션(`--sprint`, `--sprints`, `--since`)은 **동시에 하나만** 허용 (`cli.py:126-128`).
- 저널 생성 후 활성 notifier 백엔드로 최신 엔트리 요약 + 파일 첨부가 자동 전송된다 (`cli.py:159-173`).
- 에이전트가 턴을 소진하고 끝나지 않으면 `FORGE_JOURNAL_MAX_TURNS`를 늘리거나 범위를 좁힐 것.

### 11.3 Langfuse 추적 내용

`SprintTracer` (`src/forge/cost_tracker.py`)가 활성일 때(`langfuse_enabled=True`):

- 각 Phase마다 **span** 생성 (`tracer.span("planner")`, `tracer.span("generator", mode="claude-p")` 등).
- `claude -p`의 stdout에서 `Tokens: input N / output M / cache K` 패턴을 정규식으로 파싱해 span 속성으로 부착.
- span 종료 시 토큰 수·소요 시간이 Langfuse dashboard에 전송됨.

키가 없으면 **조용히 no-op**으로 동작하므로 신경 쓰지 않아도 된다.

### 11.4 `harness-cost-log.txt` 직접 확인

```
[2026-04-18T10:30:45] sprint=1 phase=planner minutes=5.2 tokens_in=12340 tokens_out=4820
[2026-04-18T10:38:12] sprint=1 phase=generator minutes=27.8 tokens_in=89210 tokens_out=31450
```

누적 분 계산: `parse_cost_log()`가 파일을 읽어 `minutes=` 값을 합산.

---

## 12. 보조 명령

### 12.1 `forge eval`

Evaluator만 수동으로 한 번 더 돌린다. QA가 잘못 판정했거나 코드를 손으로 수정한 뒤 재검증할 때.

```bash
forge eval
forge eval --root /other/project
```

- `qa-report.md`가 새로 쓰인다.
- `sprint-N-done.md`로 아카이브되지 않는다 (수동 실행은 루프 밖이므로). 아카이브를 원하면 그 이후 `forge run`으로 정상 루프에 복귀.

### 12.2 `forge notify`

Claude Code hooks 등 외부 스크립트에서 일회성 알림을 보낼 때.

```bash
forge notify session_stop "세션 종료" artifacts/progress-log.md
forge notify info "백업 완료"
```

- 첫 인자 `event_type` — 이벤트 키 (예: `session_stop`, `info`, `warning`).
- 둘째 인자 `message` — 본문.
- 셋째 선택 인자 `file_path` — 첨부 파일.
- `--root`로 대상 프로젝트 지정 가능.

`scaffold/settings.json`의 Claude Code hooks에 자동 등록되어 있지 않지만, 필요 시 `.claude/settings.json`의 `Stop` 훅에 `forge notify session_stop "세션 종료"`를 추가해 모바일 알림을 받을 수 있다.

### 12.3 `forge update-templates` / `forge update-agents`

THE FORGE 본체 업그레이드 후 프로젝트의 `templates/`, `.claude/agents/`를 최신 scaffold로 재동기화.

```bash
forge update-templates --dry-run    # 변경 대상만 출력
forge update-templates              # 실제 적용 (기존 파일은 artifacts/.backup/로 백업)
forge update-agents --dry-run
forge update-agents
```

- 내용이 동일한 파일은 건너뛴다.
- 강제로 기존 파일을 덮어쓴다 (`force=True`). 사용자가 프로젝트에서 수정한 커스텀 변경은 `.backup/`에서만 남고 메인은 원본으로 돌아간다. **직접 편집한 agents/templates가 있으면 먼저 diff로 확인할 것**.

### 12.4 `forge version`

```bash
forge version
# THE FORGE v2.3.0
```

---

## 13. 크래시 복구 시나리오

`Phase` IntEnum의 `should_run(target) = current_phase <= target` 단조성이 복구의 근간이다. 체크포인트는 각 Phase 시작 직전 + 종료 직후에 두 번 저장된다.

### 13.1 상황 A — Generator subprocess/터미널 크래시

**증상**: `claude -p --agent generator ...` 도중 터미널이 닫히거나 전원이 꺼짐.

**흐름**:
1. 오케스트레이터도 함께 종료되지만, 마지막 저장 체크포인트는 `Phase.GENERATING` (`orchestrator.py:496-497`).
2. `forge run` 재실행 → `Checkpoint.load()`가 GENERATING을 인식.
3. `should_run(GENERATING) = true` → Generator subprocess를 다시 호출.
4. Generator의 초기 프롬프트는 **qa-report.md가 있으면 FAIL 항목부터 수정, sprint-contract 체크박스 순서대로 진행, 기존 progress-log를 참조**하도록 지시되어 있어(`orchestrator.py:502-512`) 자연스럽게 이어진다.

**수동 개입 필요**: 보통 없음.

### 13.2 상황 B — 오케스트레이터 프로세스 자체 사망

**증상**: Python 예외 / OOM / `kill -9` / 전원 차단.

**흐름**:
1. `finally` 블록의 `notifier.stop()`은 못 타고 죽을 수 있지만 체크포인트는 마지막 `cp.save()` 시점까지 보존.
2. `forge run` 재실행 → `Checkpoint.load()` → 해당 Phase 진입.
3. 각 에이전트는 자기 artifact의 기존 상태를 읽고 이어쓰도록 규정됨 (CLAUDE.md).

**수동 개입 필요**: 없음. 단, 크래시가 반복되면 원인(메모리, 코드 버그)을 조사해야 한다.

### 13.3 상황 C — Planner/Evaluator subprocess 비-0 exit

**증상**: `claude -p` 호출이 네트워크/세션/턴소진으로 실패.

**흐름**:
1. `subprocess.run()`은 `check=True`가 아니라 반환값을 읽도록 되어 있어 즉시 예외가 아니다. `returncode`가 stderr과 함께 `report_subprocess()`로 기록된다.
2. Evaluator의 경우 `try/except`가 상위에서 `error` 이벤트 알림을 보낸다 (`orchestrator.py:550-551`).
3. 생성된 artifact(qa-report.md)가 없거나 무효일 수 있음 → `validate_qa_report()`가 걸러 exit code 4로 반환.
4. 사용자는 다음 중 하나를 선택:
   - `forge run`을 다시 호출 → 같은 Phase 재시도.
   - `forge eval`로 Evaluator만 재실행.
   - Telegram/Slack으로 `/eval` 버튼 클릭.

### 13.4 체크포인트 수동 초기화

```bash
# 전체 처음부터 다시 시작하고 싶을 때
rm artifacts/.harness-checkpoint           # macOS/Linux
del artifacts\.harness-checkpoint          # Windows cmd
Remove-Item artifacts/.harness-checkpoint  # PowerShell
```

파일이 없으면 `Checkpoint.load()`는 `Phase.NONE`을 반환.

### 13.5 Phase 강제 재설정

체크포인트를 통째로 지우지 않고 특정 Phase부터 이어가고 싶을 때:

```bash
forge run --from planning    # 다시 Planner 리뷰부터
forge run --from contract    # Sprint Contract부터
forge run --from generating  # Generator부터 (이미 만들어진 contract로)
forge run --from evaluating  # Evaluator만
```

`--from evaluating`은 `forge eval`과 거의 동등하지만 자동 루프 흐름 안에서 실행된다는 점이 다르다.

---

## 14. 트러블슈팅 FAQ

### 14.1 `claude: command not found`

- Claude Code CLI 미설치. `claude.com/code`에서 설치 후 `claude --version` 확인.
- Windows에서 설치했는데 `claude`가 안 잡힌다면 PATH 재부팅 필요 (새 터미널 / 로그인).
- `shutil.which("claude")`가 실패하면 오케스트레이터는 문자열 `"claude"`로 폴백 후 `FileNotFoundError`를 잡아 exit code 3으로 종료 (`orchestrator.py:501, 530-532`).

### 14.2 `forge: command not found`

- `uv tool install .`을 돌렸는데 PATH에 uv tool bin이 없을 때.
  - macOS/Linux: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc` (또는 `.bashrc`) → 새 터미널.
  - Windows: `%USERPROFILE%\.local\bin`을 PATH 환경 변수에 추가 후 재로그인.
  - `uv tool update-shell` 명령이 자동으로 넣어주기도 함.
- 일시적으로는 `uv run forge ...`로 우회 가능.

### 14.3 Telegram 403 Forbidden

- Bot Token 오류 / 사용자가 봇에게 `/start`를 보낸 적 없음 / `chat_id` 오류.
- 해결: 봇 대화에서 `/start` → `https://api.telegram.org/bot<TOKEN>/getUpdates`에서 `chat.id` 재확인.
- 프로젝트 `.env`에 `FORGE_TELEGRAM_BOT_TOKEN`, `FORGE_TELEGRAM_CHAT_ID`가 둘 다 비어있지 않은지 확인 (`config.py:73-74`의 `telegram_enabled` 조건).

### 14.4 Slack 인증 실패 / 메시지가 안 옴

- 3종 토큰(`FORGE_SLACK_BOT_TOKEN`, `FORGE_SLACK_APP_TOKEN`, `FORGE_SLACK_CHANNEL`)이 모두 채워져야 `slack_enabled`가 true (`config.py:77-78`).
- Socket Mode가 비활성이면 App Token으로 WebSocket 연결이 안 된다.
- Bot이 채널에 초대되어 있어야 `chat_postMessage`가 성공한다.
- `slack_sdk` 패키지가 설치되어 있는지 확인 (`pyproject.toml` 의존성). 누락 시 `TelegramNotifier`로 폴백하는 조건부 import가 있다 (`src/forge/notifier/slack/adapter.py:100`).

### 14.5 Langfuse 관련 실패

- `.env`/`~/.forge/config.env`에 public/secret key 누락 시 **조용히 no-op** (에러 아님).
- 네트워크 이슈 등으로 실제 전송이 실패하면 stderr에 `[forge] Langfuse ... failed: ...` 한 줄이 찍히지만 파이프라인은 계속 진행된다.

### 14.6 Windows 유니코드·stdin 이슈

- cp949 콘솔에서 이모지/한글 깨짐 → `cli.py:20-25`의 `sys.stdout.reconfigure(encoding="utf-8")` 자동 적용. 그래도 깨지면 **Windows Terminal** 또는 **VS Code 내장 터미널**을 사용할 것 (cmd.exe가 아닌).
- stdin 감지 안 됨 → 시그널 파일로 우회(`touch artifacts/.approval-signal`).

### 14.7 `scaffold/ 디렉토리를 찾을 수 없습니다`

- 경로 B로 폴더만 복사받고 `src/forge/` 또는 `scaffold/`가 누락된 경우. 전체 폴더(특히 `scaffold/`)가 복사되었는지 확인.
- 휠 빌드에서 `[tool.hatch.build.targets.wheel.force-include] "scaffold" = "forge/scaffold"` 설정이 누락됐는지 확인 (최신 `pyproject.toml`은 포함).

### 14.8 `pyproject.toml [tool.forge]` 섹션 중복

- `forge init`을 여러 번 돌려도 `"[tool.forge]" not in content`가 true일 때만 append (`cli.py:574`). 즉 이미 있으면 건드리지 않는다.
- 수동으로 두 개의 `[tool.forge]` 블록을 만들어 버린 경우 tomllib 파싱에서 에러가 날 수 있다. 하나만 남기고 나머지는 삭제.

### 14.9 프로젝트명 충돌

- `~/.forge/registry.json`에 같은 `name`이 다른 경로로 이미 있음.
- `forge init` 시 대화형으로 새 이름을 묻는다. 추천: 상위 폴더 이름을 접미로 붙이는 기본값(`{name}_{parent}`) 그대로 수락.
- 완전 초기화가 필요하면 해당 엔트리를 직접 편집하거나 `~/.forge/registry.json`을 삭제 (재사용 추적만 잃을 뿐 동작엔 무해).

### 14.10 Playwright 타임아웃

- `FORGE_PLAYWRIGHT_TIMEOUT_SECONDS` 기본 600초(10분). 테스트 수가 많으면 늘릴 것.
- 프로젝트에 `playwright.config.*`가 없으면 자동으로 E2E를 건너뛴다.
- 완전 비활성: `FORGE_PLAYWRIGHT_ENABLED=false` 또는 `pyproject.toml [tool.forge] playwright_enabled = false`.

### 14.11 `.env` 값이 적용되지 않는다

- 우선순위를 오해한 경우 (6.1 참조). 셸 환경 변수에 같은 키가 export 돼 있으면 그것이 우선한다.
- 확인: `env | grep FORGE_` (Unix) / `Get-ChildItem env:FORGE_*` (PowerShell).

### 14.12 Sprint 2+가 자동 시작되지 않는다

- `sprint-contract.md` YAML frontmatter에 `has_next_sprint: true`가 없을 때는 프로젝트 완료로 간주하고 종료한다. Planner가 마지막 스프린트라고 판단했다는 뜻.
- 이어서 스프린트를 더 돌리려면 사용자가 spec.md를 확장한 뒤 `forge run --from planning`으로 재기획.

### 14.13 `consecutive_fails`가 쌓여 멈춘다

- 3회 연속 FAIL 후 자동 중단 (`FORGE_MAX_CONSECUTIVE_FAILS`).
- 해결: `qa-report.md`를 읽고 근본 원인 파악 → 수동 수정 → `forge eval`로 재검증 → PASS 받고 `forge run`으로 루프 복귀.

---

## 15. 개발자 메모

### 15.1 테스트

```bash
uv run pytest                                 # 전체
uv run pytest tests/test_checkpoint.py -v     # 파일
uv run pytest -k "phase"                      # 키워드
```

`pyproject.toml`에서 `pythonpath = ["src"]`로 src layout이 지정되어 있다.

### 15.2 린트 · 포맷

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

`scaffold/settings.json`의 `PostToolUse` 훅이 프로젝트에 `pyproject.toml`이 있을 때 자동으로 `ruff check --fix --quiet`를 돌린다.

### 15.3 `.venv` 재생성

```bash
uv sync --reinstall
```

손상된 가상환경 초기화.

### 15.4 기여 시 역할 분담

- **`README.md`** — 프로젝트 소개·아키텍처·마케팅.
- **이 `docs/USER_GUIDE.md`** — 온보딩·실행·트러블슈팅 (사용자 관점).
- **`docs/핵심기술.md`** — 내부 설계 심화 (개발자 관점).

---

## 부록 A. 파일 · 디렉토리 전체 지도

```
<프로젝트 루트>/
├── .claude/
│   ├── settings.json        # Claude Code hooks, plugins
│   └── agents/
│       ├── planner.md
│       ├── generator.md
│       ├── evaluator.md
│       └── journal.md
├── .mcp.json                # Playwright + Context7 MCP 서버
├── .env                     # FORGE_PROJECT_NAME 등 프로젝트 고유값
├── CLAUDE.md                # 모든 에이전트 공통 규칙
├── pyproject.toml           # [tool.forge] 공유 설정 섹션
├── templates/               # Planner가 참조하는 도메인 스펙 템플릿
│   ├── INDEX.md
│   ├── sprint-contract-template.md
│   ├── generator-guide.md
│   ├── journal-guide.md
│   └── ...
└── artifacts/               # 하네스 런타임 결과물
    ├── spec.md
    ├── specs/*.md
    ├── plan-review.md
    ├── sprint-contract.md
    ├── progress-log.md
    ├── qa-report.md
    ├── sprint-1-done.md
    ├── sprint-2-done.md
    ├── harness-cost-log.txt
    ├── .harness-checkpoint
    ├── .backup/
    ├── decisions/*.md
    └── .*-signal

<홈>/
└── .forge/
    ├── config.env           # forge setup 결과 (전역 토큰)
    └── registry.json        # 프로젝트명·경로 매핑
```

## 부록 B. 시그널 파일 정리

| 파일 | 생성자 | 오케스트레이터 동작 |
|---|---|---|
| `artifacts/.approval-signal` | receiver / 사용자 touch | 승인 게이트 통과 |
| `artifacts/.skip-signal` | receiver / 사용자 | plan-review NEEDS_REVISION 강제 skip |
| `artifacts/.continue-signal` | receiver / 사용자 | 예약 (현재 미사용) |
| `artifacts/.exit-signal` | receiver / 사용자 | PLANNING 단계 중단 |
| `artifacts/.eval-signal` | receiver / 사용자 | FAIL 후 Evaluator만 재실행 |
| `artifacts/.stop-signal` | receiver / 사용자 | 자동 스프린트 루프 중단 |
| `artifacts/.revise-signal` | Slack view_submission | **내용**을 Planner Mode D 프롬프트로 전달 (spec.md 재수정) |

감지 주기: 2초 (`orchestrator.py:76, 103`). 감지 후 자동 삭제.

## 부록 C. CLI 명령 요약

```
forge run [REQUEST]  [--plan FILE] [--root PATH] [--from PHASE]
                     [--single-sprint] [--max-sprints N]
forge eval           [--root PATH]
forge journal        [--sprint N | --sprints RANGE | --since DATE]
                     [--root PATH]
forge status         [--root PATH]
forge setup          [--reset]
forge init           [--template X] [--force] [--root PATH]
forge notify         EVENT_TYPE MESSAGE [FILE] [--root PATH]
forge update-templates [--dry-run] [--root PATH]
forge update-agents    [--dry-run] [--root PATH]
forge version
```

**외부 명령** (CLI 아님 — alias/.bat 등록 필요, 2.4.1 참조)
- `forge-deploy` — `src/` 캐시 정리 후 전역 재설치

**Slack Slash Commands** (Slack App 등록 필요, 8.2.1 참조)
- `/forge-status [project_name]` — 실행 중 forge 프로세스 상태 조회

## 부록 D. 에러 메시지 ⇄ 원인 ⇄ 해결 매트릭스

| 메시지 (패턴) | 원인 | 해결 |
|---|---|---|
| `command not found: forge` | uv tool PATH 미등록 | 14.2 |
| `command not found: claude` | Claude Code CLI 미설치 | 14.1 |
| `spec.md가 없고 요청도 없습니다` | 빈 프로젝트에서 인자 없이 `forge run` | 요청 문자열 또는 `--plan` 제공 |
| `qa-report.md 검증 실패: ...` | Evaluator가 유효한 qa-report를 못 만듦 | `forge eval` 재실행 또는 수동 수정 |
| `scaffold/ 디렉토리를 찾을 수 없습니다` | 설치 방식 손상 | 14.7 |
| `⚠️ 프로젝트명 ...는 이미 등록돼 있습니다` | registry 충돌 | 14.9 |
| `Generator 시간 초과 (N분)` | subprocess timeout | `FORGE_MAX_GENERATOR_MINUTES` 증가 |
| `{backend} 크래시, /resume /skip /exit?` | 하위 subprocess 비-0 exit | 13.3 |
| Telegram `403 Forbidden` | Bot/Chat 설정 오류 | 14.3 |
| Slack `invalid_auth` / `not_authed` | 토큰 오류 | 14.4 |
| Slack `앱이 반응하지 않아 /forge-status ...` | forge 프로세스 미실행 (Socket Mode listener 없음) | `forge run`으로 프로세스 띄운 뒤 재시도. 정상 동작 |
| `[forge-deploy] FAILED - forge.exe may be running` | `forge.exe` 파일 락 | `taskkill /IM forge.exe /F` 후 재시도 |
| stderr `[forge] Langfuse ... failed` | Langfuse 전송 실패 | 14.5 (대부분 무시 가능) |

---

## 문서 끝

- 이 문서를 따라 `forge setup` → `forge init` → `forge run "첫 요청"` 세 명령까지 실패 없이 도달할 수 있어야 한다.
- 어느 한 절차라도 막힌다면 **해당 섹션의 파일:라인 번호**를 확인한 뒤, `src/forge/` 실제 코드를 열어 동작을 검증하는 것이 가장 빠른 해결책이다.
