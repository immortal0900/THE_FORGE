# Mode C: Sprint Contract 생성

조건: orchestrator가 sprint-contract 생성 요청.

## 절차

1. spec.md / specs/* / progress-log.md / sprint-*-done.md Read
2. specs/ 비어있으면 .claude/agent-knowledge/planner/mode-review.md 참조해서 specs/*.md 먼저 채움 (sprint-contract 검증 기준 구체화 위해)
3. templates/sprint-contract-template.md 형식 따름
4. **artifacts/sprint-contract.md** Write — 다음 frontmatter **필수** (없으면 orchestrator가 프로젝트 완료 판단 불가):

```yaml
---
sprint_number: 3
has_next_sprint: true
estimated_remaining_sprints: 2
next_sprint_preview: |
  다음 스프린트 예정 작업 (2-5줄)
---
```

5. 본문에 P0 3-5개 작성. 각 P0에 검증 기준 + 참조 specs/*.md 명시 (예: `참조: specs/langgraph-state.md §2`)
6. **병렬/직렬 판단**: .claude/agent-knowledge/_shared/parallel-judgment.md 참조. 결정 이유를 sprint-contract.md 본문 §갈림길 결정에 한 문단 명시
7. 분할 결정이면 본문에 `## Parallel Task Graph (YAML)` 섹션 추가 (parallel-judgment.md의 YAML 형식 참조)
8. **artifacts/sprint-capabilities.md** Write: .claude/agent-knowledge/_shared/capability-yaml.md 참조. 분기 1개 = capabilities[] 1개 매핑

## 절대 규칙

- Write 안 하고 텍스트만 답하고 종료 금지 — sprint-contract.md 미생성 시 orchestrator가 generator 시작 차단
- artifacts/ 바깥 수정 금지
