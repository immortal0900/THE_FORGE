# Mode B: spec.md 리뷰

조건: artifacts/spec.md 존재. 사용자가 기획서 직접 제공한 케이스도 포함.

## 절차

1. spec.md + specs/* 정독
2. 검토 관점: 완성도 / 기술적 일관성 / 실현 가능성 / 도메인 스펙 일치
3. **artifacts/specs/ 비어있거나 누락된 도메인 스펙 발견 시 생성**:
   - 템플릿 있으면: INDEX.md 매칭 → 선정 템플릿으로 specs/*.md Write
   - 템플릿 없으면 fallback: 도메인 키워드 기반 파일명 자유 결정. 최소 섹션 (목적/컴포넌트/제약/검증 기준)
   - 기존 specs/*.md 덮어쓰기 금지 — 새 것만 추가
   - **0건 생성 후 Mode B 종료 금지**
4. **artifacts/plan-review.md** Write — 다음 형식:

```markdown
# Plan Review

## 종합 판정
**READY** 또는 **NEEDS_REVISION**

## 생성된 도메인 스펙
- (있으면 목록)

## Axiom Verdicts
(essence_axioms 있으면 .claude/agent-knowledge/_shared/verdict-table.md 참조해서 표 작성)

## 누락/모호 항목
...

## 권장 수정 사항
(NEEDS_REVISION인 경우)
```

## 절대 규칙

- spec.md 직접 수정 금지 (Mode B 에서는 X. Mode D 에서만 Edit 허용)
- artifacts/ 바깥 파일 수정 금지
- Write/Edit 도구는 artifacts/ 경로에만
