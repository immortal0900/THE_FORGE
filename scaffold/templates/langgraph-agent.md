# LangGraph Agent 스펙 템플릿

## State 스키마
- TypedDict 또는 Pydantic BaseModel
- 필드: (나열)

## 노드
| 이름 | 입력 | 출력 | 책임 |
|------|------|------|------|
| analyze | state | state.analysis | ... |

## 엣지
- START → analyze
- analyze → (조건) → {action_a, action_b}
- * → END

## 검증
- 각 노드 단위 테스트 (입력→출력 단언)
- 전체 그래프 시나리오 테스트 2개 이상
- Langfuse trace 삽입 확인
