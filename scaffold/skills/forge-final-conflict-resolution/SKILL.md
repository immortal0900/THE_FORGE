---
name: forge-final-conflict-resolution
description: "forge finalizer의 머지 충돌 해결 절차. 단순/의미적 충돌 분류 + decision-NNN.md 양식. finalizer agent가 머지 충돌 발생 시 호출."
---

# 충돌 해결 절차

## Step 1: 수집

`git status`로 unmerged 파일 목록 X 수집. 각 unmerged 파일을 Read로 읽는다. 파일 안에 `<<<<<<<`, `=======`, `>>>>>>>` 마커가 있다.

## Step 2: 분류 (자문하라)

**단순 충돌**: 두 분기가 같은 줄을 단지 다른 형식으로 표현 (공백 차이, import 순서, 같은 의미의 변수명 차이). 한쪽 채택해도 다른 쪽 의도가 보존됨.

**의미적 충돌**: 두 분기가 같은 자리에서 **서로 양립할 수 없는 결정**을 내림. 한쪽을 택하면 다른 쪽 의도가 사라짐.

## Step 3-A: 단순 충돌이면

- Edit으로 충돌 마커 (`<<<<<<<` ~ `>>>>>>>`) **범위 안만** 정리. 그 외 행 절대 손대지 마라
- 양쪽 변경을 모두 살려야 하면 두 변경을 순서대로 배치
- 한쪽만 살려야 하면 한쪽 채택, 다른 쪽 영역과 마커 모두 삭제
- `artifacts/.merge-decisions/decision-{NNN}.md` 작성 (양식 아래)

## Step 3-B: 의미적 충돌이면

- `git merge --abort` 실행
- `artifacts/.merge-decisions/decision-{NNN}.md`에 "풀 수 없음 - 사용자 결정 필요" + 양쪽 분기의 선택 인용
- 즉시 종료. orchestrator가 사용자 게이트 발사

## Step 4: 마무리

모든 충돌 파일 정리 후:
- `git add` 각 충돌 파일
- `git commit -m "forge: finalizer-merge sprint-{N}-branch-{K} (resolved {len} conflicts)"`
- 다음 분기로 진행

## decision-NNN.md 양식 (의무)

매 충돌 해결마다 한 개. NNN은 0부터 자동 증분.

```markdown
# Decision NNN - sprint {N} merge conflict in `<파일>`

## 채택
- 분기 `branch-K`의 변경 채택.
- 이유: 한 줄

## 버린 안
- 분기 `branch-J`의 변경.
- 무엇이었는가: 한 줄
- 왜 안 맞는가: 한 줄

## 판정 종류
- [x] 단순 충돌 (공백/import/형식)
- [ ] 의미적 부분 충돌 (양립 가능)
- [ ] 의미적 양립 불가 (이건 abort + escalate 해야 함)

## 사후 검토 포인트
- 한 줄
```

**판정 종류 "양립 불가" 체크면 너는 abort + escalate 했어야 한다.** 양립 불가 체크하면서 머지 진행한 것은 자기합리화 (self-rationalization).
