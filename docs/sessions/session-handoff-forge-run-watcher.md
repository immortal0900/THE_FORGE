# 세션 핸드오프: THE FORGE_TEST forge run watcher

## 첫 메시지로 복사해서 새 Claude Code 세션에 붙여넣기

---

## 너의 책임 (요약)
**C:\1.Project\THE_FORGE_TEST에서 background로 진행 중인 `forge run`을 watch하여 결과(모든 sprint PASS + sprint-N-done.md 아카이브) 완벽까지 진행**.

메인 세션이 evaluator 1차 cold start 자동 재시도 fix를 끝낸 직후 너에게 watch 업무를 위임. 사용자 hook(`/goal`)이 active되어 결과 완벽까지 stop 안 됨.

---

## 사용자 정책 (반드시 지킬 것)

| 정책 | 내용 |
|---|---|
| 사용자 위임 | 게이트 알림은 메인 세션이 직접 결정 (사용자가 슬랙/터미널 직접 안 함). 사용자 합리적 판단으로 진행 |
| 비용 허용 | LLM 호출 비용 신경 안 씀, 결과 완벽 우선 |
| 멈춤 + 수정 + 재실행 정책 | 예상과 다르면 background kill → 코드 수정 → `python scripts/deploy.py` 재배포 → `forge run` 재시작 반복 |
| 라인 번호 표기 | 심볼명 우선 (라인 가변, [parallel-branches-design.md:0번 섹션](docs/parallel-branches-design.md) 정책) |
| 배포 명령 | **반드시 `python scripts/deploy.py`** (uv tool install --force 단독 X, silent skip 함정) |
| 커밋 prefix | feat: / fix: / refactor: 3가지만, 짧은 영어 한 줄, Co-Authored-By 금지 |

---

## 현재 상태 (메인 세션이 너에게 넘기는 시점)

| 항목 | 값 |
|---|---|
| forge run background | 방금 kill됨 (b21ekenzx) — 새로 재시작 필요 |
| 현재 phase | CONTRACT_DONE (sprint-2 FAIL reset, sprint 2 evaluator가 1차 cold start로 죽음) |
| Sprint 1 | ✅ PASS archived (sprint-1-done.md 24574 bytes) |
| Sprint 2 generator | ✅ 잘 만듦 (Langfuse out=41,000) |
| Sprint 2 evaluator | ❌ 1차 cold start exit=1 (Langfuse out=5,022 stdout=N) — fix 적용으로 다음부터 자동 재시도 |
| Sprint 3 | 미시작 |
| 누적 시간 | 53분 |
| slack 채널 | #the_forge_control_center (ID `C0ATR475UT0`) thread root ts=1778989704.807239 |

---

## 메인 세션이 한 코드 수정 (재배포 완료된 상태로 너에게 넘어옴)

### 1. parse_branches import (orchestrator.py:21)
```python
from .contract import BranchSpec, parse_branches
```
방금 fix됐고 deploy.py 통과. 이거 없으면 NameError로 forge가 죽었던 버그.

### 2. 실행 모드 표시 3곳 (cli.py + orchestrator.py)
"branch" 표기가 직렬 task인지 병렬 worktree인지 혼동되어 사용자 가독성 개선:
- `forge status` 출력에 "실행 모드: 단일 직렬 (LLM 세션 1)" row 추가
- sprint 시작 시 console + slack 알림: "Sprint N 실행 모드: ..." 명시
- capability cards 발사 메시지: "실행 모드: 단일 직렬 (실제 LLM 세션 1개)" 미리보기

### 3. **evaluator 1차 cold start 자동 1회 재시도** (orchestrator.py Phase 4 Evaluator 블록)
**이게 가장 중요**. 패턴: evaluator subprocess가 첫 turn에 일찍 죽음(returncode != 0 + 짧은 stdout). claude CLI cold start 추정. sprint 1, 2 모두 동일 발생, 둘 다 2차 시도에서는 PASS. 자동 재시도 로직:

```python
if result.returncode != 0 and len(result.stdout or "") < 1000:
    # cold start 패턴 → 2초 후 1회 재시도
    time.sleep(2)
    result = ev.run_evaluate(config, paths, notifier=notifier)
```

다중 분기 모드(run_evaluators_parallel)는 별건. 지금 stopwatch는 단일 분기라 단일 모드만 fix됨.

이 fix 덕에 너의 watch 부담 ↓: evaluator 1차 cold start 패턴은 자동 회복. 다른 FAIL 패턴이면 그때 분석.

---

## 너의 첫 액션

```bash
cd "C:\1.Project\THE_FORGE_TEST" && forge run 2>&1
```

run_in_background: true 로 실행. background task ID 받아 메모.

checkpoint=CONTRACT_DONE이라 sprint 2 generator+evaluator 단계부터 자동 복구.

---

## watch 루틴 (사이클당)

1. `forge status` 확인 (phase + 누적 시간 + Sprint 1/2/3 archived)
2. background output tail (마지막 30줄)
3. slack 채널 thread reply 보고 새 게이트 알림 있나 (mcp__slack__slack_read_thread, message_ts=1778989704.807239)
4. `artifacts/.capability-drops` 또는 `artifacts/.approval-signal` 필요한 게이트인지 판단

## 게이트 자동 처리 (사용자 위임 정책)

| 게이트 종류 | 트리거 | 자동 처리 |
|---|---|---|
| Capability Cards (sprint 시작 시 N장 발사) | "Branch Capability Card N장 발송 — 사용자 결정 대기" 메시지 출현 | sprint-capabilities.md 본문 검토 → 본질 점수(essence_score_llm/floor) 모두 60+면 keep N개 발사 |
| sprint contract 승인 | detail = "contract generated, awaiting sprint N approval" | sprint-contract.md 본질 부합 빠른 검토 후 .approval-signal=resume |
| sprint PASS 후 다음 sprint 진입 | detail = "evaluation complete" + sprint N 아카이브됨 | .approval-signal=resume |
| sprint FAIL (qa_fail 알림) | detail = "sprint-N FAIL, reset to contract_done" | 우선 .approval-signal=eval로 evaluator 재시도. 2회도 실패면 progress-log + qa-report 분석 후 결정 |
| 멈춤 + 수정 + 재실행 (사용자 정책) | 예상과 다른 결과(LLM이 잘못된 방향, 같은 sprint 3회+ FAIL 등) | TaskStop → 코드 수정 → python scripts/deploy.py → forge run 재시작 |

### Capability Cards 결정 신호 발사 형식
```
printf "keep\tbranch-1\nkeep\tbranch-2\n...\n" > artifacts/.capability-drops
```
N개 모두 keep. drop은 본질 무관 작업이 섞였을 때만.

### Approval 신호 발사 형식
```
printf "resume" > artifacts/.approval-signal     # 일반 승인 / sprint 진입
printf "eval" > artifacts/.approval-signal       # FAIL 후 evaluator만 재시도
printf "stop" > artifacts/.approval-signal       # 중단
printf "skip" > artifacts/.approval-signal       # 결함 채로 다음 sprint
```

### 정지 + 재시작 명령
```bash
# 정지
TaskStop({task_id: "<background_id>"})

# 코드 수정 후 재배포
cd "C:\1.Project\THE_FORGE" && python scripts/deploy.py

# 재시작 (checkpoint 자동 복구)
cd "C:\1.Project\THE_FORGE_TEST" && forge run 2>&1   # background
```

---

## ScheduleWakeup 사용

`/loop` dynamic mode로 self-pacing. 다음 게이트까지 평균 5-25분이라 cache-warm(270s) 또는 1500s fallback 적절. 첫 watch는 270s 추천 (generator 진입 후 모드 표시 등 변화 빠를 시점).

---

## 메인 세션이 미완료로 남긴 후속 commit

작업 끝나면 마지막에 fix들을 git에 반영:

```bash
cd "C:\1.Project\THE_FORGE"
git add src/forge/orchestrator.py src/forge/cli.py
git commit -m "fix: evaluator cold start auto retry + execution mode display"
git push origin main
```

3개 fix 묶음:
- parse_branches import (orchestrator.py:21)
- 실행 모드 표시 (cli.py status + orchestrator.py 2곳)
- evaluator 1차 cold start 자동 1회 재시도 (orchestrator.py Phase 4 단일 모드)

---

## 결과 완벽의 정의

| 조건 | 검증 |
|---|---|
| Sprint 1/2/3 모두 ✅ PASS | `forge status`에 Sprint 1/2/3 archived 표시 |
| sprint-N-done.md 3개 모두 존재 | `ls artifacts/sprint-*-done.md` 3건 |
| qa-report.md 종합 판정 PASS | grep 확인 |
| stopwatch main.py 실행 OK | `python main.py` 빈 창 + 시작/정지/리셋 동작 |
| 60초 정확성 ±0.5초 내 | qa-report sprint 2 검증 항목 |
| Freeze 정책 준수 (sprint 3) | 150분 이후 새 기능 추가 0건 (git log 확인) |

위 6개 모두 충족 시 사용자 hook이 자동 해제(/goal 조건 충족).

---

## 추가 컨텍스트 (참고)

- 메인 plan: [parallel-branches-design.md](docs/parallel-branches-design.md)
- 사용자 메모리: 커밋 메시지 스타일은 한 줄 영어 + feat/fix/refactor 3 prefix
- uv tool install --force 단독은 silent skip 함정 (메모리 [feedback_uv_tool_install_trap.md] 참조)
- 테스트 실행 경로는 `c:\1.Project\THE_FORGE_TEST`, 코드는 `c:\1.Project\THE_FORGE`
- 직전 작업 흔적: feature/parallel-branches → main 머지 + push 완료, parallel-branches 인프라 + Planner Mode E 추가됨
