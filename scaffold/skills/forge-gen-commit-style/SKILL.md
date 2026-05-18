---
name: forge-gen-commit-style
description: "forge generator의 git 커밋 메시지 규칙. 짧은 영어 + feat/fix/refactor 3 prefix만. generator agent가 커밋 직전 호출."
---

# 커밋 규칙 (엄격)

## 형식

- **짧고 직관적인 영어** 한 줄
- 허용 prefix **3가지만**: `feat:`, `fix:`, `refactor:`
- `test:`, `docs:`, `chore:` 등 **금지** (위 3가지로 흡수)
- 한 줄 요약 원칙, 본문은 선택 (1줄 "왜"만)

## 예시

```
feat: add watcher debounce
fix: handle empty vault path
refactor: extract sync_engine
```

## 금지

- `Co-Authored-By: Claude ...` 같은 자동 서명
- heredoc 메시지 (한 줄 -m 만 사용)
- 한국어 커밋 메시지
- prefix 없는 커밋

## prefix 매핑 가이드

| 의도 | prefix |
|---|---|
| 새 기능, 새 모듈, 새 테스트 추가 | `feat:` |
| 버그 수정, 깨진 동작 복구 | `fix:` |
| 동작 동일, 구조/이름/위치 변경 | `refactor:` |

테스트만 추가/문서만 수정/잡일은 가장 가까운 의도로 흡수. 예: 새 테스트 케이스 추가 = `feat:`, 깨진 테스트 수정 = `fix:`, 테스트 헬퍼 재구성 = `refactor:`.
