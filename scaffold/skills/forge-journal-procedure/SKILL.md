---
name: forge-journal-procedure
description: "forge journal의 docs/journal.md 작성 절차. 자료 수집 → 엔트리 포맷 → append 규칙. journal agent가 호출."
---

# Journal 작성 절차

## Step 1: 자료 수집 (턴 절약)

**반드시 읽을 것 (범위 관련):**
- `artifacts/decisions/decision-*.md` (ls 후 관련 범위만)
- `artifacts/progress-log.md` (최근 섹션만)

**범위에 맞을 때만:**
- `artifacts/sprint-N-done.md` — 특정 스프린트 지정 시 그것만
- `artifacts/qa-report.md` — 자동/최신 범위일 때만

**선택적 (필요 시):**
- `git log --since=<cutoff> --oneline --no-merges`
- `artifacts/harness-cost-log.txt` — 이상치 의심 시

읽기 후 **바로 `docs/journal.md` Write**로. 추가 탐색은 필요할 때만.

## Step 2: 중복 제거 확인

작성 전 `docs/journal.md` 상단 Read:
- 기존 엔트리의 날짜/범위와 겹침 → **기존 최상단 엔트리 업데이트** (새 정보만 병합)
- 완전히 새 범위면 → **위쪽에 새 엔트리 append** (기존 엔트리 절대 삭제/수정 X)
- 동일 에러/결정이 이전에 기재됐으면 반복 X. 필요 시 "연장/후속" 맥락으로 한 줄

파일 없으면 새로 생성 (제목 `# 프로젝트 저널` 한 줄만).

## Step 3: 엔트리 포맷

### 헤더

```
## YYYY-MM-DD — <프로젝트명> — <범위>
```

범위 표기:
- 단일 스프린트: `Sprint 3`
- 연속: `Sprint 1~4` (물결표)
- 불연속: `Sprint 1, 3, 5` (쉼표)
- 날짜 이후: `since 2026-04-15`
- 자동(마지막 엔트리 이후): 생략 — `## 2026-04-17 — obsidian_sync`

### 한 줄 요약 (헤더 직후, 빈 줄 띄고)

전체 맥락을 **1-3 문장**. 기술 스택 결론, 완료한 기둥, 미처리 이월 포함. **프로젝트 모르는 독자도 이해**하게 용어 풀어쓰기 (`forge-journal-writing-style` 참조).

### 본문 구조

```markdown
### Errors & Root Causes
- **증상 한 줄**
  - 원인: 한두 문장 근본 원인
  - 해결: [파일:라인](../src/x.py#L42) — commit `abc1234`
  - 교훈: 재발 방지 포인트

### Decisions
- **결정 제목** (근거: [decision-003.md](../artifacts/decisions/decision-003.md))
  - 고려안: A / B / C
  - 선택: C — 이유 한 줄
  - 영향: [변경된 파일](../src/y.py#L10)

### Tips & Gotchas
- **함정 한 줄 (일반화)** — [관련 코드](../src/z.py#L10) 참고

### Carry-overs (이월, 있을 때만)
- **이월 건** — 미처리 이유, 다음 스프린트 체크 포인트

### Performance Notes (이상치 있을 때만)
- **비용 이상치**: <한 줄>
```

## 길이 가이드

- 한 엔트리: **마크다운 렌더 2-3 스크린** (200-600줄)
- 재료 부족하면 억지로 늘리지 마라. 짧은 엔트리에 가치 있는 한 줄이 더 낫다
- 사소한 것은 생략

## 세션 종료

- `docs/journal.md` 저장만 하고 종료
- 다른 artifact, 소스 코드 수정 금지
- git commit 금지 (사용자 결정)
