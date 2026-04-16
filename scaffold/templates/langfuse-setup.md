---
template_id: langfuse-setup
domain: LLM 추적/관측
keywords: [langfuse, trace, span, observability, monitoring, token, cost]
when_to_use: |
  프로젝트 코드 내 LLM 호출을 Langfuse로 추적할 때.
  토큰 사용량, 레이턴시, 세션별 비용을 모니터링하는 경우.
output: artifacts/specs/langfuse-tracing.md
related_templates: [deepeval-setup]
---

# Langfuse 추적 스펙 템플릿

(레이어 2 — 프로젝트 코드 내부 LLM 호출 추적)

## 추적 계층
- Trace: 사용자 요청 단위
- Span: 각 LLM 호출 / 에이전트 단계
- session_id: 사용자/세션 식별자

## 메타데이터 표준
- model, input_tokens, output_tokens, latency_ms
- tool_calls (있으면)
- user_feedback (있으면)

## 삽입 위치
- 모든 LLM 래퍼 함수에 `@observe` 또는 컨텍스트 매니저
- 배치 플러시 보장 (앱 종료 전)

## 검증
- 샘플 요청 실행 후 Langfuse 대시보드에 trace가 보이는가
- Evaluator가 "삽입 누락된 LLM 호출"을 지적할 수 있는가

## 공통 함정 (실전 체크리스트)

### 1. 토큰이 Tokens/Cost 열에 안 뜸
- 원인: `span.update(metadata={"tokens_input": ...})` 에 토큰을 넣으면 metadata 탭에만 보이고 집계에 반영 안 됨
- 해결: **`usage_details`**를 써야 함
  ```python
  span.update(
      usage_details={"input": tok_in, "output": tok_out, "cache_read": tok_cache},
      metadata={"duration_seconds": duration, "status": status},  # 토큰 외 부가 정보만
  )
  ```
- 키 이름은 `input`/`output`/`cache_read` 등 Langfuse가 인식하는 표준 필드

### 2. Session 뷰에 집계 안 됨
- 원인: `metadata={"session_id": ...}` 처럼 metadata에 넣으면 Langfuse가 세션 필드로 인식 안 함
- 해결: **trace 레벨**에 직접 설정
  ```python
  client.start_as_current_observation(name=..., as_type="span", metadata={...})
  client.update_current_trace(
      name="project-sprint-1",
      session_id=project_name,   # 프로젝트/사용자 단위로 묶어야 Sessions 뷰가 의미 있음
      user_id=project_name,
  )
  ```
- 세션 범위 선택 가이드:
  - 프로젝트 전체를 한 세션으로 → 여러 실행/스프린트가 한 그룹으로 집계 (추천)
  - 한 번의 실행만을 세션으로 → trace 1개 = session 1개라 집계 의미 적음

### 3. Interactive 세션 토큰이 0
- `claude -p` 같은 비대화 호출은 stdout에 토큰이 안 찍힐 수 있음 → 정규식 파서만으론 추출 불가
- 대화형 세션(`claude` 단독)은 `~/.claude/projects/{project_id}/*.jsonl`에 `message.usage`로 기록됨
- **project_id 인코딩 규칙** (경로→폴더명): `:`, `\`, `/`, `.`, `_` 전부 `-`로 치환 + 소문자화
  ```python
  cwd = str(Path.cwd().resolve()).lower()
  project_id = re.sub(r"[:\\/._]", "-", cwd)
  session_dir = Path.home() / ".claude" / "projects" / project_id
  ```
- Windows 예: `C:\01.project\obsidian_sync` → `c--01-project-obsidian-sync`

### 4. 플러시 누락
- 앱 종료 직전 `client.flush()` 미호출 시 최근 span이 사라질 수 있음
- 컨텍스트 매니저/OTEL 사용 시 `__exit__`에서 자동 처리되지만, 짧게 끝나는 스크립트는 명시적 `flush()` 권장
