# THE FORGE

**범용 하네스 오케스트레이터 v2.1** — Planner → Generator → Evaluator 3-에이전트 사이클.

## 설치

```bash
git clone https://github.com/HWAIN/THE_FORGE.git
cd THE_FORGE
uv sync
uv tool install .
```

## 빠른 시작 (v2.0 부록 B)

1. THE_FORGE 설치: `uv tool install .`
2. (선택) Langfuse: `uv tool install ".[langfuse]"`
3. Telegram Bot 생성 (@BotFather → /newbot)
4. TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID 확인
5. 프로젝트에서 초기화: `cd my-project && forge init`
6. `forge.toml`에 토큰 + 예산 설정 입력
7. 하네스 실행: `forge run "요청 내용"`
8. Telegram에서 spec.md 파일 수신 확인
9. 첫 스프린트 완료 후 progress-log.md 확인
10. harness-cost-log.txt에서 시간 확인
11. Langfuse 대시보드에서 trace 확인 (설정한 경우)
12. THE_FORGE에 개선사항 반영
13. 5개 프로젝트 후 가정 재검증

## CLI

| 명령 | 용도 |
|------|------|
| `forge run "요청"` | 메인 하네스 사이클 |
| `forge run --plan plan.md` | 기획서 파일로 시작 |
| `forge eval` | Evaluator만 재실행 |
| `forge status` | 현재 체크포인트 출력 |
| `forge init` | 프로젝트 부트스트랩 |
| `forge init --force` | 기존 파일 백업 후 덮어쓰기 |
| `forge notify TYPE MSG [FILE]` | Hooks용 알림 |
| `forge version` | 버전 출력 |

## 테스트

```bash
uv run pytest
```

## 라이선스

MIT
