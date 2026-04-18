# THE FORGE — 사용자 가이드

> 처음 써보는 사람, 외장 SSD로 폴더만 받은 사람, 이미 쓰고 있는데 뭔가 멈춘 사람 — 셋 다 이 한 파일로 해결할 수 있게 쓴 가이드입니다.
> 대상 버전: **v2.3.0**.

---

## ⚡ 5분 퀵스타트

이미 Claude Code CLI와 `uv`가 깔려 있고, Slack 봇 토큰 3종(또는 Telegram 봇 토큰)이 있다는 가정.

```bash
# 1. THE FORGE 설치 (한 번만)
git clone https://github.com/HWAIN/THE_FORGE.git && cd THE_FORGE
uv sync && uv tool install .

# 2. 전역 설정 (한 번만 — Slack/Telegram 토큰 입력)
forge setup

# 3. 내 프로젝트에서 초기화 (프로젝트마다 한 번)
cd /path/to/my-project
forge init

# 4. 실행
forge run "LangGraph 기반 대화 에이전트 뼈대 만들어줘"
```

이후 진행 중 Slack에 버튼이 뜨면 `/resume` 클릭(또는 터미널에서 Enter). 그게 전부입니다. 나머지 절은 "막혔을 때" 또는 "더 정교하게 쓰고 싶을 때" 펼쳐 보세요.

> 💰 **비용 감각**: THE FORGE는 Claude Code CLI를 서브프로세스로 호출합니다. 즉 **Claude Pro/Max 플랜의 쿼터**를 씁니다. API 토큰 과금이 아니라 구독 쿼터를 소모한다는 뜻. 한 스프린트는 보통 30분~2시간, 쿼터 기준으로는 "Generator가 제일 많이 먹는 한 덩어리"라고 생각하면 됩니다.

---

## 🧭 내 상황 찾기

| 지금 상황 | 여기로 |
|---|---|
| 처음 깔고 처음 돌린다 | [1절](#1-사전-요구사항--토큰-발급) → [2](#2-설치--두-가지-경로) → [3](#3-최초-1회-전역-설정--forge-setup) → [4](#4-프로젝트-부트스트랩--forge-init) → [6](#6-forge-run--실행의-모든-것) |
| 폴더만 외장 SSD로 받았다 | [2.2 경로 B](#22-경로-b--폴더만-복사해왔을-때) |
| 토큰을 아직 못 받았다 | [1.3 토큰 발급](#13-토큰-발급-절차) |
| 어제 돌리다 멈췄는데 오늘 이어가고 싶다 | [12.1 이어서 하기](#121-이어서-하기--어제-멈췄다면) |
| Slack에 이상한 메시지가 왔다 | [⚠️ 에러 빠른 찾기](#️-에러-빠른-찾기) |
| 결과가 이상해서 다시 평가만 돌리고 싶다 | [11.1 forge eval](#111-forge-eval) |
| THE FORGE 본체를 업데이트했다 | [2.4 업그레이드](#24-업그레이드) |
| Git에 뭘 커밋해야 할지 모르겠다 | [4.4 Git 관리 박스](#44--git에-뭘-커밋하고-뭘-무시하나) |
| 돈이 얼마나 드는지 궁금하다 | [10.3 비용 확인](#103-harness-cost-logtxt--비용토큰-누적) |
| 완전 초기화하고 다시 시작하고 싶다 | [12.5 체크포인트 초기화](#125-체크포인트-완전-초기화) |

---

## 📖 용어 3분 요약

이 단어들만 알고 있어도 나머지 내용이 술술 읽힙니다.

| 용어 | 한 줄 설명 |
|---|---|
| **spec.md** | "무엇을 만들지"를 담은 기획서. 사용자가 쓰거나 Planner가 요청으로부터 생성. |
| **Planner** | 기획을 잡고 검토하는 에이전트. spec과 plan-review, sprint-contract를 만듭니다. |
| **Generator** | 실제 코드를 짜는 에이전트. Claude Code `-p` 모드로 실행. |
| **Evaluator** | 결과물을 검증하고 PASS/FAIL을 찍는 에이전트. qa-report.md를 씁니다. |
| **Phase (5단계)** | `PLANNING → CONTRACT → GENERATING → EVALUATING → 판정`. 한 스프린트가 이 순서대로 흐릅니다. |
| **sprint** | "기획→구현→검증" 한 사이클. 큰 프로젝트는 여러 스프린트로 쪼개집니다. |
| **artifact** | `artifacts/` 폴더에 쌓이는 모든 중간/최종 산출물. |
| **승인 게이트** | 사용자 입력을 기다리며 오케스트레이터가 멈추는 지점. Slack 버튼이나 Enter로 통과. |
| **체크포인트** | `artifacts/.harness-checkpoint`에 저장되는 현재 Phase. 크래시 후 복구의 기준점. |
| **notifier** | Slack 또는 Telegram으로 알림을 보내는 모듈. `forge setup`에서 선택. |

---

## ⚠️ 에러 빠른 찾기

본문을 읽기 전에 **에러 메시지로 바로 해결**하고 싶다면 이 표부터:

| 메시지 (패턴) | 원인 | 해결 |
|---|---|---|
| `command not found: forge` | uv tool PATH 미등록 | [12.8](#128-forge-command-not-found) |
| `command not found: claude` | Claude Code CLI 미설치 | [12.7](#127-claude-command-not-found) |
| `spec.md가 없고 요청도 없습니다` | 빈 프로젝트에서 인자 없이 `forge run` | 요청 문자열 또는 `--plan` 제공 |
| `qa-report.md 검증 실패: ...` | Evaluator가 유효한 qa-report를 못 만듦 | `forge eval` 재실행 또는 수동 수정 |
| `scaffold/ 디렉토리를 찾을 수 없습니다` | 설치 방식 손상 | [12.13](#1213-scaffold-디렉토리를-찾을-수-없습니다) |
| `⚠️ 프로젝트명 ...는 이미 등록돼 있습니다` | registry 충돌 | [12.15](#1215-프로젝트명-충돌) |
| `Generator 시간 초과 (N분)` | subprocess timeout | `FORGE_MAX_GENERATOR_MINUTES` 증가 |
| `{backend} 크래시, /resume /skip /exit?` | 하위 subprocess 비-0 exit | [12.3](#123-상황-c--planner--evaluator-호출이-실패함) |
| Telegram `403 Forbidden` | Bot/Chat 설정 오류 | [12.9](#129-telegram-403-forbidden) |
| Slack `invalid_auth` / `not_authed` | 토큰 오류 | [12.10](#1210-slack이-반응하지-않거나-인증이-실패한다) |
| Slack `앱이 반응하지 않아 /forge-status ...` | forge 프로세스 미실행 | `forge run`으로 띄운 뒤 재시도. 정상 동작 |
| `[forge-deploy] FAILED - forge.exe may be running` | `forge.exe` 파일 락 | `taskkill /IM forge.exe /F` 후 재시도 |
| stderr `[forge] Langfuse ... failed` | Langfuse 전송 실패 | [12.11](#1211-langfuse가-전송-실패로-찍힌다) — 대부분 무시 가능 |

해당하는 게 없으면 [12절 트러블슈팅](#12-멈췄을-때--에러가-났을-때)을 펼쳐보세요.

---

# Part 1. 처음 설치하기

## 1. 사전 요구사항 · 토큰 발급

### 1.1 필수 도구

| 항목 | 최소 버전 | 확인 명령 |
|---|---|---|
| Python | **3.12 이상** | `python --version` 또는 `py -V` (Windows) |
| uv | 최신 | `uv --version` |
| Claude Code CLI | Max 플랜 구독 | `claude --version` |
| Git | 최신 | `git --version` |

- **uv 설치** — macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`. Windows PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
- **Claude Code CLI** — `claude.com/code`에서 설치. 로그인 후 `claude --version`이 동작해야 합니다.
- **Max 플랜** — THE FORGE는 공식 `claude` CLI를 서브프로세스로 호출합니다. 즉 **API 키가 아니라 CLI 로그인 세션이 기준**이며, 쿼터도 구독 플랜에서 나갑니다.

### 1.2 선택 도구

- **Node.js 18+** — Playwright E2E 자동 실행 시 필요. 프로젝트에 `playwright.config.*`가 있을 때만 실제로 돌립니다.
- **Langfuse 계정** — LLM 호출 트레이싱을 원할 때. 키가 없으면 **조용히 no-op**으로 동작하므로 연결하지 않아도 에러가 나지 않습니다.
- **Slack 워크스페이스** 또는 **Telegram 계정** — 원격 승인·알림 채널. 둘 중 하나만 고르면 됩니다.

### 1.3 토큰 발급 절차

#### Slack (권장 — 팀 공유, 버튼 UX, Slash Commands)

1. `api.slack.com/apps`에서 **From scratch**로 새 앱 생성.
2. **OAuth & Permissions → Scopes → Bot Token Scopes**: `chat:write`, `files:write`, `chat:write.customize` 추가.
3. **Socket Mode** 활성화 → **App-Level Tokens**에서 `connections:write` 권한으로 App Token 발급 (`xapp-...`).
4. 워크스페이스에 설치 → **Bot User OAuth Token** 복사 (`xoxb-...`).
5. 대상 채널에 앱 초대 → 채널 ID 복사 (`C01ABC...`, 채널 URL 마지막 세그먼트).

> 획득물: `xoxb-...` (Bot Token), `xapp-...` (App Token), `C01ABC...` (Channel ID). 이 3종을 [3절 `forge setup`](#3-최초-1회-전역-설정--forge-setup)에서 입력.

#### Telegram (간단 — 봇당 1 인스턴스)

1. Telegram에서 `@BotFather` 대화 열기 → `/newbot` → 이름/사용자명 지정 → Bot Token 발급 (`123456:ABC-DEF...`).
2. 본인 개인 채팅에서 봇에게 `/start` 한 번 전송.
3. 브라우저에서 `https://api.telegram.org/bot<TOKEN>/getUpdates` 열고 `"chat": {"id": ...}` 값 확인 → 이게 `TELEGRAM_CHAT_ID`.

> 획득물: `FORGE_TELEGRAM_BOT_TOKEN`, `FORGE_TELEGRAM_CHAT_ID`.
>
> ⚠️ Telegram은 **봇 하나당 동시에 receiver 1개**만 뜰 수 있습니다. 여러 프로젝트를 동시에 돌리려면 봇을 여러 개 만들거나 Slack을 쓰세요.

#### Langfuse (선택)

1. `cloud.langfuse.com` 가입 → 프로젝트 생성.
2. Settings → API Keys에서 `pk-lf-...` (Public), `sk-lf-...` (Secret) 발급.
3. 자체 호스팅이면 `FORGE_LANGFUSE_HOST`도 별도 지정 (기본: `https://cloud.langfuse.com`).

---

## 2. 설치 — 두 가지 경로

### 2.1 경로 A — `git clone` 후 전역 설치 (권장)

```bash
# 1. 저장소 clone
git clone https://github.com/HWAIN/THE_FORGE.git
cd THE_FORGE

# 2. 의존성 설치 + 가상환경 (.venv) 동기화
uv sync

# 3. forge 명령을 전역 도구로 등록
uv tool install .
```

이후 아무 터미널에서나 `forge`를 바로 호출할 수 있습니다.

**설치 검증**:

```bash
forge version              # THE FORGE v2.3.0
forge --help               # 전체 명령 목록
which forge                # macOS/Linux
where forge                # Windows
```

`command not found`가 뜨면 [12.8](#128-forge-command-not-found) 참조.

### 2.2 경로 B — 폴더만 복사해왔을 때

외장 SSD, USB, 사내 공유로 받거나 ZIP으로 풀어놓은 경우. `.git`이 없을 수 있고, 복사본의 `.venv/`는 절대경로가 박혀 있어 그대로 못 씁니다.

**폴더 복사 시 빠지는 것들**:

| 빠지는 것 | 증상 | 복구 |
|---|---|---|
| PATH 등록 | `forge` 명령이 안 잡힘 | 아래 둘 중 하나 |
| `.venv/` 재사용 | Python 경로 불일치 | `uv sync`로 재생성 |
| `.git/` (경우에 따라) | `git pull` 불가 | clone으로 다시 받거나 git init |

**선택지 1 — 개발자용, 전역 설치 없이 `uv run`**:

```bash
cd /path/to/복사된/THE_FORGE
uv sync
uv run forge --help
uv run forge setup
uv run forge init --root /path/to/my-project
uv run forge run "첫 요청" --root /path/to/my-project
```

소스 수정 즉시 반영됩니다. 단점: 항상 `uv run` 접두어 필요.

**선택지 2 — 복사한 폴더를 전역 도구로 승격**:

```bash
cd /path/to/복사된/THE_FORGE
uv sync
uv tool install .
forge version
```

경로 A와 동일하게 어디서나 `forge`가 잡힙니다.

> **Windows 주의**: `.venv/`는 복사로 이식 불가 → `uv sync`로 재생성. 한글 콘솔(cp949)에서도 유니코드 출력은 자동 처리되므로 거의 문제 없습니다.

### 2.3 두 경로 비교

| 항목 | 경로 A (clone + install) | 경로 B ① (uv run) | 경로 B ② (복사본 install) |
|---|---|---|---|
| `forge` 명령 | 전역 PATH | 프로젝트 내부만 | 전역 PATH |
| 소스 편집 반영 | 재설치 필요 | 즉시 반영 | 재설치 필요 |
| 업데이트 | `git pull && uv tool install . --force` | `git pull && uv sync` | 원본 복사 + 재설치 |

**권장**: 일반 사용자 → **경로 A**, 코드 기여자 → **경로 B ①**.

### 2.4 업그레이드

```bash
cd THE_FORGE
git pull
uv tool install . --force   # 기존 전역 설치 덮어쓰기
```

- `scaffold/`가 업데이트되었으면 프로젝트 쪽도 반영해야 합니다 → 해당 프로젝트 디렉토리에서 `forge update-templates`, `forge update-agents` 실행 (기존 파일은 `artifacts/.backup/`에 백업).

**`forge-deploy` — 원-커맨드 재배포 (alias)**

`forge-deploy` 한 번으로 `src/` 캐시 정리 + `uv tool install --force --reinstall`을 수행합니다. 코드를 자주 수정하는 기여자용.

- Git Bash → `~/.bashrc`에 alias 등록
- cmd/PowerShell → `%USERPROFILE%\.local\bin\forge-deploy.bat` 생성

### 2.5 제거

```bash
uv tool uninstall the-forge
```

CLI만 제거하고 `~/.forge/config.env`, `~/.forge/registry.json`은 남습니다.

완전 삭제:
- macOS/Linux: `rm -rf ~/.forge`
- Windows PowerShell: `Remove-Item -Recurse $env:USERPROFILE\.forge`

---

## 3. 최초 1회 전역 설정 — `forge setup`

### 3.1 이게 하는 일

```bash
forge setup
```

대화형 마법사가 `~/.forge/config.env`를 만들거나 갱신합니다. 이후 **모든 프로젝트**가 이 파일을 자동으로 읽으므로 **토큰은 한 번만 입력**하면 됩니다.

기존 값이 있으면 테이블로 표시되고, 빈 엔터를 치면 값이 유지됩니다.

### 3.2 입력 순서

| 순서 | 라벨 | 저장 키 | 필수 |
|---|---|---|---|
| 1 | Notifier 백엔드 | `FORGE_NOTIFIER_BACKEND` | 예 (기본 `slack`) |
| 2 | Slack Bot Token | `FORGE_SLACK_BOT_TOKEN` | Slack 선택 시 |
| 3 | Slack App-Level Token | `FORGE_SLACK_APP_TOKEN` | Slack 선택 시 |
| 4 | Slack Channel ID | `FORGE_SLACK_CHANNEL` | Slack 선택 시 |
| 5 | Langfuse Public Key | `FORGE_LANGFUSE_PUBLIC_KEY` | 아니오 |
| 6 | Langfuse Secret Key | `FORGE_LANGFUSE_SECRET_KEY` | 아니오 |
| 7 | Langfuse Host | `FORGE_LANGFUSE_HOST` | 아니오 (기본 `https://cloud.langfuse.com`) |

> Telegram 토큰은 **프로젝트마다 다른 봇을 쓰는 경우가 많아** 마법사에 포함돼 있지 않습니다. 프로젝트의 `.env`에 직접 넣으세요.

### 3.3 재입력 · 초기화

```bash
forge setup           # 기존 값 유지하며 일부만 갱신
forge setup --reset   # 전부 비우고 처음부터
```

### 3.4 보안 주의

- 마법사가 파일 권한을 `0o600`으로 설정합니다 (Windows는 OS 레벨에서 무시되지만 에러는 안 남).
- **이 파일은 절대 Git에 커밋하지 마세요**. 기본 위치가 `~/.forge/`라 프로젝트 외부에 있어 실수할 일은 거의 없습니다.

### 3.5 생성 결과 예시

```env
# ~/.forge/config.env — forge setup이 생성/갱신
FORGE_NOTIFIER_BACKEND="slack"
FORGE_SLACK_BOT_TOKEN="xoxb-..."
FORGE_SLACK_APP_TOKEN="xapp-..."
FORGE_SLACK_CHANNEL="C01ABC..."
FORGE_LANGFUSE_PUBLIC_KEY="pk-lf-..."
FORGE_LANGFUSE_SECRET_KEY="sk-lf-..."
FORGE_LANGFUSE_HOST="https://cloud.langfuse.com"
```

---

## 4. 프로젝트 부트스트랩 — `forge init`

### 4.1 실행 위치

**대상 프로젝트 디렉토리로 이동한 뒤** 실행하거나 `--root`로 지정.

```bash
cd /path/to/my-project
forge init
# 또는
forge init --root /path/to/my-project
```

### 4.2 자동 프로젝트명 추론

디렉토리명이 snake_case로 자동 변환됩니다.

| 디렉토리명 | → 프로젝트명 |
|---|---|
| `obsidian-sync` | `obsidian_sync` |
| `My Project` | `my_project` |
| `서버` (비영문) | `project` (안전 폴백) |

표시용 봇 이름은 `Forge-{PascalCase}` (예: `Forge-ObsidianSync`).

**이름 중복 시**: `~/.forge/registry.json`에 같은 이름이 다른 경로로 이미 있으면 경고가 뜨고 새 이름을 묻습니다. 엔터만 치면 `{원래이름}_{상위폴더}` 형태로 자동 변경됩니다.

### 4.3 📦 안심 박스 — `forge init`이 내 프로젝트에 하는 일 / 안 하는 일

> **✅ 건드리는 것 (덮어쓰거나 추가)**
>
> - `CLAUDE.md` — 없으면 생성. 있으면 `--force` 쓸 때만 `artifacts/.backup/`으로 옮기고 덮어씀.
> - `.claude/agents/*.md` (planner/generator/evaluator/journal) — 복사.
> - `.claude/settings.json` — **병합**. 기존 hooks는 유지, 중복 command만 건너뜀.
> - `.mcp.json` — 없을 때만 복사 (Playwright + Context7 MCP).
> - `templates/*.md` — 11종 복사.
> - `artifacts/`, `artifacts/specs/`, `artifacts/decisions/`, `docs/` — 없으면 생성.
>
> **✅ 없을 때만 추가 (있으면 안 건드림)**
>
> - `.env` — `FORGE_PROJECT_NAME="..."` 한 줄만. 이미 있으면 그대로 둠.
> - `pyproject.toml`의 `[tool.forge]` 섹션 — 없을 때만 append. `pyproject.toml`이 아예 없으면 만들지도 않음.
> - `.gitignore` — 12개 항목을 미존재 시에만 append.
>
> **❌ 절대 건드리지 않는 것**
>
> - 기존 소스 코드 (`src/`, `app/` 등 전부 포함)
> - 기존 테스트
> - 기존 `README.md`
> - 기존 `package.json` / `Cargo.toml` / `go.mod` 등 다른 언어의 매니페스트
> - Git 히스토리
>
> **🔧 `--force` 플래그를 쓰면?**
>
> - `CLAUDE.md`, `.claude/settings.json`, `.env`가 `artifacts/.backup/`에 백업된 뒤 덮어쓰기.
> - `templates/`, `.claude/agents/`가 scaffold 최신 버전으로 교체.
> - **여전히 소스 코드는 건드리지 않습니다**.

### 4.4 🔒 Git에 뭘 커밋하고 뭘 무시하나

`forge init`이 `.gitignore`에 자동으로 추가하는 항목은 다음과 같습니다 (이미 `.gitignore`가 있으면 항목이 없을 때만 append).

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

**이유 요약**:

| 무시 대상 | 왜? |
|---|---|
| `.env` | 토큰/키가 들어감 |
| `spec.md`, `plan-review.md`, `sprint-contract.md`, `progress-log.md`, `qa-report.md` | 매 실행마다 덮어써지는 작업 파일. 리뷰할 거면 `sprint-N-done.md`가 아카이브 역할 |
| `.harness-checkpoint`, `.*-signal` | 런타임 상태/신호. 커밋돼도 다른 머신에서 의미 없음 |
| `harness-cost-log.txt` | 내 구독 쿼터 로그, 공유할 필요 없음 |

**커밋해야 하는 것**:

| 대상 | 왜 커밋하나 |
|---|---|
| `sprint-N-done.md` | 완료된 스프린트의 영구 아카이브. **의도적으로 ignore 대상 아님** |
| `CLAUDE.md`, `.claude/agents/*.md`, `.claude/settings.json` | 팀원이 동일 환경에서 돌릴 수 있게 공유 |
| `templates/`, `.mcp.json` | 에이전트 설정의 일부 |
| `pyproject.toml [tool.forge]` | 팀 공유 타임아웃/턴수 |
| 실제 소스 코드 | Generator가 만든 결과물이 여기 있습니다 |

### 4.5 비-Python 프로젝트에서

`pyproject.toml`이 없어도 동작합니다. Node.js·Rust·Go 프로젝트에서도 `.env`와 scaffold는 정상 설치되며, 공유 설정은 `forge.toml` 또는 환경 변수로 관리하세요 ([5.1](#51-7단-우선순위) 참조).

---

# Part 2. 설정 이해하기

## 5. 설정 우선순위와 환경 변수

### 5.1 7단 우선순위

값이 해석되는 순서(**위가 우선**, 먼저 나오는 비어있지 않은 값이 최종값):

1. **프로세스 환경 변수** — `FORGE_*`로 export된 값.
2. **프로젝트 `.env`** — 대상 프로젝트 루트의 `.env`.
3. **전역 `~/.forge/config.env`** — `forge setup`으로 저장된 파일.
4. **`forge.toml [forge]`** — 프로젝트 루트의 `forge.toml` (선택).
5. **`pyproject.toml [tool.forge]`** — Python 프로젝트용 공유 설정.
6. **자동 추론** — 프로젝트명 등.
7. **내장 기본값** — 아래 표의 기본값 열.

### 5.2 어디에 값을 두어야 하나

| 성격 | 권장 위치 | 예시 |
|---|---|---|
| 전역 공유 토큰 (변하지 않음) | `~/.forge/config.env` | `FORGE_SLACK_BOT_TOKEN`, `FORGE_LANGFUSE_*` |
| 프로젝트별 이름·봇 얼굴 | 프로젝트 `.env` | `FORGE_PROJECT_NAME`, `FORGE_BOT_DISPLAY_NAME`, `FORGE_BOT_EMOJI` |
| 프로젝트별 Telegram 봇 | 프로젝트 `.env` | `FORGE_TELEGRAM_BOT_TOKEN`, `FORGE_TELEGRAM_CHAT_ID` |
| 팀이 공유할 타임아웃/턴수 | `pyproject.toml [tool.forge]` | `max_sprint_minutes`, `generator_max_turns` |
| CI/일시 오버라이드 | 셸 환경 변수 | `FORGE_NOTIFIER_BACKEND=telegram forge run ...` |

### 5.3 모든 `FORGE_*` 환경 변수

| 환경 변수 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `FORGE_PROJECT_NAME` | str | 디렉토리명 추론 | 식별자. snake_case. |
| `FORGE_BOT_DISPLAY_NAME` | str | `Forge-{PascalCase}` | Slack 메시지의 username. |
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
| `FORGE_MAX_GENERATOR_MINUTES` | int | `120` | Generator 타임아웃. |
| `FORGE_PLANNER_MAX_TURNS` | int | `15` | Planner generate 턴. |
| `FORGE_PLANNER_REVIEW_MAX_TURNS` | int | `10` | Planner review 턴. |
| `FORGE_CONTRACT_MAX_TURNS` | int | `12` | Sprint Contract 생성 턴. |
| `FORGE_EVALUATOR_MAX_TURNS` | int | `20` | Evaluator QA 턴. |
| `FORGE_GENERATOR_MAX_TURNS` | int | `180` | Generator `--max-turns`. |
| `FORGE_JOURNAL_MAX_TURNS` | int | `80` | `forge journal` 턴. |
| `FORGE_PLAYWRIGHT_ENABLED` | bool | `true` | Evaluator E2E 자동 실행. |
| `FORGE_PLAYWRIGHT_TIMEOUT_SECONDS` | int | `600` | Playwright 타임아웃. |
| `FORGE_MAX_TOTAL_MINUTES` | int | `1440` | 전체 누적 시간 상한 (24h). |
| `FORGE_MAX_CONSECUTIVE_FAILS` | int | `3` | 연속 FAIL 허용. |
| `FORGE_MAX_TOTAL_SPRINTS` | int | `20` | 자동 루프 최대 스프린트. |
| `FORGE_APPROVAL_TIMEOUT_SECONDS` | int | `86400` | 승인 대기 타임아웃 (24h). |

### 5.4 `pyproject.toml [tool.forge]` 예시

```toml
[tool.forge]
max_sprint_minutes = 180
max_generator_minutes = 120
planner_max_turns = 15
planner_review_max_turns = 10
contract_max_turns = 12
evaluator_max_turns = 20
generator_max_turns = 180
journal_max_turns = 120         # 오래 걸리는 저널용
max_consecutive_fails = 3
max_total_sprints = 20
```

빈 문자열(`""`)은 파싱에서 무시됩니다.

---

# Part 3. 실행

## 6. `forge run` — 실행의 모든 것

### 6.1 진입 패턴 4가지

#### 패턴 A — 짧은 요청 (spec.md 없이)

```bash
forge run "LangGraph 기반 대화 에이전트 뼈대 만들어줘"
```

`artifacts/spec.md`가 없으면 Planner가 요청 문자열로부터 spec.md를 생성합니다.

#### 패턴 B — 기획서 파일

```bash
forge run --plan ./my-plan.md
forge run -p ./my-plan.md              # 별칭
```

지정한 마크다운 파일을 `artifacts/spec.md`로 복사한 뒤 Planner가 검토 단계부터 시작합니다. 이미 `spec.md`가 있으면 덮어쓰지 않습니다.

#### 패턴 C — 체크포인트 자동 복구

```bash
forge run
```

인자 없이 실행하면 `artifacts/.harness-checkpoint`의 Phase를 읽어 이어서 진행. 체크포인트가 없으면 `spec.md`가 있어야 합니다.

#### 패턴 D — 특정 Phase부터 강제 시작

```bash
forge run --from contract
forge run --from generating
forge run --from evaluating
forge run --from planning
```

`--from` 값으로 체크포인트를 강제 재설정합니다. 허용값: `planning`, `contract`, `generating`, `evaluating` (대소문자 무관).

#### 루트 지정

```bash
forge run "요청" --root /path/to/other-project
forge run "요청" -r /path/to/other-project
```

### 6.2 5-Phase 사이클 — 비유로 이해하기

한 스프린트는 **소규모 팀의 하루 업무**를 모델로 합니다.

```
📋 PLANNING        기획 — "이걸 왜 만드나? 어떻게 쪼개나?"
   ↓               (spec.md, specs/*.md, plan-review.md 생성)
📝 CONTRACT        이번 스프린트 계약서 — "이번엔 어디까지 한다"
   ↓               (sprint-contract.md 생성, 다음 스프린트 존재 여부 결정)
🔨 GENERATING      구현 — Generator가 실제 코드를 짭니다
   ↓               (progress-log.md, decisions/*.md, 소스 커밋)
🔍 EVALUATING      검증 — Evaluator가 체크박스·테스트·E2E를 확인
   ↓               (qa-report.md 생성)
🎯 판정             PASS → sprint-N-done.md로 아카이브 → 다음 스프린트
                   FAIL → CONTRACT_DONE으로 되돌려 Generator 재진입
```

**생성물 요약**:

| Phase | 에이전트 | 생성물 |
|---|---|---|
| PLANNING | Planner | `spec.md`, `specs/*.md`, `plan-review.md` |
| CONTRACT | Planner | `sprint-contract.md` (스프린트마다 덮어씀) |
| GENERATING | Generator | `progress-log.md`, `decisions/*.md`, 실제 소스 커밋 |
| EVALUATING | Evaluator (+선택적 Playwright) | `qa-report.md` |
| 판정 | 오케스트레이터 | PASS → `sprint-N-done.md` 아카이브 / FAIL → 체크포인트 되감기 |

### 6.3 자동 스프린트 루프

**기본 동작 (옵션 없음)**: PASS + `has_next_sprint: true` (sprint-contract.md 프론트매터)이면 `/resume` 대기 후 자동으로 다음 스프린트. FAIL이면 `/resume` / `/eval` / `/stop` 중 선택.

```bash
forge run "처음 요청"                   # has_next_sprint가 false가 될 때까지 자동
forge run --single-sprint "처음 요청"   # 1 스프린트만 돌고 종료
forge run --max-sprints 3 "처음 요청"   # 최대 3개
```

### 6.4 안전장치 3종 — 무한 루프 방지

다음 중 하나라도 걸리면 자동 중단합니다:

| 조건 | 환경 변수 | 기본값 | 동작 |
|---|---|---|---|
| 누적 스프린트 수 ≥ | `FORGE_MAX_TOTAL_SPRINTS` 또는 `--max-sprints` | 20 | `auto_stop` 알림 후 종료 |
| 연속 FAIL ≥ | `FORGE_MAX_CONSECUTIVE_FAILS` | 3 | `auto_stop` 알림 + qa-report 첨부 |
| 누적 시간 > (분) | `FORGE_MAX_TOTAL_MINUTES` | 1440 (24h) | `budget_exceeded` 알림 + cost-log 첨부 |

이 중단은 **체크포인트를 유지**한 채 나갑니다. 조건을 수정하고 `forge run`을 다시 호출하면 이어집니다.

### 6.5 첫 스프린트의 승인 게이트

- **PLANNING 완료 시** — `plan-review.md`의 상태에 따라 버튼이 달라집니다:
  - 상태 `READY` → `[/resume] [/exit]`.
  - 상태 `NEEDS_REVISION` → `[/skip] [/resume] [/exit]`. `/skip`만이 강제 진행하며, `/resume`을 누르면 중단됩니다(Planner가 "아직 아니라고" 한 걸 무시하지 않기 위함).
- **Sprint 1의 CONTRACT 완료 시** — `[/resume] [/exit]` 대기.
- **Sprint 2+ 의 CONTRACT** — 자동 진행 (승인 없음). 첫 승인만으로 전체 프로젝트에 대한 위임이 이루어집니다.

### 6.6 종료 코드

| 코드 | 의미 |
|---|---|
| `0` | 정상 종료 (프로젝트 완료 / `/stop` / `/exit` / `--single-sprint` PASS) |
| `1` | `--single-sprint` 모드에서 FAIL |
| `2` | spec.md 없고 요청도 없음 |
| `3` | `claude: command not found` |
| `4` | `qa-report.md` 검증 실패 |

---

## 7. 실행 중 사용자 개입

### 7.1 승인 게이트 — 언제 멈추나

오케스트레이터가 입력을 기다리는 시점:

1. **PLANNING 완료 후** — plan-review 검토.
2. **Sprint 1 CONTRACT 완료 후** — 첫 스프린트 범위 승인.
3. **PASS + has_next_sprint=true** — 다음 스프린트 진행 여부.
4. **FAIL** — 재시도·재평가·중단 선택.

이 외의 Phase 전이는 전부 자동입니다.

### 7.2 Telegram · Slack 공통 명령어

| 명령 | 한글 별칭 | 효과 |
|---|---|---|
| `/resume` | `/계속`, `/진행`, `/approve` | 승인 통과 / FAIL 후 Generator 재진입 |
| `/skip` | `/스킵`, `/무시` | plan-review `NEEDS_REVISION` 강제 진행 |
| `/continue` | — | 예약 (현재 미사용) |
| `/exit` | `/종료` | PLANNING 단계 중단 |
| `/eval` | `/재평가` | FAIL 후 Evaluator만 재실행 |
| `/stop` | `/중단` | 자동 스프린트 루프 중단 |
| `/revise` | `/수정` | **Slack 전용**: 모달로 수정 지시 입력 → Planner 재수정 |
| `/status` | `/상태` | 현재 Phase/Sprint/누적시간 회신 |
| `/help` | `/도움` | 명령어 도움말 회신 |

Slack에서는 알림 메시지에 버튼이 붙어 타이핑 없이 클릭만으로 가능합니다.

**Slack Slash Commands** (Slack App → Features → Slash Commands에 등록, Request URL 비움 — Socket Mode):

| 명령 | 인자 | 동작 |
|---|---|---|
| `/forge-status` | 없음 또는 `[project_name]` | 실행 중 forge 프로세스 상태 조회 |

**`/revise` 버튼 (Slack 전용)**: Planner 알림의 `[✏️ revise]` 클릭 → 입력 모달 → 수정 지시 제출 → Planner가 재실행되어 `spec.md`를 수정. 만족할 때까지 반복 가능.

### 7.3 시그널 파일 직접 생성 — 비상용

봇이 응답 안 하거나 네트워크가 막혔을 때:

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

오케스트레이터는 2초 간격으로 시그널 파일을 폴링하며, 감지 후 자동 삭제합니다.

### 7.4 stdin 직접 입력 — CLI만으로 운용

`forge run`을 실행한 터미널에 그냥 **Enter**를 치면 `resume`으로 해석됩니다.

- Windows: 아무 키 + Enter.
- macOS/Linux: Enter만.

Telegram/Slack 없이 CLI만으로 돌릴 때 유용합니다.

### 7.5 Telegram 파일 업로드로 artifact 덮어쓰기

Telegram에서 파일을 보내며 caption을 `artifacts/<경로>` 형태로 적으면 해당 경로에 저장됩니다.

```
(파일 첨부)
caption: artifacts/spec.md
```

- 기존 파일은 `artifacts/.backup/{원파일명}.bak`으로 이동.
- `artifacts/` 밖으로 벗어나는 상대경로는 거부됩니다 (traversal 방어).
- 성공 시 `✅ artifacts/spec.md 저장 완료` 회신.

모바일에서 기획서를 수정한 뒤 `/resume`으로 다음 단계를 트리거할 수 있습니다.

### 7.6 Generator 실행 중 개입

v2.3에서 Generator는 `claude -p` 비대화형 서브프로세스로 돕니다. 실시간 개입 방법:

- **Ctrl+C** — 서브프로세스 즉시 종료, 체크포인트가 `GENERATING`으로 유지됨. `forge run` 다시 돌리면 이어집니다.
- **타임아웃** — `FORGE_MAX_GENERATOR_MINUTES` 초과 시 `warning` 알림 후 중단.
- **Generator 완료 후 수정** — `progress-log.md`/코드를 직접 수정한 뒤 `/eval`로 Evaluator만 재검증.

---

## 8. QA 결과별 분기

### 8.1 PASS 분기

Evaluator가 `qa-report.md` 마지막 줄에 `PASS`를 기록하면:

- `artifacts/sprint-N-done.md`로 복사 (영구 아카이브, Git 추적).
- `sprint-contract.md` 프론트매터의 `has_next_sprint`를 확인.

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

### 8.2 FAIL 분기

- `consecutive_fails += 1`.
- 체크포인트를 `CONTRACT_DONE`으로 강제 리셋 → 다음 `/resume` 시 Generator 재진입.
- 알림 버튼: `[/resume] [/eval] [/stop]`.

| 신호 | 동작 |
|---|---|
| `/resume` | Generator 재진입 (같은 sprint-contract로 다시 구현) |
| `/eval` | Evaluator만 재실행. 평가가 잘못된 경우. |
| `/stop` | 루프 중단. 체크포인트 유지. |
| 타임아웃 | `approval_timeout_seconds` 초과 시 타임아웃 처리. |

연속 FAIL이 `max_consecutive_fails`(기본 3) 이상이면 다음 반복 진입 직전에 자동 중단됩니다.

### 8.3 qa-report.md 검증 실패

파일 자체가 없거나 형식이 잘못되면 exit code 4로 종료. `forge eval`로 Evaluator를 재실행하거나 수동으로 파일을 수정 후 다시 진행하세요.

---

## 9. `artifacts/` 안에서 벌어지는 일

| 파일 | 생성자 | 수명 | Git |
|---|---|---|---|
| `artifacts/spec.md` | Planner (1회) | 프로젝트 수명 | ignore |
| `artifacts/specs/*.md` | Planner | 프로젝트 수명 | ignore |
| `artifacts/plan-review.md` | Planner | spec.md 갱신 시 자동 무효화 | ignore |
| `artifacts/sprint-contract.md` | Planner | 스프린트마다 덮어씀 | ignore |
| `artifacts/progress-log.md` | Generator | 누적 (최상단 추가) | ignore |
| `artifacts/qa-report.md` | Evaluator | 스프린트마다 덮어씀 | ignore |
| `artifacts/sprint-N-done.md` | 오케스트레이터 (PASS) | 영구 아카이브 | **추적** |
| `artifacts/harness-cost-log.txt` | SprintTracer | 누적 append | ignore |
| `artifacts/.harness-checkpoint` | 오케스트레이터 | 매 Phase save | ignore |
| `artifacts/decisions/*.md` | Generator | 영구 | ignore (기본) |
| `artifacts/.backup/` | init/update | 수동 삭제까지 유지 | ignore |
| `artifacts/.*-signal` | receiver / 사용자 | 감지 후 자동 삭제 | ignore |
| `docs/journal.md` | `forge journal` | 누적 (최상단 추가) | **추적 권장** |

---

# Part 4. 관측 · 보조 명령

## 10. 상태 확인 · 저널 · 관측

### 10.1 `forge status` — 지금 어디쯤 왔나

```bash
forge status
forge status --root /path/to/other-project
```

출력 예:

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

### 10.2 `forge journal` — 엔지니어링 저널

`docs/journal.md`에 누적 기록을 생성합니다.

```bash
forge journal                          # 마지막 엔트리 이후 변경분만
forge journal --sprint 3               # 특정 스프린트
forge journal -s 3                     # 별칭
forge journal --sprints 1-4            # 범위
forge journal --sprints 1,3,5          # 목록
forge journal --sprints 1-3,5          # 혼합
forge journal --since 2026-04-01       # 날짜 이후
forge journal --root /other/project
```

- `--sprint`, `--sprints`, `--since`는 **동시에 하나만** 허용.
- 저널 생성 후 활성 notifier로 요약 + 파일 첨부가 자동 전송됩니다.
- 턴 소진으로 끝나지 않으면 `FORGE_JOURNAL_MAX_TURNS`를 올리거나 범위를 좁히세요.

### 10.3 `harness-cost-log.txt` — 비용/토큰 누적

```
[2026-04-18T10:30:45] sprint=1 phase=planner minutes=5.2 tokens_in=12340 tokens_out=4820
[2026-04-18T10:38:12] sprint=1 phase=generator minutes=27.8 tokens_in=89210 tokens_out=31450
```

- **누적 분 계산**은 `minutes=` 값을 합산.
- Claude Pro/Max 구독 쿼터 감각을 잡는 용도.

### 10.4 Langfuse 추적 (선택)

`SprintTracer`가 활성일 때(키 존재 시):

- 각 Phase마다 span 생성 (`planner`, `generator`, `evaluator` 등).
- `claude -p`의 stdout에서 토큰 사용량을 정규식으로 파싱해 span 속성에 부착.
- Langfuse 대시보드에서 스프린트/Phase별 토큰·시간을 확인 가능.

키가 없으면 **조용히 no-op**. 신경 쓰지 않아도 됩니다.

---

## 11. 보조 명령 모음

### 11.1 `forge eval`

Evaluator만 수동으로 한 번 더 돌립니다. QA가 잘못 판정했거나 코드를 손으로 수정한 뒤 재검증할 때.

```bash
forge eval
forge eval --root /other/project
```

- `qa-report.md`가 새로 쓰입니다.
- `sprint-N-done.md` 아카이브는 만들지 않습니다 (수동 실행이므로). 아카이브가 필요하면 이후 `forge run`으로 정상 루프 복귀.

### 11.2 `forge notify`

외부 스크립트(예: Claude Code hooks)에서 일회성 알림:

```bash
forge notify session_stop "세션 종료" artifacts/progress-log.md
forge notify info "백업 완료"
```

- 첫 인자 `event_type` — 이벤트 키 (예: `session_stop`, `info`, `warning`).
- 둘째 `message` — 본문.
- 셋째 (선택) `file_path` — 첨부 파일.
- `--root`로 대상 프로젝트 지정 가능.

### 11.3 `forge update-templates` / `forge update-agents`

THE FORGE 본체 업그레이드 후 프로젝트의 `templates/`, `.claude/agents/`를 최신 scaffold로 재동기화.

```bash
forge update-templates --dry-run    # 변경 대상만 출력
forge update-templates              # 실제 적용 (기존은 artifacts/.backup/에 백업)
forge update-agents --dry-run
forge update-agents
```

- 내용이 동일한 파일은 건너뜁니다.
- **주의**: 프로젝트에서 커스텀 수정한 agents/templates가 있다면 먼저 `--dry-run`으로 확인하세요. 덮어쓰면 사용자 수정본은 `.backup/`에만 남습니다.

### 11.4 `forge version`

```bash
forge version
# THE FORGE v2.3.0
```

---

# Part 5. 멈췄을 때

## 12. 멈췄을 때 · 에러가 났을 때

### 12.1 이어서 하기 — 어제 멈췄다면

**대부분의 경우 `forge run` 한 줄이면 끝납니다.**

체크포인트(`artifacts/.harness-checkpoint`)가 현재 Phase를 저장하고 있어 자동 복구됩니다:

```bash
cd /path/to/my-project
forge run                         # 인자 없이도 OK — 체크포인트가 이어받음
```

**상황별 동작**:

| 마지막 상태 | `forge run`이 하는 일 |
|---|---|
| PLANNING 중 중단 | Planner를 처음부터 다시 |
| CONTRACT 중 중단 | Sprint Contract 생성부터 다시 |
| GENERATING 중 중단 | Generator를 이어서 (`progress-log`와 qa-report 참조해 다시 진행) |
| EVALUATING 중 중단 | Evaluator를 다시 |
| 승인 게이트에서 멈춤 | 다시 멈춤 — Slack 버튼 또는 Enter로 통과 |

### 12.2 상황 A — Generator 서브프로세스/터미널 크래시

**증상**: Generator 실행 중 터미널이 닫히거나 전원이 꺼짐.

**복구**:
1. 오케스트레이터도 함께 종료되지만 체크포인트는 `GENERATING`으로 남아 있습니다.
2. `forge run` 재실행 → Generator를 다시 호출.
3. Generator는 `qa-report.md`가 있으면 FAIL 항목부터, 없으면 sprint-contract 체크박스 순서대로, 기존 `progress-log`를 참조해 자연스럽게 이어집니다.

**수동 개입**: 보통 없음.

### 12.3 상황 B — 오케스트레이터 자체 사망

**증상**: Python 예외 / OOM / `kill -9` / 전원 차단.

**복구**:
1. `finally` 블록의 `notifier.stop()`은 못 타고 죽을 수 있지만 체크포인트는 마지막 save 시점까지 보존됩니다.
2. `forge run` 재실행 → 해당 Phase 진입.

**반복 크래시**라면 원인(메모리, 코드 버그) 조사가 필요합니다.

### 12.3 상황 C — Planner / Evaluator 호출이 실패함

**증상**: `claude -p`가 네트워크/세션/턴소진으로 비-0 종료.

**복구 선택지**:

- `forge run` 다시 호출 → 같은 Phase 재시도.
- `forge eval`로 Evaluator만 재실행.
- Telegram/Slack `/eval` 버튼 클릭.

### 12.4 Phase 강제 재설정

체크포인트를 통째로 지우지 않고 특정 Phase부터 이어가고 싶을 때:

```bash
forge run --from planning    # 다시 Planner 리뷰부터
forge run --from contract    # Sprint Contract부터
forge run --from generating  # Generator부터 (이미 만들어진 contract로)
forge run --from evaluating  # Evaluator만
```

`--from evaluating`은 `forge eval`과 거의 동등하지만 자동 루프 흐름 안에서 실행된다는 점이 다릅니다.

### 12.5 체크포인트 완전 초기화

```bash
rm artifacts/.harness-checkpoint           # macOS/Linux
del artifacts\.harness-checkpoint          # Windows cmd
Remove-Item artifacts/.harness-checkpoint  # PowerShell
```

파일이 없으면 다음 실행은 처음부터 시작합니다.

### 12.6 Ctrl+C로 중단하기

안전합니다. 체크포인트는 현재 Phase 직전/직후 두 번 저장되므로, 어디서 끊어도 대부분 한 Phase 되감기만으로 복구됩니다.

### 12.7 `claude: command not found`

- Claude Code CLI 미설치. `claude.com/code`에서 설치 후 `claude --version` 확인.
- Windows에서 설치했는데 안 잡히면 **새 터미널 또는 재로그인** 필요.
- 오케스트레이터는 이 에러를 exit code 3으로 종료합니다.

### 12.8 `forge: command not found`

- `uv tool install .`을 돌렸는데 PATH에 uv tool bin이 없을 때.
  - macOS/Linux: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc` (또는 `.bashrc`) → 새 터미널.
  - Windows: `%USERPROFILE%\.local\bin`을 PATH 환경 변수에 추가 후 재로그인.
  - `uv tool update-shell` 명령이 자동으로 넣어주기도 합니다.
- 일시적 우회: `uv run forge ...`.

### 12.9 Telegram 403 Forbidden

- Bot Token 오류 / 사용자가 봇에게 `/start`를 보낸 적 없음 / `chat_id` 오류.
- 해결: 봇 대화에서 `/start` → `https://api.telegram.org/bot<TOKEN>/getUpdates`에서 `chat.id` 재확인.
- 프로젝트 `.env`에 `FORGE_TELEGRAM_BOT_TOKEN`, `FORGE_TELEGRAM_CHAT_ID`가 둘 다 비어있지 않은지 확인.

### 12.10 Slack이 반응하지 않거나 인증이 실패한다

- 3종 토큰(`FORGE_SLACK_BOT_TOKEN`, `FORGE_SLACK_APP_TOKEN`, `FORGE_SLACK_CHANNEL`)이 모두 채워져야 Slack이 활성화됩니다.
- **Socket Mode가 비활성**이면 App Token으로 WebSocket 연결이 안 됩니다.
- **Bot이 채널에 초대**되어 있어야 메시지 전송이 성공합니다.
- `slack_sdk` 패키지가 설치돼 있는지 확인 (누락 시 Telegram으로 폴백되는 조건부 import가 있음).

### 12.11 Langfuse가 전송 실패로 찍힌다

- `.env`/`~/.forge/config.env`에 public/secret key가 없으면 **조용히 no-op**으로 동작하므로 에러 아님.
- 네트워크 이슈 등으로 실제 전송 실패 시 stderr에 `[forge] Langfuse ... failed: ...` 한 줄이 뜨지만 파이프라인은 계속 진행됩니다. 대부분 무시해도 됩니다.

### 12.12 Windows 유니코드 · stdin 이슈

- cp949 콘솔에서 이모지/한글 깨짐 → 자동으로 UTF-8 재설정 시도. 그래도 깨지면 **Windows Terminal** 또는 **VS Code 내장 터미널**을 사용 (cmd.exe 피하기).
- stdin 감지 안 됨 → 시그널 파일로 우회(`touch artifacts/.approval-signal`).

### 12.13 `scaffold/ 디렉토리를 찾을 수 없습니다`

- 경로 B로 폴더만 복사받았는데 `scaffold/`가 누락된 경우. 전체 폴더(특히 `scaffold/`)가 복사됐는지 확인.
- 휠 빌드 설정이 깨진 경우도 드물게 발생 — 최신 `pyproject.toml`은 `scaffold/`를 휠에 포함합니다.

### 12.14 `pyproject.toml [tool.forge]` 섹션 중복

- `forge init`은 없을 때만 append하므로 여러 번 돌려도 중복되지 않습니다.
- 수동으로 두 블록을 만든 경우 TOML 파싱 에러가 날 수 있으니 하나만 남기세요.

### 12.15 프로젝트명 충돌

- `~/.forge/registry.json`에 같은 이름이 다른 경로로 이미 있음.
- `forge init` 시 대화형으로 새 이름을 묻습니다. 추천: 기본값(`{name}_{parent}`) 그대로 수락.
- 완전 초기화가 필요하면 해당 엔트리를 수동 편집하거나 `~/.forge/registry.json`을 삭제 (재사용 추적만 잃고 동작엔 무해).

### 12.16 Playwright 타임아웃

- 기본 600초(10분). 테스트가 많으면 `FORGE_PLAYWRIGHT_TIMEOUT_SECONDS`를 늘리세요.
- `playwright.config.*`가 없으면 자동으로 E2E를 건너뜁니다.
- 완전 비활성: `FORGE_PLAYWRIGHT_ENABLED=false`.

### 12.17 `.env` 값이 적용되지 않는다

- 우선순위를 오해한 경우 ([5.1](#51-7단-우선순위) 참조). 셸 환경 변수에 같은 키가 export되어 있으면 그것이 우선합니다.
- 확인: `env | grep FORGE_` (Unix) / `Get-ChildItem env:FORGE_*` (PowerShell).

### 12.18 Sprint 2+가 자동 시작되지 않는다

- `sprint-contract.md` 프론트매터의 `has_next_sprint`가 `true`가 아닙니다. Planner가 "마지막 스프린트"라고 판단했다는 뜻.
- 더 돌리려면 `spec.md`를 확장한 뒤 `forge run --from planning`으로 재기획.

### 12.19 `consecutive_fails`가 쌓여 멈춘다

- 3회 연속 FAIL 후 자동 중단.
- 해결: `qa-report.md`를 읽고 근본 원인 파악 → 수동 수정 → `forge eval`로 재검증 → PASS 받고 `forge run`으로 복귀.

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
├── pyproject.toml           # [tool.forge] 공유 설정
├── templates/               # Planner 참조 템플릿
│   ├── INDEX.md
│   ├── sprint-contract-template.md
│   ├── generator-guide.md
│   ├── journal-guide.md
│   └── ...
└── artifacts/               # 런타임 결과물
    ├── spec.md
    ├── specs/*.md
    ├── plan-review.md
    ├── sprint-contract.md
    ├── progress-log.md
    ├── qa-report.md
    ├── sprint-1-done.md     # ← Git 추적 대상
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

## 부록 B. 시그널 파일 요약

| 파일 | 생성자 | 오케스트레이터 동작 |
|---|---|---|
| `artifacts/.approval-signal` | receiver / 사용자 | 승인 게이트 통과 |
| `artifacts/.skip-signal` | receiver / 사용자 | plan-review NEEDS_REVISION 강제 skip |
| `artifacts/.continue-signal` | receiver / 사용자 | 예약 (현재 미사용) |
| `artifacts/.exit-signal` | receiver / 사용자 | PLANNING 단계 중단 |
| `artifacts/.eval-signal` | receiver / 사용자 | FAIL 후 Evaluator만 재실행 |
| `artifacts/.stop-signal` | receiver / 사용자 | 자동 스프린트 루프 중단 |
| `artifacts/.revise-signal` | Slack view_submission | 수정 지시를 Planner 재실행에 전달 |

감지 주기 2초. 감지 후 자동 삭제.

## 부록 C. CLI 명령 한눈에

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

**외부 명령** (CLI 아님 — alias/.bat 등록 필요, [2.4](#24-업그레이드) 참조)
- `forge-deploy` — `src/` 캐시 정리 후 전역 재설치

**Slack Slash Commands** (Slack App 등록 필요, [7.2](#72-telegram--slack-공통-명령어) 참조)
- `/forge-status [project_name]` — 실행 중 forge 프로세스 상태 조회

---

## 문서 끝

- 이 문서를 따라 `forge setup` → `forge init` → `forge run "첫 요청"` 세 명령까지 실패 없이 도달할 수 있어야 합니다.
- 개발자 관점의 코드 레퍼런스(파일:라인, 내부 함수)는 [`docs/DEV.md`](./DEV.md)에 별도로 정리되어 있습니다.
- 아키텍처·내부 설계 심화는 [`docs/핵심기술.md`](./핵심기술.md)를 참조하세요.
