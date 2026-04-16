---
purpose: 템플릿 인덱스 — 토큰 효율적 선택적 참조용
---

# Templates

Planner가 spec.md/sprint-contract.md 작성 시, 관련 템플릿만 선택적으로 참조하라.
전체 템플릿을 읽지 말고 필요한 것만 `cat templates/<파일명>`으로 확인하라.

| 파일 | 도메인 | 사용 시점 |
|------|--------|----------|
| sprint-contract-template.md | Core | 매 스프린트 (frontmatter 필수) |
| generator-guide.md | Core | Generator 상세 가이드 참조 |
| langgraph-agent.md | LangGraph | LangGraph State/Node/Edge 프로젝트 |
| db-setup.md | Database | DB 테이블/인덱스/벡터검색 프로젝트 |
| deepeval-setup.md | DeepEval | LLM 평가 메트릭 프로젝트 |
| langfuse-setup.md | Langfuse | 관측성(Observability) 프로젝트 |
