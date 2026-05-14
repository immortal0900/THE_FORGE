# THE FORGE: 사람의 판단을 빠르게 도와주는 하네스

## 한마디 요약

LLM(에이전트)은 5배 빨라졌는데, 너(사용자)가 결과 보고 결정하는 시간은 그대로다. 이 plan은 그 결정 시간을 짧게 만드는 것이 목표다. 결정 횟수를 줄이는 게 아니라, **한 번의 결정이 1-10초 안에 끝나도록 판단에 필요한 맥락은 풍부하게, 무관한 디테일은 collapsible 뒤로** 보낸다.

---

## 무엇은 그대로고 무엇이 바뀌나 (먼저 명확히)

| 영역 | 현재 | 변경 후 |
|---|---|---|
| 에이전트끼리 주고받는 산출물 파일 (spec.md, sprint-contract.md, qa-report.md, progress-log.md) | 그대로 | **구조 그대로**. 단 spec.md 위에 `essence_axioms` 블록 추가, qa-report.md에 `Axiom Verdicts` 표 추가 (둘 다 메타데이터 보강) |
| 단계 흐름 (planner → generator → evaluator) | 그대로 | **그대로**. 추가로 LLM이 도중에 사용자에게 ASK_USER 옵션 카드를 던질 수 있음 |
| 사용자가 외울 슬래시 명령 (`/resume` `/skip` `/eval` `/stop` `/revise`) | 5개 | **5개 그대로**. 새 명령 X |
| 사용자에게 가는 Slack 메시지 | 점수 + 토큰/시간 + 첨부 | **카드 형태로 시각화** (Verdict Card, 옵션 카드). 데이터는 같은 산출물 파일에서 추출 |
| 사용자가 LLM에 의견 던지는 방법 | (없음) Verdict가 와야만 `/revise` 가능 | Slack 스레드 안에 평문 메시지 → LLM stdin에 push (큰 그림 3) |
| 자식 프로세스 호출 방식 | `subprocess.run` 한 번에 batch | 영속 `Popen` + 양방향 stream-json (토대 1) |

**한마디**: 산출물 파일과 흐름은 같다. 그 위에 (a) 본질 메타데이터, (b) 시각 카드, (c) 양방향 의사소통이 얹힌다.

---

## 비유로 먼저 잡기

| | 지금 (THE FORGE v2.3) | 목표 |
|---|---|---|
| 어떤 가게? | 우체국(post office) | 코너 편의점(corner store) |
| 흐름 | 너가 요청서 제출 → 며칠 후 두꺼운 책 한 권 도착 → 너가 25분 읽고 도장 찍음 | 너가 들어가서 "A 콜라요 B 사이다요?" → 너 "B" → 1초 끝 |
| 사용자 부담 | 결과물을 통째로 검토 (점수 환산, 본질 부합 여부, 근거 추적, 다음 결정 선택을 매번 스스로 재구성) | 점원(LLM)이 미리 정리해놓은 카드 보고 "맞다/아니다"만 |

**한마디**: 점원이 묻는 횟수가 늘어도, 매 질문이 1초면 전체는 더 빠르다.

---

## 무엇이 문제인가 (수치로)

매 결정 1건당 사용자 점유 시간(현재 추정):

| 결정 지점 | 매번 사용자가 하는 인지 작업 | 시간/건 |
|---|---|---|
| 기획 수락 (spec.md 통과) | spec.md 전문 읽고 누락 탐지 | 15-25분 |
| 첫 sprint contract 수락 | contract와 spec 대조 | 10-15분 |
| QA PASS 수락 | 4축 점수 + 항목별 근거 훑기 | 8-15분 |
| QA FAIL 처리 | 근거 읽고 /resume vs /skip vs /eval 판단 | 12-20분 |
| 코딩 도중 잘못된 분기 | 사후 발견, 되돌리기 | 30분+ (있을 때) |

**목표**: 한 결정당 30초-2분 (15-25분 → 30초).

---

## 어떻게 고치나 (큰 그림 3개)

### 큰 그림 1. LLM이 평소에 짧게 묻는다

**지금**: LLM이 모호한 분기를 다 *추측*으로 채워 spec.md / 코드 일괄 작성. 너는 *사후*에 발견해서 `/revise`로 되돌림.

**변경**: LLM이 모호 분기를 만나면 그 자리에서 짧은 옵션 카드를 너에게 던짐. 너는 "A냐 B냐" 8초 답. LLM은 처음부터 정답.

**옵션 카드는 이렇게 생긴다** (Slack):

```
📍 결정 요청  |  axiom a2 (1초 내 처리)와 연관

상황: generator가 파일 업로드 핸들러를 만들고 있다.
     큰 파일을 어떻게 처리할지 두 갈래에서 멈췄다.

────────────────────────────────────────────
🚀 A  스트리밍 처리
   동작: 파일을 청크로 잘라 받으면서 처리
   실측 예상: 100MB → 0.8초 (axiom a2 충족)
   부수 효과: 부분 실패 시 복구 코드 +50줄 필요
   유사 사례: src/import.py:88 가 같은 패턴 사용

🛡️ B  안전한 일괄 로드
   동작: 파일 전체를 메모리에 올린 후 한 번에 처리
   실측 예상: 100MB → 5.4초 (axiom a2 위반)
   장점: 에러 시 통째 롤백, 코드 단순
   유사 사례: src/legacy_loader.py:42 (단 작은 파일 전용)
────────────────────────────────────────────

💡 LLM 추천: 🚀 A
   왜: axiom a2(1초 내 처리)가 critical weight.
       복구 코드 +50줄은 이번 sprint 범위 내(`progress-log.md`
       현재 1200줄 / 한계 2000줄).
       사용자 30%가 100MB 이상 사용하므로 B는 본질 위반 빈발.

────────────────────────────────────────────
[A 누름]   [B 누름]   [더 보기 ▾]

[더 보기 ▾]: 다른 후보 옵션(C: 청크 단위 검증 후 일괄, D: 외부 라이브러리),
            각 옵션의 코드 변경 미리보기 diff
```

---

### 카드 디자인 = LLM 출력 명세 (구현 시 참조)

위 두 카드(Verdict Card, 옵션 카드)의 본문 줄 하나하나가 evaluator/planner가 산출물 파일(qa-report.md, planning-dialog.md)에 *반드시 채워야 할 컬럼* 이다.

**Verdict Card → evaluator의 Axiom Verdict 표 컬럼 (qa-report.md)**:
| 컬럼 | 예시 | 출처 |
|---|---|---|
| `id` | a2 | spec.md의 essence_axioms |
| `statement` (본질) | "1초 내 처리" | spec.md |
| `verdict` | VERIFIED / PARTIAL / MISSING | evaluator 판정 |
| `confidence` (0-100) | 60 | evaluator 판정 |
| `inspection_method` (검사 방법) | "10MB / 100MB 입력 처리 시간 측정" | evaluator가 어떻게 평가했는지 |
| `measurements` (실측) | "10MB → 0.3초 ✓ / 100MB → 측정 안 함" | 실제 측정값 |
| `evidence` (근거) | "tests/perf_test.py:34 의 100MB 케이스가 skip" | 파일:라인 또는 명령 결과 |
| `counter_hypothesis` (반박) | "선형이면 100MB → 3초로 axiom 위반" / "없음" | 명시. "없음"이면 "없음" 적기 (silent 금지) |
| `user_impact` (사용자 영향) | "현재 사용자 30%가 100MB 이상 사용 (artifacts/user-data-sizes.md)" | spec.md 또는 artifacts에서 인용 |
| `recommend_action` | `accept` / `partial_regen(a2)` / `reject(reason)` | evaluator 결정 |

**옵션 카드 → planner/generator의 ASK_USER JSON 스키마**:
```json
{
  "type": "ask_user",
  "qid": "<uuid>",
  "axiom_link": "a2",                          // 어느 axiom과 연관
  "situation": "<상황 1문장>",                  // generator가 어디서 멈췄나
  "options": [
    {
      "id": "A",
      "label": "<5단어 이내>",
      "icon": "🚀",
      "mechanism": "<동작 한 줄>",
      "expected_metric": "<수치 결과 1구>",
      "side_effect": "<부수 효과 1구>",
      "similar_case": "<유사 사례 파일:라인 또는 null>"
    },
    { "id": "B", ... }
  ],
  "recommend": "A",
  "recommend_basis": "<axiom 부합 + sprint 범위 + 사용자 영향, 3-5줄>"
}
```

이 스키마는 [scaffold/agents/planner.md](c:/1.Project/THE_FORGE/scaffold/agents/planner.md), [scaffold/agents/generator.md](c:/1.Project/THE_FORGE/scaffold/agents/generator.md), [scaffold/agents/evaluator.md](c:/1.Project/THE_FORGE/scaffold/agents/evaluator.md) 각 system prompt에 의무 출력 명세로 박는다. 모호 표현("이 정도면 괜찮다", "대체로", "아마")이 들어가면 신뢰도 강제 ≤50.

---

### 큰 그림 2. LLM이 결과를 "본질 부합도" 카드로 미리 정리

**지금**: 결과물(qa-report.md)에 4축 점수 + 파일:라인. 너가 "이게 우리가 만들고 싶었던 거랑 부합하나?"를 매번 직접 재구성.

**변경**: spec.md 맨 위에 본질(axiom, 본질적 약속 3-7개)을 미리 박아둔다. 결과 평가 시 LLM이 axiom마다 verdict(통과/부분/실패) + 신뢰도 + 근거 + 반박가설 + 추천 액션을 채운다. 너는 카드 한 장 1-3초.

**Verdict Card는 이렇게 생긴다** (Slack, 사용자가 *논리적 판단* 할 수 있게 맥락 충분히):

```
📋 Sprint 3 평가  |  본질 부합도 ✅✅⚠️✅  3/4 axioms

────────────────────────────────────────────
✅ a1  오프라인 동작                    95%
   본질: 비행기/지하철에서 노트앱이 동작
   검사 방법: 네트워크 차단 후 핵심 기능 12개 실행
   실측: 12/12 통과
   근거: src/net.py:42 외부 호출 0건
   반박: 없음 (가능 시나리오 모두 커버)

⚠️ a2  1초 내 처리                      60%
   본질: 사용자가 "느리다" 인식 직전 임계
   검사 방법: 10MB / 100MB 입력 처리 시간 측정
   실측: 10MB → 0.3초 ✓  /  100MB → 측정 안 함
   근거: tests/perf_test.py:34 의 100MB 케이스가 skip 상태
   반박: 알고리즘이 입력 크기 선형이면 100MB → 3초 (axiom 위반)
   사용자 영향: 현재 사용자 30%가 100MB 이상 파일 사용
                (출처: artifacts/user-data-sizes.md)

✅ a3  진단 로그                        98%
   본질: 사용자가 문제 신고 시 무엇이 일어났는지 추적
   검사 방법: 의도적 에러 5종 발생 후 로그 검사
   실측: 5/5 모두 에러 경로 + stack + context 기록
   근거: src/log.py:120, tests/log_test.py 11/11 통과
   반박: 없음

✅ a4  단일 파일 export                  92%
   본질: 외부 의존 없이 한 파일로 공유
   검사 방법: export 후 압축 파일 개수 + 외부 링크 검사
   실측: 1개 zip, 외부 링크 0개
   근거: tests/export_test.py 7/7 통과
   반박: 없음
────────────────────────────────────────────

💡 LLM 추천: a2만 부분 재실행
   왜: a2의 100MB 측정만 누락. generator가 그 부분만 보강하면
       신뢰도 60→90 회복 예상. 사용자 30% 인구에 닿는 본질이라
       완전 수락 X.
💰 +12분 (이번 sprint 추정)
   완전 거절 시: +28분, 그냥 수락 시: 0분이지만 a2 본질 위반 위험.

────────────────────────────────────────────
[수락]   [부분 재실행 a2]   [거절+지시]

[원본 qa-report.md 펼치기 ▾]  ← 점수 환산 과정, 다른 옵션 비용, 전체 보고서
```

**사용자가 카드 위에서 무엇을 보고 판단하나** (논리적 판단의 흐름):

1. 상단 시각 바(`✅✅⚠️✅ 3/4`)로 전체 분포를 1초 안에 파악
2. ⚠️ 가 있는 axiom(여기선 a2)에 집중. 다른 ✅들은 스캔만
3. a2의 **본질**(왜 중요한가) + **검사 방법**(어떻게 평가했나) + **실측**(무엇이 누락인가) + **반박**(실제 위협) + **사용자 영향**(우리 사용자 몇 %가 닿나)을 본문에서 8-10초 안에 읽음
4. LLM 추천의 **왜**(논리적 근거) 한 단락 확인
5. 동의하면 [부분 재실행 a2] 1탭. 동의 안 하면 [거절+지시]로 모달 입력.

**collapsible 뒤로 가는 것** (1차 판단에 불필요한 디테일):
- 원본 qa-report.md 전체 텍스트
- 점수 환산 공식
- 다른 옵션의 추정 비용 상세
- 다른 sprint의 누적 메트릭

**카드 길이**: axiom 4개 기준 약 28줄 (Slack 한 화면). axiom 7개면 약 45줄 (스크롤 1회).

**버튼은 새 슬래시 명령을 추가하지 않는다.** 기존 5개(`/resume` `/skip` `/eval` `/stop` `/revise`)에 매핑:

| 버튼 | 내부 신호 | 함께 보내는 텍스트 |
|---|---|---|
| [수락] | `/resume` | (없음) |
| [부분 재실행 a2] | `/revise` | "axiom a2만 부분 재실행. 다른 항목 유지." |
| [거절] | `/revise` | (사용자 입력 modal에서 받음, 기존 동작 그대로) |

---

### 큰 그림 3. 사용자가 LLM에게 의견 던지는 채널 (Slack 스레드 = 프로젝트 단위)

**상황**: LLM 동작 중에 사용자가 "지금 너무 길게 가지마" 같은 의견을 던질 수 있어야 한다. 멀티 프로젝트 동시 실행 시 메시지가 어느 프로젝트로 갈지 라우팅 필요.

**구현 핵심**:
- THE FORGE 시작 시 Slack에 새 스레드를 연다(메시지 첫 글: `🧵 [<project_name>] sprint N 시작`).
- 스레드 ID(`thread_ts`)를 [src/forge/checkpoint.py](c:/1.Project/THE_FORGE/src/forge/checkpoint.py) 또는 별도 `.forge/slack_thread.txt`에 저장.
- 이후 모든 Slack 알림(Verdict Card, 옵션 카드, heartbeat)을 그 thread에 reply.
- Slack adapter는 thread 안의 사용자 평문 메시지를 listen → 그 메시지를 해당 프로젝트의 `whisper_queue`에 push → ForgeAgentRunner가 다음 LLM turn 전에 stdin에 `[사용자 의견] ...` user message로 push.
- 슬래시 명령(`/resume` `/skip` `/eval` `/stop` `/revise`)도 thread 안에서 사용 시 그 프로젝트로 라우팅.
- 동시 N 프로젝트 실행: 각 프로젝트가 자기 스레드만 본다. 사용자는 어느 스레드에 답할지로 라우팅 결정 (외울 prefix·명령 X).
- 단일 프로젝트일 때도 동일 메커니즘 (스레드 1개).

LLM 측 처리 규칙은 의견의 성격별로:
1. 의견이 진행과 일치 → "반영했다" 한 줄 답 + 즉시 적용
2. 의견이 axiom과 충돌 → 옵션 카드(큰 그림 1)로 1회 확인
3. 의견이 spec/contract 변경 요구 → "이건 정식 `/revise`로 주세요" 응답 (sprint 범위 보호)
4. 의견이 모호 → "자세히" 답

---

## 기술 토대 (실제로 무엇을 만드나)

### 토대 1. claude CLI를 영속 Popen 세션으로 띄우기

**세션 수명 정의 (1 Popen = 1 session)**:

streaming이 되면 기존 Mode A/B/D 분기가 한 세션에 흡수된다. Mode D(revise) 폐기.

| 단위 | 1 Popen 세션 | 세션 안에서 일어나는 일 |
|---|---|---|
| planner-spec (프로젝트 시작 1회) | 1 (필요 시 `--resume <uuid>`로 재개) | essence_axioms 읽기 → spec.md 작성 → ASK_USER/`/revise`/사용자 의견 받아 같은 컨텍스트에서 수정 → plan-review.md → 최종 spec.md 확정. **기존 Mode A + B + D 흡수** |
| planner-contract (sprint마다) | 1 (필요 시 `--resume <uuid>` 재개) | sprint-contract.md 작성. **ASK_USER 가능** (sprint 범위 결정: 어느 axiom 우선? 어느 항목 이번 sprint 포함?). Mode C 유지 |
| generator (sprint마다) | 1 | 코딩 + ASK_USER N회 + whisper M회 → sprint 완성 |
| evaluator (sprint마다) | 1 | qa-report.md 작성. **ASK_USER 정책상 금지** (관대함은 버그를 통과시킨다, 보고만) |

**sprint별 세션 수**: sprint 1 = 4 세션 (spec, contract, gen, eval). sprint N (N≥2) = 3 세션 (contract, gen, eval).

**도구 호출마다 새 세션 X** (컨텍스트 재주입 50K 토큰 낭비). **전체 sprint 공유 X** (에이전트마다 별도 system prompt).

**사용자 응답 대기 동안 세션 처리**: 사용자가 24시간 응답 안 할 수도 있으므로 무한정 Popen 살려두지 않음. 세션 일시 종료 + `session_id` UUID를 [checkpoint.py](c:/1.Project/THE_FORGE/src/forge/checkpoint.py)에 저장 → 응답 도착 시 `--resume <uuid>`로 같은 컨텍스트 재개. (claude CLI가 자체 컨텍스트 캐시 유지)

**실행할 일**:
1. 신규 [src/forge/agents/cli_session.py](c:/1.Project/THE_FORGE/src/forge/agents/cli_session.py): `asyncio.create_subprocess_exec`로 claude CLI 영속 띄우는 클래스.
2. flag 묶음 (공식, 출처: https://code.claude.com/docs/en/sdk-headless):
   ```bash
   claude -p --input-format stream-json --output-format stream-json --verbose --permission-mode dontAsk
   ```
3. 신규 [src/forge/agents/runner.py](c:/1.Project/THE_FORGE/src/forge/agents/runner.py): 세션 위에 ASK_USER/whisper 라우팅 wrapper.
4. 기존 `subprocess.run` 호출 마이그레이션:
   - [planner.py:13-39](c:/1.Project/THE_FORGE/src/forge/agents/planner.py#L13-L39)
   - [evaluator.py:13-39](c:/1.Project/THE_FORGE/src/forge/agents/evaluator.py#L13-L39)
   - [orchestrator.py:725-735](c:/1.Project/THE_FORGE/src/forge/orchestrator.py#L725-L735) (generator)
5. 세션 UUID를 [checkpoint.py](c:/1.Project/THE_FORGE/src/forge/checkpoint.py)에 저장 → 크래시 후 `--resume <uuid>` 재개.

**참고 prior art (패턴만)**:
- `unixfox/opencode-claude-code-plugin` (실제 `--input-format/--output-format stream-json` 양방향 사례)
- `anthropics/claude-code-sdk-python/_internal/transport/subprocess_cli.py` (단방향 reference, 안전장치 참고: 1MB JSON 버퍼, 30초 stderr 타임아웃)

---

### 토대 2. 자식 env에서 API 키 제거 (인증 자체는 그대로)

**실행할 일 한 줄**: 토대 1의 Popen 호출 시 자식 env에서 `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` 제거.

```python
env = {k: v for k, v in os.environ.items()
       if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
```

**왜 이것만 하나**: claude CLI가 OS 키체인에서 OAuth 토큰을 자동 조회 → 현재 동작 그대로. 단 자식 env에 API 키가 살아있으면 키체인보다 우선 → 사용량 과금 (issue #37686, $1,800 사고). CI/서버용 `CLAUDE_CODE_OAUTH_TOKEN`은 선택.

---

### 토대 3. 본질을 미리 박는다 (essence_axioms) — **사용자가 외부에서 제공**

**핵심 분업** (사용자 idea의 0→1 vs 1→N 분리):
- 본질을 *정의*하는 일 = 인간 사용자. LLM이 만들지 않음.
- 본질을 *읽고 구체화 / 검증*하는 일 = LLM (planner, generator, evaluator).

THE FORGE가 본질을 *자동 생성*하지 않는다는 결정의 의미: planner는 spec.md를 만들 때 essence_axioms를 *임의 작성*하지 않고, 사용자가 외부에서 제공한 본질을 *읽어서 spec.md에 인용*만 한다.

**사용자가 본질을 제공하는 두 경로**:

1. **docs/ 폴더에 기획서 파일** (정적 제공):
   - 예: `docs/essence.md`, `docs/<project>-vision.md`, `docs/<project>-pillars.md` 등.
   - 파일 형식 자유 (마크다운, YAML 모두 가능). THE FORGE는 frontmatter 또는 명시 섹션을 파싱.
   - THE FORGE 시작 시 setup_wizard가 사용자에게 "본질 파일 경로?"를 묻고 `.forge/config.yaml`의 `essence_source_path` 에 저장.

2. **본질 정의 skill** (동적 제공):
   - 사용자가 미리 만들어둔(또는 만들) "본질 정의" 전용 Skill을 호출.
   - 그 Skill이 사용자와 대화하며 본질 목록을 산출 → 파일이나 텍스트로 THE FORGE에 전달.
   - THE FORGE는 그 출력을 `artifacts/essence-axioms.yaml`에 캐시.

**THE FORGE가 읽어서 spec.md에 인용하는 형태** (planner가 *복사*만 함, 출처 명시):

```yaml
---
essence_source: docs/essence.md          # 또는 skill:essence-definer (출처 추적용)
essence_imported_at: 2026-05-14T...
essence_axioms:
  - id: a1
    statement: "오프라인에서 동작"
    rationale: "사용자가 비행기/지하철에서 사용"
    falsifiable_by: "네트워크 차단 후 핵심 기능 동작 확인"
    weight: critical
  - id: a2
    ...
---
```

**규칙 (본질은 선택, 강제 X)**:
- **본질 파일이 있으면 → 참고**해서 spec.md에 인용, Verdict Card도 axiom 단위로 렌더.
- **본질 파일이 없으면 → 사용자 요청 그대로 진행** (기존 동작 그대로 폴백). spec.md에 essence_axioms 블록 없을 수도 있고, evaluator는 axiom verdict 표 대신 기존 4축 점수만 출력.
- planner는 essence_axioms를 *읽기 전용*. 자체 추가 / 수정 / 추출 금지 (있을 때).
- 사용자가 docs/essence.md를 도중에 수정하면 다음 sprint 시작 시 THE FORGE가 mtime 검사 후 spec.md 재인용. 변경 시 사용자에게 한 줄 알림(Slack).
- 3-7개 권장. 그 이상은 사용자가 본질을 너무 잘게 쪼갠 것.
- `falsifiable_by`(어떻게 깨졌다고 입증할 수 있나)가 비면 LLM이 evaluator 시 "검증 불가"로 처리 (사용자가 보강할 수 있게 알림).
- `weight: critical` axiom이 부분 통과(PARTIAL)면 sprint 통과 못 함.

**Evaluator는 axioms가 spec.md에 인용돼 있으면 verdict 표를 채운다** (Verdict Card 데이터 원천). 없으면 기존 4축 점수만.

**한마디**: 가게 출입문에 "우리는 무엇을 한다"를 종이에 박아두는 일은 사장(사용자)이 한다. 점원(LLM)은 그 종이를 매일 출근하면서 읽고, 손님 응대가 그 종이와 부합하는지 매번 확인한다.

---

## 확정된 결정

- **멀티 프로젝트 의견 채널**: 옵션 B (Slack 스레드 = 프로젝트 단위). 위 "큰 그림 3" 참조.
- **질문 한도**: agent별 `max_questions` 기본값 10000 (사실상 무제한). config로 조정.
- **인증**: 현재 동작 그대로(키체인 자동 사용). 유일한 추가 작업은 자식 env에서 `ANTHROPIC_API_KEY` 제거 (청구 사고 방지). CI/서버용 `CLAUDE_CODE_OAUTH_TOKEN`은 선택.
- **신호**: 기존 5개 (`/resume` `/skip` `/eval` `/stop` `/revise`) 유지, 새 슬래시 명령 추가 X.
- **자동 채택 타임아웃**: 폐기. 무기한 백그라운드 대기 + 6h heartbeat.

---

## 변경되는 파일 (요약)

| 파일 | 무엇이 바뀌나 |
|---|---|
| 신규 [src/forge/agents/cli_session.py](c:/1.Project/THE_FORGE/src/forge/agents/cli_session.py) | `claude` CLI를 영속 Popen으로 띄우는 클래스 (토대 1) |
| 신규 [src/forge/agents/runner.py](c:/1.Project/THE_FORGE/src/forge/agents/runner.py) | 세션 위에 ASK_USER, whisper 라우팅 얹는 wrapper |
| 신규 [src/forge/judgment.py](c:/1.Project/THE_FORGE/src/forge/judgment.py) | 사용자 제공 essence 파일(docs/) 또는 skill 출력 파싱 + spec.md 인용 + Verdict Card 빌더 + 비용 시뮬레이션 (큰 그림 2) |
| [src/forge/agents/planner.py](c:/1.Project/THE_FORGE/src/forge/agents/planner.py) | `subprocess.run` → 영속 Popen 호출 마이그레이션. **Mode D(`run_revise`, 88-140줄) 폐기** (streaming에서 Mode A 세션에 흡수). Mode B(`run_review`)도 자연스럽게 같은 세션 흡수. Mode C(contract)만 별도 함수 유지 |
| [src/forge/agents/evaluator.py](c:/1.Project/THE_FORGE/src/forge/agents/evaluator.py) | `subprocess.run` → 영속 Popen 마이그레이션 (planner와 동일 패턴). ASK_USER 정책 금지 유지 (system prompt에 명시) |
| [src/forge/orchestrator.py](c:/1.Project/THE_FORGE/src/forge/orchestrator.py) | async 진입점, Verdict Card 버튼→기존 5개 신호 매핑, 무기한 대기 |
| [src/forge/notifier/slack/adapter.py](c:/1.Project/THE_FORGE/src/forge/notifier/slack/adapter.py) | Verdict Card + 옵션 카드 빌더, 평문 메시지 라우팅 (큰 그림 3) |
| [src/forge/cli.py](c:/1.Project/THE_FORGE/src/forge/cli.py) | ASK_USER stdin 입력 처리 + 백그라운드 whisper 입력 스레드 |
| [src/forge/config.py](c:/1.Project/THE_FORGE/src/forge/config.py) | `auto_approve`, `axiom_*_threshold`, `max_questions`(기본 10000, agent별), `essence_source_path`, `slack_thread_id_path` (`.forge/slack_thread.txt`) |
| [src/forge/cost_tracker.py](c:/1.Project/THE_FORGE/src/forge/cost_tracker.py) | `estimate_action_cost(action)`, `waiting_for_user_seconds` 분리 |
| [src/forge/checkpoint.py](c:/1.Project/THE_FORGE/src/forge/checkpoint.py) | CLI 세션 UUID 저장/복원 (`--resume <uuid>`용) |
| [src/forge/setup_wizard.py](c:/1.Project/THE_FORGE/src/forge/setup_wizard.py) | auto_approve 첫 설정 + **본질 파일 경로(`essence_source_path`) 또는 본질 정의 skill 호출 안내** + (선택) CI 환경이면 `CLAUDE_CODE_OAUTH_TOKEN` 안내 |
| [scaffold/agents/planner.md](c:/1.Project/THE_FORGE/scaffold/agents/planner.md) | essence_axioms **읽기 전용 인용**(자체 생성 금지) + ASK_USER 프로토콜 |
| [scaffold/agents/generator.md](c:/1.Project/THE_FORGE/scaffold/agents/generator.md) | ASK_USER + whisper 처리 규칙 |
| [scaffold/agents/evaluator.md](c:/1.Project/THE_FORGE/scaffold/agents/evaluator.md) | Axiom Verdict 표 의무화 (id/statement/verdict/confidence/inspection_method/measurements/evidence/counter_hypothesis/user_impact/recommend_action 10컬럼) + 모호 표현 금지(신뢰도≤50 강제) |
| 신규 [artifacts/decisions/decisions.jsonl](c:/1.Project/THE_FORGE/artifacts/decisions/decisions.jsonl) | ASK_USER 답변 학습 로그 |
| 신규 [artifacts/decisions/whispers.jsonl](c:/1.Project/THE_FORGE/artifacts/decisions/whispers.jsonl) | 사용자 평문 의견 로그 |

---

## 비범위 (의도적으로 안 하는 것)

- oh-my-claudecode 영감 (3x3 verifier 매트릭스, hook 슬롯, skill auto-inject 이원화) → 다음 사이클
- **본질(axiom) 자동 생성 / planner가 essence 작성**: 사용자가 docs/ 또는 본질 정의 skill로 외부 제공. THE FORGE는 읽기 전용 인용만.
- 자동 채택 타임아웃 → 폐기, 무기한 백그라운드 대기 (사용자 요청)
- 새 슬래시 명령 추가 → 기존 5개로 충분
- hunk 단위 diff 수락 UI → Slack 한계, axiom 단위 그룹핑으로 우회
- claude-agent-sdk-python 사용 → Max Plan 인증 제약, 자체 Popen만

---

## 작업 순서

| 단계 | 내용 | 의존 |
|---|---|---|
| 1 | 토대 1 (영속 Popen 세션) + 회귀 테스트 통과 | - |
| 2 | 토대 2 (자식 env에서 ANTHROPIC_API_KEY 제거) | 1 |
| 3 | 토대 3 (사용자 제공 essence 파일 파싱 + spec.md 인용 + Axiom Verdict 출력) | 1 |
| 4 | 큰 그림 3 일부 (Slack 스레드 = 프로젝트 단위 자동 생성, 모든 알림이 스레드에 reply) | 1 |
| 5 | 큰 그림 2 (Verdict Card Slack 렌더 + 스레드에 reply) | 3, 4 |
| 6 | Verdict Card 버튼 → 기존 5개 신호 매핑 | 5 |
| 7 | 큰 그림 1 (ASK_USER 프로토콜, planner-spec / planner-contract부터) | 1 |
| 8 | 무기한 백그라운드 대기 + 6h heartbeat | 7 |
| 9 | 큰 그림 1 generator 적용 (코딩 중 분기) | 7 |
| 10 | 큰 그림 3 나머지 (스레드 평문 메시지 listen + whisper push) | 4 |
| 11 | 카테고리별 auto-approve (어떤 결정이 시끄러운지 dogfood 후 결정) | - |
| 12 | 1주 dogfood → 결정 시간 측정 회고 | 모두 |

각 단계 독립 커밋. 1줄 영어, `feat:` `fix:` `refactor:` prefix만.

---

## 검증 (성공이라 말할 수 있는 조건)

`artifacts/decisions/decisions.jsonl`을 1주 dogfood 후 분석. 한 결정 1건당 사용자 응답 시간(`elapsed_seconds`) 중앙값:

| 결정 종류 | 현재 | 목표 |
|---|---|---|
| ASK_USER 옵션 카드 응답 (추천 동의 시) | (없음) | ≤ 45초 |
| ASK_USER 옵션 카드 응답 (다르게 판단 시) | (없음) | ≤ 2분 |
| Verdict Card PASS 수락 | 8-15분 | ≤ 1분 |
| Verdict Card 부분 재실행 결정 | (없음) | ≤ 2분 |
| Verdict Card FAIL 처리 (지시 입력 포함) | 12-20분 | ≤ 3분 |
| 사용자 의견 평문 던지기 (Slack 스레드) | (없음) | ≤ 30초 |

추가 검증:
1. **회귀**: 기존 5개 신호(`/resume` `/skip` `/eval` `/stop` `/revise`)가 모두 동작.
2. **API 키 누출 방지**: `ANTHROPIC_API_KEY`를 일부러 부모 env에 넣고 실행 → 자식 프로세스 env에는 들어가지 않음을 명시적으로 확인 (issue #37686 방지). OAuth는 키체인이 자동 처리하므로 별도 검증 불필요.
3. **axiom verdict 품질**: "구조 의심" 시나리오 빈도 < 30%. 넘으면 evaluator.md 보강 우선.
4. **무기한 대기**: 응답 안 하고 6시간 경과 → heartbeat 알림 → 24시간 후 응답 → 정상 진행.
5. **whisper(또는 사용자가 고른 옵션)**: 사용자가 평문 의견 → 다음 turn에 LLM이 반영.

---

