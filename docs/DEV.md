# THE FORGE — 개발자 참고

> 이 문서는 THE FORGE 본체에 **기여하거나 디버깅**할 때 보는 코드 레퍼런스입니다. 일반 사용자 가이드는 [`USER_GUIDE.md`](./USER_GUIDE.md), 아키텍처 설계는 [`핵심기술.md`](./핵심기술.md) 참조.

---

## 1. 테스트

```bash
uv run pytest                                 # 전체
uv run pytest tests/test_checkpoint.py -v     # 파일
uv run pytest -k "phase"                      # 키워드
```

`pyproject.toml`에서 `pythonpath = ["src"]`로 src layout이 지정되어 있습니다.

## 2. 린트 · 포맷

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

`scaffold/settings.json`의 `PostToolUse` 훅이 프로젝트에 `pyproject.toml`이 있을 때 자동으로 `ruff check --fix --quiet`를 실행합니다.

## 3. `.venv` 재생성

```bash
uv sync --reinstall
```

손상된 가상환경 초기화용.

## 4. 재배포 (코드 수정 후 글로벌 `forge` CLI 갱신)

**한 줄 기본**:

```bash
python scripts/deploy.py
```

내부적으로 다음을 순서대로 자동 처리:
1. `uv tool install --force --refresh-package the-forge .` (uv build cache 강제 무효화)
2. 프로젝트 `.venv`에 `pip install -e .` (pip 없으면 자동으로 폴백)
3. uv tool 글로벌(`~/AppData/Roaming/uv/tools/the-forge/...`) + 프로젝트 `.venv` 두 곳 모두 `src/forge`와 sha256 비교
4. 불일치/누락 발견 시 수동 복사 폴백
5. `forge --help` smoke test

### 상황별 옵션

| 상황 | 명령 |
|---|---|
| **평소 재배포** | `python scripts/deploy.py` |
| **검증만**, 아무것도 안 고침 | `python scripts/deploy.py --check-only` |
| uv tool **글로벌만** | `python scripts/deploy.py --targets tool` |
| 프로젝트 **`.venv`만** | `python scripts/deploy.py --targets venv` |
| install 건너뛰고 **폴백 복사만** | `python scripts/deploy.py --skip-install` |
| smoke test 건너뛰기 (forge.exe 실행 중 등) | `python scripts/deploy.py --skip-smoke` |

### 왜 deploy 스크립트가 필요한가 (silent skip 함정)

`uv tool install --force .` 만으로는 **반영 안 됨**. uv가 `the-forge==2.3.4` (version 키)로 directory source build cache를 hit하여 옛 wheel을 그대로 재설치한다. verbose log에:

```
DEBUG Directory source requirement already cached: the-forge==2.3.4
Installed 1 package in 63ms
```

만 떠 있으면 캐시 hit (= src 변경분 미반영). 정상이면:

```
Building the-forge @ file:///C:/1.Project/THE_FORGE
   Built the-forge @ file:///C:/1.Project/THE_FORGE
Installed 1 package in 77ms
```

`--force`는 site-packages 비우기 + 재설치이지 **재빌드는 아님**. `--refresh-package the-forge`가 build cache를 강제 무효화한다.

### 수동 폴백 한 줄 (deploy.py를 못 쓰는 환경)

```bash
uv tool install --force --refresh-package the-forge .
```

여전히 의심되면 sha256 비교:

```bash
md5sum src/forge/notifier/slack/adapter.py
md5sum "$USERPROFILE/AppData/Roaming/uv/tools/the-forge/Lib/site-packages/forge/notifier/slack/adapter.py"
```

다르면 [scripts/deploy.py](../scripts/deploy.py) 의 `sync_target()` 로직대로 src/forge → site-packages 통째로 복사.

## 5. 기여 시 문서 역할 분담

- **`README.md`** — 프로젝트 소개·아키텍처·마케팅.
- **`docs/USER_GUIDE.md`** — 온보딩·실행·트러블슈팅 (사용자 관점).
- **`docs/DEV.md`** (이 문서) — 테스트·린트·코드 레퍼런스 (기여자 관점).
- **`docs/핵심기술.md`** — 내부 설계 심화.

---

## 6. 코드 레퍼런스 — USER_GUIDE의 각 항목이 어디서 구현되는가

사용자 가이드에서 제거한 파일:라인 참조를 여기 모아둡니다. 실제 동작을 검증하거나 수정할 때 참고하세요.

### 6.1 CLI 진입점

| 주제 | 위치 |
|---|---|
| `forge` 명령 엔트리 | `pyproject.toml [project.scripts]` → `forge.cli:app` |
| Windows UTF-8 강제 | `src/forge/cli.py:20-25` — `stream.reconfigure(encoding="utf-8")` |
| `forge status` 출력 | `src/forge/cli.py:244-271` |
| `forge journal` 옵션 검증 | `src/forge/cli.py:126-128` (세 옵션 중 하나만 허용) |
| `forge journal` 알림 송신 | `src/forge/cli.py:159-173` |
| `scaffold/` 자동 탐색 | `src/forge/cli.py` `_scaffold_dir()` |

### 6.2 `forge init` 구현

| 주제 | 위치 |
|---|---|
| scaffold 복사 | `src/forge/cli.py` `_copy_scaffold` |
| `.claude/settings.json` 병합 | `src/forge/cli.py` `_merge_claude_settings` |
| `.env` / `pyproject.toml` append | `src/forge/cli.py` `_ensure_env_and_pyproject` (라인 ~574) |
| `.gitignore` append | `src/forge/cli.py` `_ensure_gitignore` |
| 프로젝트명 추론 | `src/forge/autoinfer.py` `infer_project_name()` |
| registry 관리 | `~/.forge/registry.json` |

### 6.3 설정 로딩

| 주제 | 위치 |
|---|---|
| `ForgeConfig` 필드 정의 | `src/forge/config.py:21-70` |
| env_file 우선순위 | `src/forge/config.py:24` — `env_file=(global, project)` 튜플에서 뒤쪽이 우선 |
| `telegram_enabled` 조건 | `src/forge/config.py:73-74` |
| `slack_enabled` 조건 | `src/forge/config.py:77-78` |
| 빈 문자열 무시 | `src/forge/config.py:148` |
| `ProjectPaths` 정의 | `src/forge/config.py:154-206` |

### 6.4 오케스트레이터 / 체크포인트

| 주제 | 위치 |
|---|---|
| `Phase` IntEnum 정의 | `src/forge/checkpoint.py:13-23` — `NONE(0)` → `PLANNING(1)` → `PLANNING_DONE(2)` → `CONTRACT(3)` → `CONTRACT_DONE(4)` → `GENERATING(5)` → `GENERATING_DONE(6)` → `EVALUATING(7)` → `EVALUATING_DONE(8)` |
| stdin 감지 (Windows) | `src/forge/orchestrator.py:30-48` — `msvcrt.kbhit` 분기 |
| 시그널 파일 폴링 | `src/forge/orchestrator.py:60-76` (2초 주기) |
| stdin → resume 변환 | `src/forge/orchestrator.py:74-75, 101-102` |
| `--plan` 기존 spec 보호 | `src/forge/orchestrator.py:366-371` |
| `--from` Phase 재설정 | `src/forge/orchestrator.py:376-379` |
| plan-review 상태별 버튼 | `src/forge/orchestrator.py:420-432` |
| `/resume` 차단 로직 (NEEDS_REVISION) | `src/forge/orchestrator.py:439-440` |
| 안전장치 3종 | `src/forge/orchestrator.py:454-467` |
| Generator 재진입 프롬프트 | `src/forge/orchestrator.py:502-512` |
| Generator 크래시 시 체크포인트 | `src/forge/orchestrator.py:496-497` |
| `claude` PATH 탐색 폴백 | `src/forge/orchestrator.py:501, 530-532` |
| Evaluator try/except | `src/forge/orchestrator.py:550-551` |

### 6.5 Notifier

| 주제 | 위치 |
|---|---|
| Telegram 명령 파싱 | `src/forge/notifier/telegram/receiver.py:76-95` |
| Telegram 파일 업로드 처리 | `src/forge/notifier/telegram/receiver.py:97-132` |
| Slack 명령 파싱 | `src/forge/notifier/slack/adapter.py:60-75` |
| Slack → Telegram 폴백 import | `src/forge/notifier/slack/adapter.py:100` |

### 6.6 비용/관측

| 주제 | 위치 |
|---|---|
| `SprintTracer` no-op 조건 | `src/forge/cost_tracker.py` — 키가 비어있으면 조용히 no-op |
| cost log append | 같은 파일 |

### 6.7 휠 빌드

| 주제 | 위치 |
|---|---|
| `scaffold/` 휠 포함 설정 | `pyproject.toml [tool.hatch.build.targets.wheel.force-include] "scaffold" = "forge/scaffold"` |
| 전역 tool 설치 위치 | `~/.local/share/uv/tools/the-forge/` (격리 venv), bin 링크 `~/.local/bin/forge` (Windows: `%USERPROFILE%\.local\bin\forge.exe`) |

---

## 7. Phase 전이 단조성

`should_run(target) = current_phase <= target`.

체크포인트는 각 Phase **시작 직전 + 종료 직후** 두 번 저장됩니다. 즉 크래시 후 복구는 "마지막 저장된 Phase"부터 이어가되, `should_run` 조건이 단조 증가하므로 같은 Phase를 두 번 돌아도 안전합니다.

## 8. Slack Socket Mode 초기화

v2.3부터 lazy init이 적용되어 있습니다. `forge run` 시작 시 바로 WebSocket을 열지 않고, 첫 알림 송신 시점에 연결합니다. `forge-status` 같은 Slash Command는 **forge 프로세스가 떠 있어야만** 응답 가능 — 미실행 상태에서는 "앱이 반응하지 않아..." 에러가 정상 동작입니다.

## 9. `claude -p` 토큰 파싱

Generator subprocess의 stdout에서 다음 정규식으로 토큰을 추출:

```
Tokens: input N / output M / cache K
```

매칭된 값이 Langfuse span 속성 및 `harness-cost-log.txt`에 부착됩니다.
