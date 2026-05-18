---
name: forge-eval-playwright
description: "forge evaluator의 Playwright/브라우저 도구 사용 규칙. 웹 UI(HTML 슬라이드·웹앱·대시보드) 평가 시 호출. evaluator agent가 spec/contract가 브라우저 확인을 요구할 때 호출."
---

# Playwright/브라우저 도구 사용 규칙

## 사용 조건

다음 중 하나가 충족될 때만 사용:
- spec.md/sprint-contract.md가 브라우저 확인을 명시적으로 요구
- 평가 대상이 웹 UI (HTML 슬라이드, 웹앱, 대시보드)

조건 안 맞으면 도구 호출 금지. (코드/로그 정적 분석으로 충분)

## playwright.config.* 가 있으면

오케스트레이터가 `npx playwright test` 자동 실행 후 결과를 qa-report.md 말미에 붙인다. evaluator는 추가로 mcp 도구를 손으로 호출하지 않아도 된다 (필요 시 보강만).

## 사용 가능 도구

- `mcp__playwright__browser_navigate` — URL 이동
- `mcp__playwright__browser_snapshot` — 접근성 트리 캡처
- `mcp__playwright__browser_take_screenshot` — 시각 캡처
- `mcp__playwright__browser_click` — 인터랙션
- `mcp__playwright__browser_console_messages` — 콘솔 에러 수집
- `mcp__playwright__browser_evaluate` — JS 실행
- `mcp__playwright__browser_wait_for` — 대기
- `mcp__playwright__browser_network_requests` — 네트워크 호출 수집

## 핵심 규칙 (몰아쓰기 금지)

스크린샷/탐색을 **한 건 찍을 때마다 qa-report.md를 Edit으로 업데이트**. "수집 몰아서 마지막에 Write" 금지.

이유: evaluator 세션이 max-turns 도달로 끊겨도 부분 결과가 qa-report.md에 남는다.

## 보고 형식

qa-report.md의 "상세 평가" 섹션에 다음 식으로 기록:

```markdown
### 웹 UI 검증 (slide 3)
- 페이지 로드: OK
- 콘솔 에러: 0건
- 시각 확인: <screenshot 파일 경로 또는 한 줄 묘사>
- 인터랙션 (버튼 클릭 → 모달): PASS
- 발견 이슈: 모달 닫기 X 버튼 hit area 너무 작음 (~12px)
```

스크린샷 파일은 `artifacts/screenshots/` 경로에 두고 보고서에서 링크.
