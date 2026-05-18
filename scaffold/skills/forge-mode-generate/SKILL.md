---
name: forge-mode-generate
description: "Planner Mode A. forge에서 spec.md 없을 때 사용자 평문 요청을 spec.md + specs/*.md로 변환하는 절차. planner agent가 호출."
---

# Mode A: spec.md 생성

조건: artifacts/spec.md가 없거나 사용자가 명시적 생성 요청.

## 절차

1. 사용자 요청 분석 + templates/INDEX.md 읽고 매칭 템플릿 선정
2. 선정 템플릿만 본문 읽기 (관련 없는 건 X)
3. **artifacts/spec.md** Write — 다음 구조:
   - 1. 프로젝트 개요 (목적 3-5문장, 핵심 사용자 시나리오)
   - 2. 기술 스택 (프레임워크 수준, 선택 이유 한 줄)
   - 3. 기능 목록 (P0/P1/P2, User Story 형식)
   - 4. 스프린트 분해 (3-5개/스프린트, 의존성 순서, S/M/L)
   - 5. 디자인 원칙
   - 6. 성공 기준 (검증 가능)
   - 7. 제약 조건
4. **artifacts/specs/*.md** 도메인별 상세 스펙 Write — 매칭 템플릿의 frontmatter `output` 필드 경로로
5. 템플릿 없을 시 fallback: 도메인 키워드로 파일명 자유 결정 (예: specs/auth-flow.md). 최소 섹션: 목적·주요 컴포넌트·제약·검증 가능 성공 기준
6. **specs/*.md 0건 생성 후 종료 금지** — Generator/Evaluator 참조 자산 필수

## 본질(essence_axioms) 처리

prompt 상단에 본질 inline 주입돼 있으면 spec.md 본문에 **원본 그대로** 반영. 표현·의미 재해석 금지. 자체 axiom 추가 금지. spec.md frontmatter는 orchestrator가 박으므로 건드리지 마라.

본질 없으면 사용자 요청만 보고 작성. 강제 X.

## 절대 규칙

- 코드 작성 금지
- artifacts/ 바깥 파일 수정 금지
- 세부 구현(라이브러리 버전, 함수명) 지정 금지
