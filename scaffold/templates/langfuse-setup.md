# Langfuse 추적 스펙 템플릿

(레이어 2 — 프로젝트 코드 내부 LLM 호출 추적)

## 추적 계층
- Trace: 사용자 요청 단위
- Span: 각 LLM 호출 / 에이전트 단계
- session_id: 사용자/세션 식별자

## 메타데이터 표준
- model, input_tokens, output_tokens, latency_ms
- tool_calls (있으면)
- user_feedback (있으면)

## 삽입 위치
- 모든 LLM 래퍼 함수에 `@observe` 또는 컨텍스트 매니저
- 배치 플러시 보장 (앱 종료 전)

## 검증
- 샘플 요청 실행 후 Langfuse 대시보드에 trace가 보이는가
- Evaluator가 "삽입 누락된 LLM 호출"을 지적할 수 있는가
