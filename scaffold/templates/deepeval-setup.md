# DeepEval 평가 스펙 템플릿

## 메트릭
- (예: AnswerRelevancy, Faithfulness, ContextualPrecision)
- 임계값

## 테스트케이스
- 입력 / 기대 출력 / 컨텍스트
- 최소 N개

## 실행
- `deepeval test run tests/eval/`
- CI 연동 여부

## 검증
- 모든 메트릭 임계값 통과
- 실패 케이스 근거 로그 저장
