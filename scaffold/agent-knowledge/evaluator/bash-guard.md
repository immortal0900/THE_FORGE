# Bash 실행 가드 (세션 hang 방지)

## 절대 금지

**GUI mainloop을 직접 실행하지 마라.** `python <name>.py`, `node <name>.js` 등이 Tkinter/Qt/Electron/wx/PySide/curses 같은 mainloop를 호출하면 Bash tool이 영원히 기다리다 evaluator 세션이 죽는다.

## 사전 확인 방법

실행 전 `grep` 으로 차단 호출 패턴 점검:

```bash
grep -E "mainloop|app\.exec|run\(host=|listen\(|input\(\)" <파일>
```

매치되면 그 파일은 **직접 실행 금지**.

## 대체 검증 방법

- `python -c "import <module>"` — import 성공만 확인
- `python -c "from <module> import <Class>; <Class>()"` — 인스턴스화만 확인
- `python <test_file>.py` — 단위 테스트는 OK
- 코드 정적 분석 + grep + AST parse 로 대체

## sprint-contract에 "GUI 시연" 항목이 있어도

sprint-contract.md 가 "수동 시연"·"GUI 시연" 항목을 명시했어도, **실제 GUI 실행은 사용자 몫**이다. evaluator는 코드/로그/정적 분석 결과만 보고하라.

## Bash timeout

모든 Bash 호출에 `timeout=30000` (30초) 이하 명시. 무한 대기 가능성 있는 명령(server, watcher, REPL)은 호출 자체 금지.

## 위반 시 영향

evaluator 세션이 timeout 없이 hang → max-turns 도달 → qa-report.md 미완료 → 스프린트 평가 실패. (2026-05-17 검증된 fix)
