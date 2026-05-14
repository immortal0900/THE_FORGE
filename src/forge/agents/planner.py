"""Planner 에이전트 — 영속 Popen 세션 호출 wrapper.

토대 1 (docs/plan-judgment-velocity.md): subprocess.run batch → 영속 Popen +
stream-json 양방향. 함수 시그니처는 그대로 두어 호출처(orchestrator.py)와의
인터페이스 호환을 유지한다. 결과 객체는 RunResult (subprocess.CompletedProcess
호환: returncode / stdout / stderr).

NOTE (큰 그림 1 단계에서 처리 예정):
    - Mode A(run_generate) ↔ Mode B(run_review) ↔ Mode D(run_revise) 는
      streaming 세션이 살아있는 한 *같은 세션*에 흡수되어야 한다.
      이번 토대 1에서는 마이그레이션만, 흡수는 큰 그림 1에서.
"""

from __future__ import annotations

from ..config import ForgeConfig, ProjectPaths
from .runner import RunResult, run_agent_sync


def run_generate(
    request: str,
    config: ForgeConfig,
    paths: ProjectPaths,
) -> RunResult:
    """모드 A — spec.md 생성."""
    prompt = (
        f"사용자 요청: {request}\n\n"
        f"artifacts/spec.md가 없거나 사용자가 재생성을 요청했다. "
        f"생성 모드로 동작하여 artifacts/spec.md를 작성하라."
    )
    return run_agent_sync(
        "planner",
        paths.project_root,
        prompt,
        max_turns=config.planner_max_turns,
    )


def run_review(config: ForgeConfig, paths: ProjectPaths) -> RunResult:
    """모드 B — 기존 spec.md 검토."""
    prompt = (
        "artifacts/spec.md가 이미 존재한다. **반드시 Mode B(리뷰 모드)로 동작**하라. "
        "생성 모드로 전환하지 말 것. "
        "최우선 작업: artifacts/plan-review.md를 작성하라 "
        "(종합 판정은 READY 또는 NEEDS_REVISION 중 하나). "
        "plan-review.md 작성 완료 후에만, specs/ 에 누락된 도메인 스펙이 있으면 추가로 보강하라."
    )
    return run_agent_sync(
        "planner",
        paths.project_root,
        prompt,
        max_turns=config.planner_review_max_turns,
    )


def run_contract(
    sprint_num: int,
    config: ForgeConfig,
    paths: ProjectPaths,
) -> RunResult:
    """모드 C — Sprint Contract 생성."""
    prompt = (
        f"Sprint {sprint_num}의 sprint-contract.md를 생성하라. "
        f"templates/sprint-contract-template.md 형식을 따르고, "
        f"spec.md / specs/ / progress-log.md / sprint-*-done.md를 반영하라."
    )
    return run_agent_sync(
        "planner",
        paths.project_root,
        prompt,
        max_turns=config.contract_max_turns,
    )


def run_revise(
    revise_text: str,
    config: ForgeConfig,
    paths: ProjectPaths,
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
