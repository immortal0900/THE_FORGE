# 세션 분할 운영 가이드 (멀티 세션 구현 전략)

## 무엇인가
THE FORGE의 병렬 분기 + Finalizer 아키텍처(`../parallel-branches-design.md`)를 3개 세션에 분할 구현하는 운영 문서.

## 분할 구조 (L 레이어별)

```
세션 A (기반)               세션 B (엔진)              세션 C (Finalizer/UX)
──────────────────         ──────────────────         ──────────────────
단계 0: 설정 변수            단계 4: contract.py        단계 7: finalizer.py + md
단계 1: BranchState         단계 5: run_agents_parallel 단계 8: FAIL 격상 + 부분 머지
단계 2: worktree.py         단계 6: orchestrator 분기  단계 9: whisper 라우팅 + prefix
단계 3: paths.branch_paths   + evaluator branch_id 주입
   │
   ▼ (A 완료 후 B,C 동시)
시간 ─────────────────────────────────────────────────────────────────►
```

## 각 세션 진입 방법
새 Claude Code 세션 3개를 열고 각각에 다음 프롬프트를 그대로 붙여넣는다.

| 세션 | 프롬프트 파일 | 시작 시점 |
|---|---|---|
| A | `./session-A.md` | 즉시 시작 가능 |
| B | `./session-B.md` | 세션 A 완료 후 |
| C | `./session-C.md` | 세션 A 완료 후 |

## git 브랜치 토폴로지

```
main
 └─ feature/parallel-branches      ← 통합 base 브랜치 (오케스트레이터가 머지)
     ├─ feature/parallel-foundation (세션 A)
     ├─ feature/parallel-engine    (세션 B, A 완료 후 분기)
     └─ feature/parallel-finalizer (세션 C, A 완료 후 분기)
```

## 통합 책임 (오케스트레이터 = main 세션)
1. 세션 A 산출물 검토 → 회귀 1번 통과 확인 → `feature/parallel-branches`에 머지
2. 세션 B/C 동시 시작 (이미 A 위에서 분기되어 있음)
3. 세션 B 산출물 검토 → 회귀 1번 + 골든 2번 통과 확인
4. 세션 C 산출물 검토 → 회귀 1번 + 검증 3/4/4-2/4-3/4.8 통과 확인
5. B와 C를 `feature/parallel-branches`에 차례 머지 (orchestrator.py 충돌 가능성 → 사용자 결정)
6. 전체 검증 시나리오 1-8 재실행
7. `docs/USER_GUIDE.md` 신규 환경변수 문서화
8. `sprint-1-done.md` 형식의 통합 보고서 작성 (사용자 사후 검토용)

## 운영 주의

### 세션 간 통신은 git만
Slack/메모리 공유 없음. 각 세션이 자기 branch에 commit + push. 오케스트레이터가 fetch + merge로 통합.

### 자기 영역 외 수정 금지
각 세션 프롬프트의 "금지" 항목 위반 시 통합 단계에서 revert.

### orchestrator.py 충돌 회피
세션 B와 C가 같은 파일을 건드린다. **함수 단위 분리**가 핵심:
- 세션 B: `_handle_parallel_sprint_generation(...)` 작성
- 세션 C: `_handle_parallel_sprint_finalization(...)`, `_handle_parallel_sprint_escalation(...)` 작성

이렇게 분리하면 같은 파일이라도 git merge 충돌 0건.

## 라인 번호 표기 규칙 (세션 공통)
메인 plan의 0번 섹션 그대로:
- **심볼명 우선**, 라인 번호는 가변 보조
- 정확 위치는 `Grep "심볼명"`으로 재확인
- 라인 번호가 plan과 다르면 **심볼명을 정답으로 본다**
