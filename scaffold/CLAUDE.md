# 프로젝트 하네스 규칙

이 프로젝트는 THE FORGE 하네스(Planner → Generator → Evaluator)로 운영된다.
각 에이전트의 상세 규칙은 `.claude/agents/*.md`에 있다. 이 파일은 **모든 에이전트 공통 컨텍스트**다.

## 파일 레이아웃

```
artifacts/
├── spec.md                 # 프로젝트 기획 (Planner)
├── specs/*.md              # 도메인 상세 스펙 (Planner)
├── plan-review.md          # 기획 리뷰 (Planner)
├── sprint-contract.md      # 현재 스프린트 범위 (Planner)
├── progress-log.md         # 작업 기록 (Generator, 최상단에 누적)
├── qa-report.md            # QA 결과 (Evaluator)
├── decisions/*.md          # 의사결정 기록 (Generator)
├── sprint-N-done.md        # PASS 된 스프린트 아카이브
└── harness-cost-log.txt    # 시간/토큰 로그

templates/                  # 도메인 스펙 템플릿 (Planner 참조)
```

## 커밋 규칙 (모든 에이전트 공통)

- **짧고 직관적인 영어**로 작성
- **허용 prefix 3가지만**: `feat:`, `fix:`, `refactor:`
- 예: `feat: add watcher debounce`, `fix: handle empty vault path`
- 한 줄 요약 원칙
- `Co-Authored-By` 자동 서명 금지 (settings에서도 차단)

## 에이전트별 상세

- `.claude/agents/planner.md` — 기획/리뷰/Sprint Contract
- `.claude/agents/generator.md` — 구현/커밋/progress-log
- `.claude/agents/evaluator.md` — QA/qa-report
