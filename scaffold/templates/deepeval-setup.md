---
template_id: deepeval-setup
domain: LLM 평가
keywords: [deepeval, metric, g-eval, test case, evaluation, faithfulness, relevancy, a_measure, asyncio, parallel, custom llm, evaluator]
when_to_use: |
  LLM 출력 품질을 자동 평가하는 파이프라인이 필요할 때.
  DeepEval 메트릭과 테스트케이스 설계, 커스텀 평가 LLM 구성,
  메트릭 병렬화, 평가 결과를 자체 포맷으로 리포팅해야 할 때.
output: artifacts/specs/deepeval-metrics.md
related_templates: [langfuse-setup]
---

# DeepEval 평가 스펙 템플릿

(레이어 3 — LLM 출력 품질 자동 채점)

## DeepEval 필수 체크리스트 (먼저 읽을 것)

> DeepEval은 "원인·해결책이 문서에 잘 안 드러나는" 함정이 유독 많다. 한국어 채점, 커스텀 LLM, 병렬화, 가중치 분리 산출을 붙이면 빠르게 지뢰밭이 된다. 아래 6개는 반드시 확인.

1. **채점 LLM은 반드시 `response_format={"type": "json_object"}` 로 JSON 강제**
   - G-Eval 등 LLM 판정형 메트릭은 내부적으로 `trimAndLoadJson()`으로 score/reason을 파싱함
   - 한국어 채점에서 LLM이 자유 텍스트나 Python 문자열 연결 등 비표준 구문을 섞으면 `ValueError` 로 케이스 통째 실패
   - OpenAI 계열은 `model_kwargs={"response_format": {"type": "json_object"}}` 로 해결. Anthropic 계열은 시스템 프롬프트에 JSON 강제 지시 필수

2. **커스텀 평가 LLM은 `generate()` + `a_generate()` 둘 다 구현**
   - `a_generate()` 가 없으면 `metric.a_measure()` 호출 시 `NotImplementedError` → 병렬화 불가
   - `DeepEvalBaseLLM` 상속 후 `generate`, `a_generate`, `load_model`, `get_model_name` 4개 필수
   - `temperature=0` 고정이 기본 — 채점 결과 일관성을 위해

3. **메트릭은 매 테스트 케이스마다 새 인스턴스로 만들 것 (팩토리 패턴)**
   - 메트릭 객체는 `.score`, `.reason`, `.success`, `.error` 속성을 **인스턴스 상태**로 덮어씀
   - 한 인스턴스를 여러 케이스에 재사용하면 이전 케이스의 reason이 남거나, 병렬 실행 시 race condition 발생
   - `def get_metrics_for_type(...) -> list: return [GEval(...), Faithfulness(...), ...]` 같이 호출할 때마다 새로 생성

4. **CLI는 `deepeval test run`, 내부는 pytest — 마지막 "No test cases found" 메시지는 정상**
   - `deepeval test run path/to/test.py -v`는 pytest 래퍼. 일반 `pytest` 로 돌려도 되지만 `assert_test` 훅이 빠짐
   - `assert_test(test_case, metrics)` 없이 `metric.measure()` / `metric.a_measure()` 를 수동 호출하면, deepeval CLI 마지막 줄에 `"No test cases found, please try again."` 가 찍힘 → **무시해도 됨** (결과/PASS/FAIL 판정과 무관)
   - 수동 호출 방식이 커스텀 출력 포맷(분석/RAG 분리, 에이전트별 가중치 등)을 유지할 때 유리

5. **실행 모드를 환경변수로 분리 — 개발 반복 속도가 수십 배 차이**
   - `E2E_MODE=eval_only` (캐시 로드), `cache_only` (서버 호출+저장만), `full` (서버 호출+평가) 3-way 분리
   - 이 분리가 없으면 메트릭 한 줄 고치고도 매번 40분 서버 파이프라인을 기다리게 됨
   - `EVAL_QUICK_MODE=1` 로 "에이전트/데이터셋당 첫 케이스만" 돌리는 스위치도 같이 준비 — 디버깅 시 1시간→1분

6. **병렬화는 `metric.a_measure()` + `asyncio.gather()` 가 정석 — pytest-xdist(-n 4)는 함정**
   - 내장 메트릭(GEval, Faithfulness, AnswerRelevancy 등)은 모두 `a_measure()` 네이티브 지원
   - `-n 4` (pytest-xdist)는 프로세스가 분리돼서 전역 dict(`_JSON_DETAIL_STORE` 등)와 Langfuse `ContextVar` 가 프로세스별로 쪼개짐 → JSON 덮어쓰기·세션 추적 깨짐
   - asyncio는 단일 스레드라 전역 dict와 ContextVar가 자동 안전. 커스텀 출력 포맷도 그대로 유지

### 의존성 명시

```toml
# pyproject.toml
dependencies = [
    "deepeval>=3.8.8,<4",   # 3.8부터 a_measure() 안정화
    "pytest>=8",            # deepeval CLI가 내부적으로 사용
]
```

`deepeval>=3.x` 만 써두면 `uv sync`가 4.x로 올릴 경우 API 깨짐 가능. 메이저 버전 핀 권장.

## 메트릭
- (예: AnswerRelevancy, Faithfulness, ContextualPrecision, G-Eval 커스텀)
- 임계값 (`threshold=0.7` 권장, 도메인별 조정)
- 가중치 분리: RAG 관련 메트릭과 로직 품질 메트릭은 **합산하지 말고 독립 산출** 권장 (둘의 성격이 다름)

## 테스트케이스
- 입력 / 기대 출력 / 컨텍스트 (`retrieval_context` — RAG 시)
- 최소 N개 (에이전트당 3건 이상 권장, CI에선 1건으로 축소)

## 실행
- `deepeval test run tests/eval/` (로컬 전체)
- `EVAL_QUICK_MODE=1 deepeval test run tests/eval/ -v` (빠른 파일럿)
- `EVAL_FULL_OUTPUT=1 ...` (입출력 원문 확인용, 디버깅 시)
- CI 연동 여부

## 검증
- 모든 메트릭 임계값 통과
- 실패 케이스 근거 로그 저장 (`metric.reason` 를 JSON에 필수 포함)

## 공통 함정 (실전 체크리스트)

### 1. GEval이 한국어 응답에서 `ValueError` 로 죽음
- 원인: 채점 LLM이 `"reason": "...이다."` 같은 텍스트를 반환할 때 내부 구두점/줄바꿈으로 JSON 파싱 실패
- 해결:
  ```python
  # src/tests/custom_llm.py
  from deepeval.models.base_model import DeepEvalBaseLLM

  class ProjectEvaluatorLLM(DeepEvalBaseLLM):
      def __init__(self, model_name="gpt-5-mini"):
          from utils.llm import RetryableChatOpenAI
          self.model = RetryableChatOpenAI(
              model=model_name,
              temperature=0,
              request_timeout=120,
              model_kwargs={"response_format": {"type": "json_object"}},  # 핵심
          )
          self._model_name = model_name
          super().__init__()

      def generate(self, prompt: str) -> str:
          return self.model.invoke(prompt).content

      async def a_generate(self, prompt: str) -> str:
          return (await self.model.ainvoke(prompt)).content

      def load_model(self):
          return self.model

      def get_model_name(self) -> str:
          return self._model_name

  evaluator_llm = ProjectEvaluatorLLM()  # 싱글톤
  ```
- 메트릭 생성 시 `model=evaluator_llm` 으로 주입하여 전체 메트릭이 동일 평가 모델 공유

### 2. 메트릭을 직렬 `for` 루프로 돌려서 평가 시간 N배 누적
- 원인: `for m in metrics: m.measure(test_case)` 는 메트릭별 LLM 응답(15~180초)이 순차 누적
- 해결: `a_measure()` + `asyncio.gather()` 로 "가장 느린 메트릭 1개 시간"만 기다리면 됨
  ```python
  # src/tests/format_utils.py — 공용 헬퍼
  import asyncio
  import time

  async def _a_measure_one(metric, test_case):
      m_name = getattr(metric, "name", type(metric).__name__)
      t0 = time.time()
      try:
          score = await metric.a_measure(test_case)
          return m_name, score or 0.0, time.time() - t0, None
      except Exception as e:
          return m_name, 0.0, time.time() - t0, e

  def run_metrics_parallel(test_case, metrics):
      async def _gather():
          return await asyncio.gather(*[_a_measure_one(m, test_case) for m in metrics])
      return asyncio.run(_gather())
  ```
- 호출부는 기존 for 루프를 한 줄로 치환 → 출력 포맷(print/JSON) 0% 변경
  ```python
  # BEFORE
  for metric in metrics:
      score = metric.measure(tc)
      scores[metric.name] = score

  # AFTER
  for m_name, score, elapsed, err in run_metrics_parallel(tc, metrics):
      if err is not None:
          print(f"[경고] {m_name} 실패: {err}")
      scores[m_name] = score
  ```
- 실측: 메트릭 6개 병렬 시 약 2.6~3배 단축 (I/O 대기 제거가 병목. 직렬 453s → 병렬 177s)

### 3. `evaluate()` 함수를 썼더니 커스텀 출력 포맷이 다 깨짐
- 원인: `evaluate(test_cases, metrics)` 는 자체 포맷으로 `EvaluationResult` 를 반환하고 콘솔에 찍음
- 증상: 프로젝트 고유의 `[분석 평가]`, `[RAG 평가]`, 에이전트별 가중치 분리 등을 재구성하려면 `result.test_results[i].metrics_data[j].score/.reason` 를 전면 파싱해야 함
- 선택 기준:
  - **커스텀 리포팅이 중요 → 수동 `a_measure()` + `asyncio.gather()`**
  - **캐싱/비용추적/Confident AI 연동이 중요 → `evaluate()` + `AsyncConfig(run_async=True, max_concurrent=20)`**

### 4. Rate limit (OpenAI 429) 가 병렬화 직후 발생
- 원인: 메트릭 N개 × 테스트 케이스 M개를 동시에 발사하면 TPM/RPM 상한 돌파
- 해결 A — `asyncio.Semaphore` 로 동시성 상한:
  ```python
  _SEM = asyncio.Semaphore(4)

  async def _a_measure_one(metric, test_case):
      async with _SEM:
          return await metric.a_measure(test_case)
  ```
- 해결 B — `evaluate()` 사용 시 `AsyncConfig(throttle_value=2, max_concurrent=10)` 로 케이스 간 지연 + 동시성 상한 동시 적용
- 해결 C — 프로젝트의 `RetryableChatOpenAI` 같은 지수 백오프 래퍼 사용 (429는 재시도로 복구 가능)

### 5. Langfuse 세션 추적이 비어 있음
- 원인: DeepEval 채점 LLM 호출이 `session_id=null` 로 기록되어 프로덕션 trace와 구분 안 됨
- 해결: pytest `session` 스코프 fixture로 `ContextVar` 기반 세션 전파
  ```python
  # src/tests/conftest.py
  @pytest.fixture(scope="session", autouse=True)
  def langfuse_test_session():
      from utils.langfuse_tracker import tracker
      from datetime import datetime
      session_id = f"deepeval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
      tokens = tracker.set_test_context(session_id=session_id, tags=["deepeval", "evaluation"])
      yield session_id
      tracker.clear_test_context(tokens)
      tracker.flush()
  ```
- asyncio는 단일 스레드 → ContextVar 자동 전파 (`a_measure()` 병렬 실행에도 안전)
- 주의: `deepeval test run -n 4` (pytest-xdist) 쓰면 프로세스 분리로 ContextVar가 공유 안 됨 → 세션 추적 깨짐

### 6. 전역 `_JSON_DETAIL_STORE` 가 pytest-xdist 에서 덮어씌워짐
- 원인: 프로세스별 Python 인터프리터가 각자의 전역 dict를 가짐 → 마지막 프로세스의 데이터만 파일에 저장됨
- 해결: 병렬화는 프로세스(-n) 대신 asyncio로. 꼭 프로세스 병렬이 필요하면 `multiprocessing.Manager().dict()` 같은 공유 객체로 교체

### 7. E2E 서버 파이프라인 호출이 매번 40분 걸려 개발 반복 불가
- 원인: 테스트마다 실제 파이프라인을 호출하면 메트릭 튜닝 주기가 막힘
- 해결: 3-mode fixture로 캐시 분리
  ```python
  # E2E_MODE: eval_only(기본, 캐시 로드) / cache_only(서버→캐시 저장만) / full(서버+평가)
  E2E_MODE = os.getenv("E2E_MODE", "eval_only").strip()
  CACHE_PATH = "e2e_result.json"

  @pytest.fixture(scope="session")
  def e2e_result():
      if E2E_MODE == "eval_only":
          with open(CACHE_PATH, "r", encoding="utf-8") as f:
              return json.load(f)
      # cache_only / full: 서버 호출 후 캐시 저장
      result = client.run_pipeline(...)
      with open(CACHE_PATH, "w", encoding="utf-8") as f:
          json.dump(result, f, ensure_ascii=False, indent=4)
      if E2E_MODE == "cache_only":
          pytest.skip("cache_only: 평가 생략")
      return result
  ```
- 최초 1회 `E2E_MODE=cache_only` 로 캐시 생성 → 이후 메트릭/프롬프트 수정 반복은 `eval_only` 로 수 분 내 완료

### 8. 커스텀 메트릭 G-Eval 의 `criteria` 가 모호해서 점수가 들쭉날쭉
- 원인: `criteria="분석이 좋은지 평가"` 같이 추상적이면 채점 LLM이 매번 다른 기준 적용
- 해결: 가점/감점 요건을 **명시적 리스트** 로 작성. 예시:
  ```python
  from deepeval.metrics import GEval
  from deepeval.test_case import LLMTestCaseParams

  analysis_depth = GEval(
      name="AnalysisDepth",
      evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
      criteria=(
          "분석의 깊이를 다음 기준으로 평가:\n"
          "- [가점 1] 수치 근거가 3개 이상 인용되는가 (예: 매매가, 인구 증감률, 청약 경쟁률)\n"
          "- [가점 2] 원인-결과 논리 체인이 2단계 이상인가\n"
          "- [감점 1] 일반론적 서술(~로 보인다, ~할 수 있다)이 60% 이상인가\n"
          "- [필수] 판단 근거는 한국어로 작성되었는가\n"
      ),
      model=evaluator_llm,
      threshold=0.7,
  )
  ```
- `reason` 필드에 평가 LLM이 "어떤 요건이 가/감점됐는지" 명시하도록 criteria 에 유도

### 9. 분석 점수와 RAG 점수를 합산했더니 한쪽이 0점이어도 통과
- 원인: 분석 품질 메트릭과 RAG 검색 품질 메트릭을 단순 평균하면 서로를 상쇄
- 해결: **독립 산출**. 각각 threshold 걸고 둘 다 통과해야 PASS
  ```python
  def calculate_separated_scores(agent_name, scores: dict) -> dict:
      analysis_weights = {"AnalysisDepth": 0.6, "DataFidelity": 0.2, "StructuralCompleteness": 0.2}
      rag_weights = {"Faithfulness": 0.334, "Contextual Relevancy": 0.333, "Answer Relevancy": 0.333}

      analysis_score = sum(scores.get(k, 0) * w for k, w in analysis_weights.items())
      rag_score = sum(scores.get(k, 0) * w for k, w in rag_weights.items())
      return {"analysis_score": analysis_score, "rag_score": rag_score}
  ```
- RAG 점수는 RAG 에이전트에만 적용, 비-RAG는 분석 점수만

### 10. `truths_extraction_limit` 기본값 때문에 Faithfulness 호출이 폭주
- 원인: Faithfulness는 `actual_output`에서 claims를 추출해 각 claim을 context에 대조 → 장문 응답은 100+ claims 추출 → LLM 호출 100회
- 해결: `FaithfulnessMetric(truths_extraction_limit=10, ...)` 로 상한 설정
- Contextual Relevancy, Answer Relevancy도 동일한 `limit` 계열 파라미터 확인 후 상한 설정
