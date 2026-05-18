# Mode D: Spec 수정

조건: orchestrator가 사용자 수정 지시와 함께 spec.md 수정 요청.

## 절차

1. **artifacts/spec.md** + **artifacts/plan-review.md** Read
2. **artifacts/spec.md를 Edit 도구로 직접 수정**:
   - 이 모드에서만 spec.md 직접 편집 허용 (Mode B 에서는 금지)
   - 기존 구조·용어 최대한 유지, 사용자 지정 부분만 국소 교체
3. 관련 artifacts/specs/*.md 추가 보강 (덮어쓰기 X, 추가만)
4. **artifacts/plan-review.md** 갱신:
   - 맨 위에 `## 수정 이력 — {timestamp}` 섹션 추가 (사용자 지시 + 변경 요약)
   - 종합 판정 라인(READY/NEEDS_REVISION) 상황 맞게 재기록

## 회피 패턴 차단

stream-json 양방향 모드에서 LLM이 "수정 검토했지만 변경 안 함" 같이 텍스트로만 답하고 Edit 호출 안 하는 패턴 관찰됨. **반드시 Edit 도구 호출 후 종료**. 호출 안 하면 orchestrator가 spec.md mtime 변화 감지 못해 "수정 회피" 경고 발사.

## 절대 규칙

- artifacts/ 바깥 파일 수정 금지
- 사용자 지시 외 자체 추가 수정 금지 (지시 범위 안 국소 교체만)
