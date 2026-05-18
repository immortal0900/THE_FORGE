---
name: forge-gen-decision-log
description: "forge generator의 artifacts/decisions/decision-NNN.md 작성 형식. 스펙 모순·트레이드오프 결정 기록. generator agent가 결정 발생 시 호출."
---

# Decision 기록 (decisions/*.md)

## 언제 작성하나

- 스펙(spec.md/specs/*/sprint-contract.md) 사이에 모순 발견
- 구현 도중 axiom 충돌 또는 트레이드오프 결정
- ASK_USER로 묻기엔 작지만 사후 검토 가치가 있는 분기

작은 명명 선택, 라이브러리 호출 형식, 변수명 같은 사소한 결정은 **기록 금지** (노이즈).

## 파일 위치

`artifacts/decisions/decision-NNN.md` — NNN은 0부터 자동 증분. 기존 `ls artifacts/decisions/` 로 다음 번호 결정.

## 형식

```markdown
# Decision NNN — <한 줄 결정 제목>

## 상황
- 1-3 문장. 어떤 분기에서 무엇이 모순 또는 양립 불가였는지

## 고려안
- A: <한 줄 + 영향 한 줄>
- B: <한 줄 + 영향 한 줄>
- (C: ...)

## 선택: <A/B/C>
- 이유: 1-2 문장. 어떤 axiom 또는 sprint 범위 제약 때문에 이걸 골랐는지

## 영향
- 변경된 파일 / 새 가정 / 다음 스프린트 영향 (한 줄씩)

## 사후 검토 포인트
- 한 줄. "이 결정이 틀렸다면 어디서 먼저 깨질 것인가"
```

## 작성 후 흐름

1. decision-NNN.md Write
2. 합리적 기본값으로 구현 즉시 진행 (사용자 응답 대기 X)
3. 세션 종료 시 progress-log.md에 "결정: decision-NNN 참조" 한 줄 추가

## 금지

- 결정 없이 진행 후 사후에 끼워넣기
- 결정 본문에 "고민 중", "검토 필요" 같은 모호 표현
- 사용자에게 결정 떠넘기는 톤 ("어느 게 좋을지 모르겠다") — 본인이 합리적 기본값을 골라야 한다
