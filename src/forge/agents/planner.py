"""Planner 에이전트 — 영속 Popen 세션 호출 wrapper.

토대 1 (docs/plan-judgment-velocity.md): subprocess.run batch → 영속 Popen +
stream-json 양방향. 함수 시그니처는 그대로 두어 호출처(orchestrator.py)와의
인터페이스 호환을 유지한다. 결과 객체는 RunResult (subprocess.CompletedProcess
호환: returncode / stdout / stderr).

토대 3 (docs/plan-judgment-velocity.md): 사용자가 docs/essence.md 등으로 본질을
제공한 경우, planner prompt에 inline으로 inject한다. planner는 본질을 *원본
그대로 spec.md 본문에 반영*만 한다 (자체 추가/수정 금지). frontmatter는
orchestrator가 자동 박는다.

NOTE (큰 그림 1 단계에서 처리 예정):
    - Mode A(run_generate) ↔ Mode B(run_review) ↔ Mode D(run_revise) 는
      streaming 세션이 살아있는 한 *같은 세션*에 흡수되어야 한다.
      이번 토대 1에서는 마이그레이션만, 흡수는 큰 그림 1에서.
"""

from __future__ import annotations

from typing import Optional

from ..config import ForgeConfig, ProjectPaths
from ..judgment import EssenceSource
from .runner import AskUserCallback, RunResult, run_agent_sync


_VERDICT_TABLE_GUIDE = (
    "### Axiom Verdicts 표 형식 (10컬럼 고정, Verdict Card 렌더링 대상)\n"
    "**핵심 규칙**: 각 셀은 '파일:라인 가서 보세요' 같은 위치 지시가 아니라 "
    "**카드만 읽고도 사용자가 8-10초 안에 판단**할 수 있도록 *내용 자체*를 한 문장씩 친절히 풀어 적는다. "
    "위치만 적으면 사용자가 파일을 열어 직접 찾아 읽어야 해서 카드의 존재 이유가 사라진다.\n\n"
    "**각 컬럼이 답해야 할 질문 (이것을 셀에 그대로 답한다)**:\n"
    "- `inspection_method` ← \"이 본질이 충족됐는지 어떻게 따져봤나?\" → spec의 어느 기준/규칙을 *측정 잣대*로 잡았는지 한 문장.\n"
    "  - 좋은 예: \"spec이 '60초 동시 측정 시 ±0.5초 이내' 라는 정량 임계를 명시했는지 본문을 점검했다\"\n"
    "  - 나쁜 예: \"spec.md §3 참조\", \"본문 확인\"\n"
    "- `measurements` ← \"실제로 spec/코드에 무엇이 적혀 있나?\" → *구체 내용 요약*. 위치 X, 내용 O.\n"
    "  - 좋은 예: \"start_time/accumulated 누적 + 100ms tick 명시, 정확성 60초 ±0.3초 목표가 박혀 있음\"\n"
    "  - 나쁜 예: \"spec.md §3에 적혀 있음\", \"OK\"\n"
    "- `evidence` ← \"가장 강한 증거 한 줄은?\" → spec/코드의 *해당 문구를 따옴표로 직접 인용*. 위치는 인용 뒤에 괄호로.\n"
    "  - 좋은 예: '\"now - start_time + accumulated 로 시각차분 누적\" (spec.md Sprint 1 §3)'\n"
    "  - 나쁜 예: \"spec.md Sprint 1\", \"본문에 있음\"\n"
    "- `counter_hypothesis` ← \"그래도 깨질 수 있는 시나리오는?\" → 1줄 반박 또는 \"없음\" 명시.\n"
    "  - 좋은 예: \"기간이 길면 부동소수점 누적 오차로 ±0.5초 초과 가능. 다만 stopwatch는 길어야 수 분이라 영향 적음\"\n"
    "  - 나쁜 예: 빈 셀, \"검토 필요\"\n"
    "- `user_impact` ← \"이 본질이 깨지면 사용자에게 무슨 일이 일어나나?\" → 결과 묘사.\n"
    "  - 좋은 예: \"채점 시 표시 시간이 실제와 어긋나 60초 정확성 점수 0\"\n"
    "  - 나쁜 예: \"성능 영향\", \"점수 깎임\"\n\n"
    "**작성 톤**: 사용자에게 말하듯 친절한 한국어 한 문장씩. 약어/내부 용어/줄임표 자제. "
    "위치 인용은 evidence 셀에서만, 그것도 *해당 문구를 따옴표로 함께 적는다*. "
    "위치만 적고 내용 없는 셀은 *값이 비어있는 것으로 간주*된다.\n\n"
    "**올바른 행 예시 (a2 = 시각차분 측정)**:\n"
    "| a2 | 시각차분으로 정확하게 시간 측정 | VERIFIED | 90 | spec이 '60초 동시 측정 시 ±0.5초' 라는 정량 임계를 명시했는지 점검 | start_time/accumulated 변수 + time.time() 차분 누적 + 100ms tick + 정확성 60초 ±0.3초 목표 모두 포함 | \"now - start_time + accumulated 로 시각차분 누적\" (spec.md Sprint 1 §3) | 부동소수점 누적 오차는 수 분 수준 stopwatch에서는 무시 가능 | 깨지면 채점 시 60초 정확성 점수 0 | accept |\n\n"
    "**금지 표현** (있으면 confidence 강제 ≤ 50): '대체로', '아마', '이 정도면 괜찮다', "
    "'spec.md §N 참조', '자세한 건 본문에서', '문서에 적혀있음', '코드에 있음'. "
    "위치만 적고 내용 안 옮긴 셀은 *값이 비어있는 것으로 간주*.\n\n"
    "verdict 값: VERIFIED(spec에 충분 반영) / PARTIAL(일부만 반영, 보완 필요) / MISSING(아예 누락).\n"
    "confidence: 0-100 정수. recommend_action: accept / partial_regen(<axiom_id>) / reject(<reason>) 중 하나.\n\n"
)


def _format_essence_for_prompt(essence: EssenceSource) -> str:
    """essence를 planner prompt에 inline 박을 마크다운 블록으로 직렬화.

    planner는 이 블록을 *원본 그대로* spec.md 본문에 반영한다 (계약).
    """
    lines = [
        "## 본질 (essence_axioms) — 사용자가 외부에서 제공",
        f"_출처: {essence.source}_",
        "",
    ]
    for ax in essence.axioms:
        weight_badge = f"[{ax.weight}] " if ax.weight else ""
        lines.append(f"- **{ax.id}** {weight_badge}{ax.statement}")
        if ax.rationale:
            lines.append(f"  - 이유: {ax.rationale}")
        if ax.falsifiable_by:
            lines.append(f"  - 검증 방법: {ax.falsifiable_by}")
    lines.extend(
        [
            "",
            "**계약**: 이 본질은 *원본 그대로 spec.md 본문에 반영*만 하라. "
            "자체 추가/수정/추출 금지. spec.md 상단 frontmatter(--- ... ---)는 "
            "orchestrator가 자동으로 박으므로 손대지 마라.",
            "",
        ]
    )
    return "\n".join(lines)


def run_generate(
    request: str,
    config: ForgeConfig,
    paths: ProjectPaths,
    essence: Optional[EssenceSource] = None,
    on_question: Optional[AskUserCallback] = None,
    notifier=None,
) -> RunResult:
    """모드 A — spec.md 생성.

    essence가 제공되면 prompt에 inline 인용. 없으면 사용자 request 그대로.
    on_question이 있으면 ASK_USER JSON 출력 시 콜백 호출 (큰 그림 1).

    ⚠️ 같은 세션에서 plan-review.md도 작성한다. spec 생성 후 다음 turn에 즉시
    리뷰를 self-author하여 사용자가 한 카드에서 결정할 수 있게 한다 (큰 그림 1
    Mode A↔B 흡수).
    """
    if essence:
        essence_block = _format_essence_for_prompt(essence) + "\n"
        essence_section = (
            "## 0단계: 본질(essence_axioms) 인용\n"
            "위 본질은 *원본 그대로 spec.md frontmatter에 박아라*. 자체 추가/수정 금지. "
            "frontmatter는 yaml 블록(--- ... ---)으로 spec.md 최상단에 둔다.\n\n"
        )
    else:
        essence_block = ""
        # essence 외부 파일이 없으면 사용자 요청 본문에서 본질을 추출. plan 토대 3의
        # "본질 생성 금지" 원칙은 *외부 essence 파일이 있을 때* 적용되는 우선순위
        # 규칙으로 운용한다. 외부 파일이 없으면 사용자 요청 자체가 본질 출처이므로
        # planner가 그 본문에서 명시적인 본질을 추출해 spec.md frontmatter에 박는다
        # (자동 *해석/인용*이지 자체 *발명*이 아님).
        essence_section = (
            "## 0단계: 본질(essence_axioms) 자동 추출\n"
            "외부 essence 파일이 제공되지 않았다. **사용자 요청 본문에서 본질 3-7개를 추출**하여 "
            "artifacts/spec.md 최상단 frontmatter(--- ... ---)에 YAML 블록으로 박아라. "
            "지어내지 말고 *사용자 요청 본문에 명시적으로 또는 강하게 함축된* 항목만 본질로 채택한다.\n\n"
            "frontmatter 필수 형식:\n"
            "```yaml\n"
            "---\n"
            "essence_source: planner_extracted_from_user_request\n"
            "essence_axioms:\n"
            "  - id: a1\n"
            "    statement: <한 줄, 동사형, 사용자 가치 기준>\n"
            "    rationale: <왜 본질인지 1줄, 사용자 요청 어느 부분에서 도출했는지>\n"
            "    falsifiable_by: <어떻게 깨졌다고 입증할 수 있나, 측정/관찰 방법>\n"
            "    weight: critical | high | medium\n"
            "  - id: a2\n"
            "    ...\n"
            "---\n"
            "```\n"
            "**금지**: 사용자 요청에 없는 항목 추가, 통상적 베스트프랙티스 항목 자동 삽입, "
            "테스트/문서/CI 같은 운영 항목을 본질로 두기 (그건 본질이 아니라 수단).\n\n"
        )
    prompt = (
        f"사용자 요청: {request}\n\n"
        f"{essence_block}"
        "# Mode A — spec.md 생성 + 즉시 self-review (한 세션, 두 산출물)\n\n"
        "artifacts/spec.md가 없다. 다음을 **반드시 모두 Write 도구로 작성**하라.\n\n"
        f"{essence_section}"
        "## 1단계: spec.md 작성\n"
        "위 본질(frontmatter) 아래에 본문을 작성한다. 본문에는 (a) 한마디 요약 "
        "(b) 주요 기능/요구사항 (c) 비범위 (d) 스프린트 구획(`## Sprint 1` … `## Sprint N`)을 포함하라.\n\n"
        "## 2단계: 즉시 self-review → plan-review.md 작성\n"
        "spec.md 작성 직후 같은 세션에서 stop 없이 artifacts/plan-review.md를 "
        "Write로 작성한다. 다음 항목을 반드시 모두 포함:\n"
        "  - 종합 판정 라인: `READY` 또는 `NEEDS_REVISION` 중 하나의 단어를 정확히 포함\n"
        "  - **`## Axiom Verdicts` 섹션** (필수): essence_axioms 각 행을 10컬럼 표로 평가\n"
        "  - 누락/모호 항목 리스트 (있으면)\n"
        "  - 사용자가 결정 시 참고할 1-3개 핵심 트레이드오프\n\n"
        f"{_VERDICT_TABLE_GUIDE}"
        "## 3단계: 사용자 whisper(평문 의견) 응답\n"
        "세션 진행 도중 `[사용자 의견] ...` 으로 시작하는 메시지가 stdin으로 들어올 수 있다. "
        "그 의견에 평문 한 단락으로 즉시 답하라. 답변은 plan-review.md의 `## 사용자 질문 응답` "
        "섹션에도 추가하라 (사용자가 결과에서 확인 가능하도록).\n\n"
        "## 실패 모드\n"
        "spec.md 또는 plan-review.md 둘 중 하나라도 Write 미호출이면 orchestrator가 "
        "감지하여 사용자에게 경고 카드를 띄운다. 반드시 두 파일 모두 Write 후 종료하라."
    )
    return run_agent_sync(
        "planner",
        paths.project_root,
        prompt,
        max_turns=config.planner_max_turns,
        on_question=on_question,
        whisper_queue_path=paths.whisper_queue,
        notifier=notifier,
    )


def run_review(
    config: ForgeConfig,
    paths: ProjectPaths,
    essence: Optional[EssenceSource] = None,
    on_question: Optional[AskUserCallback] = None,
    notifier=None,
) -> RunResult:
    """모드 B — 기존 spec.md 검토.

    ⚠️ 강제 규칙: stream-json 양방향 모드에서 LLM이 종종 텍스트로만 답하고 Write 도구를
    호출하지 않는 패턴이 관찰됨. 이를 막기 위해 prompt를 *명령형*으로 강화.
    """
    if essence:
        essence_block = _format_essence_for_prompt(essence) + "\n"
        essence_section = ""
    else:
        essence_block = ""
        essence_section = (
            "## 0단계: 본질(essence_axioms) 자동 추출 (없을 때만)\n"
            "artifacts/spec.md 상단에 `---\\nessence_axioms:\\n  - ...\\n---` 형식의 "
            "YAML frontmatter가 이미 있으면 이 단계는 skip. 없다면 spec.md 본문(또는 "
            "사용자가 입력한 평문 요청)에서 본질 3-7개를 추출하여 spec.md 최상단에 "
            "Edit 도구로 frontmatter를 박아라.\n\n"
            "frontmatter 필수 형식:\n"
            "```yaml\n"
            "---\n"
            "essence_source: planner_extracted_from_user_request\n"
            "essence_axioms:\n"
            "  - id: a1\n"
            "    statement: <한 줄, 동사형, 사용자 가치 기준>\n"
            "    rationale: <왜 본질인지 1줄, 본문의 어느 부분에서 도출했는지>\n"
            "    falsifiable_by: <어떻게 깨졌다고 입증할 수 있나, 측정/관찰 방법>\n"
            "    weight: critical | high | medium\n"
            "  - id: a2\n"
            "    ...\n"
            "---\n"
            "```\n"
            "**금지**: 본문에 없는 항목 추가, 통상적 베스트프랙티스 자동 삽입, "
            "테스트/문서/CI 같은 운영 항목을 본질로 두기 (그건 본질이 아니라 수단).\n\n"
        )
    prompt = (
        f"{essence_block}"
        "# Mode B — 리뷰 모드 (즉시 실행, 텍스트만 답하지 마라)\n\n"
        "artifacts/spec.md가 이미 존재한다. **반드시 Mode B(리뷰 모드)로 동작**하라.\n\n"
        f"{essence_section}"
        "## 필수 규칙 (위반 시 세션 실패)\n"
        "1. **이 세션은 반드시 Write 도구를 호출하여 artifacts/plan-review.md를 실제로 작성한 뒤 종료해야 한다.** "
        "텍스트로만 답변하고 Write 없이 끝내는 것은 허용되지 않는다.\n"
        "2. plan-review.md는 종합 판정 라인 (READY 또는 NEEDS_REVISION 중 하나)을 반드시 포함해야 한다.\n"
        "3. **plan-review.md에 `## Axiom Verdicts` 섹션 필수** — 아래 가이드 그대로 따라 작성:\n\n"
        f"{_VERDICT_TABLE_GUIDE}"
        "4. 사용자 응답(예: `[사용자 의견]` 접두사 메시지)이 있으면 평문 한 단락으로 즉시 답하고, "
        "plan-review.md 본문에도 `## 사용자 질문 응답` 섹션을 추가해 사용자가 결과를 확인할 수 있게 하라.\n"
        "5. plan-review.md 작성 완료 후에만, specs/ 에 누락된 도메인 스펙이 있으면 추가로 보강하라.\n\n"
        "## 실패 모드\n"
        "Write가 한 번도 호출되지 않고 세션이 종료되면 orchestrator가 plan-review.md 부재를 감지하여 "
        "사용자에게 경고를 전송한다. 그 상황을 피하려면 **반드시 Write 실행 후 종료**하라."
    )
    return run_agent_sync(
        "planner",
        paths.project_root,
        prompt,
        max_turns=config.planner_review_max_turns,
        on_question=on_question,
        whisper_queue_path=paths.whisper_queue,
        notifier=notifier,
    )


_CAPABILITY_GUIDE = (
    "### sprint-capabilities.md 작성 가이드 (Branch Capability Card 데이터 소스)\n"
    "**핵심 규칙**: sprint-contract.md의 분기(branch) 1개 = sprint-capabilities.md의 "
    "capabilities[] 항목 1개. 사용자는 분기별 카드 1장만 보고 8-10초 안에 "
    "'이 분기를 살릴지 뺄지' 판단하므로 각 필드에 *내용 자체*를 적어야 한다.\n\n"
    "**파일 위치**: `artifacts/sprint-capabilities.md`. frontmatter YAML 단일 소스 + "
    "본문은 사람 친화 미러(선택). Write 도구로 생성.\n\n"
    "**frontmatter 스키마** (예시 그대로 박지 말고 분기 내용에 맞춰 새로 작성):\n"
    "```yaml\n"
    "---\n"
    "sprint_number: 1\n"
    "branches:\n"
    "  - id: branch-1                        # contract.py BranchSpec.id와 1:1 매핑\n"
    "    title: \"URL 입력 + 진행률 표시\"     # BranchSpec.title 미러\n"
    "    tasks:                              # BranchSpec.tasks 미러 (체크리스트로 카드에 노출)\n"
    "      - \"URL 폼 컴포넌트\"\n"
    "      - \"다운로드 진행률 SSE 핸들러\"\n"
    "    related_essence: [a2, a3]           # 매핑된 본질 id (spec.md essence_axioms 참조)\n"
    "    essence_score_llm: 88               # LLM 추정 0-100 (critical=80+, high=60-80, medium=40-60)\n"
    "    essence_score_floor: 70             # 규칙 하한선 = max(매핑 본질의 weight 환산)\n"
    "                                        # critical=100 / high=70 / medium=40\n"
    "    essence_basis: |\n"
    "      본질 a2(시각차분 측정)와 직접 부합. a3(노이즈 차단)에도 약하게 기여.\n"
    "      이유: 사용자가 입력→결과까지의 흐름을 끊지 않고 보게 함.\n"
    "    what_is: \"URL 한 줄 입력 → 다운로드 진행률 실시간 표시\"\n"
    "    why_needed: |\n"
    "      본질 a2의 이유: \"어디까지 진행됐는지 모르면 새로고침/재시도로 불필요 비용 유발.\"\n"
    "      spec §사용자 시나리오 1과 일치.\n"
    "    absence_impact: |\n"
    "      입력 후 무응답 화면 → 진행 중인지 죽었는지 모름.\n"
    "      재요청 클릭으로 비용 2배. 본질 a2 위반.\n"
    "    recommend_action: keep              # keep | drop | revise\n"
    "---\n"
    "```\n\n"
    "**필드별 핵심 질문**:\n"
    "- `essence_score_llm`: weight + rationale + 사용자 시나리오를 종합한 본질 부합도 추정. "
    "critical 본질 직접 부합이면 80+, high 본질 부합이면 60-80, medium만 닿으면 40-60.\n"
    "- `essence_score_floor`: 규칙 기반 하한선. 매핑된 본질 weight 환산값 중 최댓값.\n"
    "- `essence_basis`: 어느 본질의 어느 statement에 어떻게 부합하는지 자연어 1-2줄. "
    "본질 id만 적지 말고 *왜 부합하는지 이유까지*.\n"
    "- `what_is`: 이 분기가 만들 기능을 한 문장 직접 묘사 (위치만 지시 X).\n"
    "- `why_needed`: 본질의 rationale + spec 사용자 시나리오 인용. 위치 X, 내용 O.\n"
    "- `absence_impact`: 이 분기가 빠지면 사용자에게 일어날 일을 결과로 묘사. "
    "어느 본질이 깨지는지도 명시.\n"
    "- `recommend_action`: keep(본질 부합 명확) / drop(본질 무관) / revise(부분 보강 필요).\n\n"
    "**금지**: `essence_basis`/`why_needed`/`absence_impact` 셀에 "
    "'spec.md §N 참조', '코드에 있음', '본문에서 확인' 같은 위치만 적는 표현. "
    "이런 표현이 있으면 카드만으로 사용자가 판단 불가 → 본 가이드 위반.\n"
    "**related_essence가 비어있으면** 그 분기를 P0에서 제외 권유 (recommend_action=drop). "
    "본질과 무관한 기능을 sprint에 묶지 마라.\n\n"
)


def run_contract(
    sprint_num: int,
    config: ForgeConfig,
    paths: ProjectPaths,
    essence: Optional[EssenceSource] = None,
    on_question: Optional[AskUserCallback] = None,
    notifier=None,
) -> RunResult:
    """모드 C — Sprint Contract 생성.

    ⚠️ Write 도구 강제 규칙은 run_review와 같은 이유로 명령형 prompt.
    """
    essence_block = _format_essence_for_prompt(essence) + "\n" if essence else ""
    prompt = (
        f"{essence_block}"
        f"# Mode C — Sprint {sprint_num} Contract 생성 (즉시 실행, 텍스트만 답하지 마라)\n\n"
        f"## 필수 규칙 (위반 시 세션 실패)\n"
        f"1. **이 세션은 반드시 Write 도구를 호출하여 artifacts/sprint-contract.md를 실제로 작성한 뒤 종료해야 한다.** "
        f"텍스트로만 답변하고 Write 없이 끝내는 것은 허용되지 않는다.\n"
        f"2. templates/sprint-contract-template.md 형식을 따르라.\n"
        f"3. spec.md / specs/ / progress-log.md / sprint-*-done.md를 반영하라.\n"
        f"4. **sprint-contract.md 작성 직후 곧이어 Write 도구로 "
        f"artifacts/sprint-capabilities.md도 작성하라.** "
        f"sprint-contract.md의 분기(branch)별로 Branch Capability Card 데이터를 채운다. "
        f"양식과 톤은 아래 가이드 참조.\n\n"
        f"{_CAPABILITY_GUIDE}"
        f"## 실패 모드\n"
        f"Write 미호출 종료 시 orchestrator가 sprint-contract.md 부재를 감지하여 generator 시작을 막고 "
        f"사용자에게 경고를 전송한다. 반드시 Write 실행 후 종료하라."
    )
    return run_agent_sync(
        "planner",
        paths.project_root,
        prompt,
        max_turns=config.contract_max_turns,
        on_question=on_question,
        whisper_queue_path=paths.whisper_queue,
        notifier=notifier,
    )


def run_revise(
    revise_text: str,
    config: ForgeConfig,
    paths: ProjectPaths,
    notifier=None,
) -> RunResult:
    """모드 D — 사용자 지시에 따라 기존 spec.md를 수정.

    streaming 도입 후에도 단독 진입점으로 유지 (orchestrator가 별도 신호로 호출).
    큰 그림 1 단계에서 planner-spec 세션과 흡수 여부 재검토.
    """
    prompt = (
        f"# Mode D — spec.md 수정 모드 (즉시 실행, 질문 금지)\n\n"
        f"## 사용자 지시\n{revise_text}\n\n"
        f"## 필수 규칙 (위반 시 실패로 간주)\n"
        f"1. **이 세션은 반드시 Edit 도구를 최소 1회 이상 호출하여 "
        f"artifacts/spec.md를 실제로 수정해야 한다.** "
        f"Edit 없이 종료하는 것은 허용되지 않는다.\n"
        f"2. **사용자에게 추가 질문하지 마라.** 이 세션은 비대화형 subprocess다. "
        f"사용자는 응답을 볼 수 없다.\n"
        f"3. **'구체적 지시가 필요하다', '수정 준비 완료', '어떻게 바꿀까요' 같은 "
        f"메타 응답은 금지**된다. 그 응답 대신 즉시 Edit을 실행하라.\n"
        f"4. 사용자 지시가 추상적이면 **artifacts/plan-review.md의 NEEDS_REVISION 지적사항 전체**를 "
        f"수정 대상 리스트로 사용하라. 모호한 부분은 합리적 기본값을 채택하고, "
        f"그 근거를 artifacts/decisions/decision-NNN.md에 1-3줄로 기록하라.\n\n"
        f"## 수행 절차\n"
        f"1. artifacts/spec.md Read\n"
        f"2. artifacts/plan-review.md Read (반영 대상 목록)\n"
        f"3. artifacts/specs/*.md Read (존재하는 것만)\n"
        f"4. **artifacts/spec.md를 Edit 도구로 실제 수정** "
        f"— 사용자 지시 + plan-review 지적사항 병합 반영\n"
        f"5. 일관성 필요 시 artifacts/specs/*.md도 Edit으로 보강 (신규 Write도 허용)\n"
        f"6. artifacts/plan-review.md를 Edit으로 갱신하되, 맨 위에 이 섹션 추가:\n"
        f"   ```\n"
        f"   ## 수정 이력 — (현재 타임스탬프)\n"
        f"   - 사용자 지시: {revise_text}\n"
        f"   - 변경 요약: spec.md의 어느 섹션을 어떻게 바꿨는지 3줄 이상\n"
        f"   ```\n"
        f"7. plan-review.md의 종합 판정 라인을 READY 또는 NEEDS_REVISION으로 재기록\n\n"
        f"## 금지 사항\n"
        f"- artifacts/ 바깥 파일 수정/생성/이동/삭제\n"
        f"- Edit 호출 없이 설명·분석만 하고 종료\n"
        f"- 사용자에게 추가 지시를 요구하는 질문형 응답\n"
        f"- spec.md의 구조를 통째로 바꾸지 말 것 (사용자가 명시 요청한 경우만 예외)\n\n"
        f"## 실패 모드\n"
        f"Edit을 한 번도 호출하지 않고 세션이 종료되면, 오케스트레이터가 "
        f"spec.md mtime 미변경을 감지하여 사용자에게 경고를 전송한다. "
        f"그 상황을 피하려면 **반드시 Edit 실행 후 종료**하라."
    )
    return run_agent_sync(
        "planner",
        paths.project_root,
        prompt,
        max_turns=config.planner_review_max_turns,
        whisper_queue_path=paths.whisper_queue,
        notifier=notifier,
    )


def plan_review_status(paths: ProjectPaths) -> str:
    """plan-review.md에서 'READY' / 'NEEDS_REVISION' 추출."""
    if not paths.plan_review.exists():
        return "MISSING"
    text = paths.plan_review.read_text(encoding="utf-8", errors="replace")
    if "NEEDS_REVISION" in text:
        return "NEEDS_REVISION"
    if "READY" in text:
        return "READY"
    return "UNKNOWN"
