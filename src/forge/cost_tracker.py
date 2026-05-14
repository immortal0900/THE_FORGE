"""SprintTracer — Langfuse Trace/Span + harness-cost-log.txt + 토큰 추적 (v2.3)."""

from __future__ import annotations

import json
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional


# ── 토큰 추출 유틸리티 (v2.3) ──────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"[Tt]okens?:\s*input\s*([\d,]+)\s*/\s*output\s*([\d,]+)"
    r"(?:\s*/\s*cache\s*([\d,]+))?",
    re.IGNORECASE,
)


def _extract_tokens_from_stdout(stdout: str) -> dict:
    """subprocess stdout의 마지막 'Tokens: ...' 라인을 파싱."""
    matches = list(_TOKEN_RE.finditer(stdout))
    if not matches:
        return {"input": 0, "output": 0, "cache": 0}
    m = matches[-1]
    return {
        "input": int(m.group(1).replace(",", "")),
        "output": int(m.group(2).replace(",", "")),
        "cache": int(m.group(3).replace(",", "")) if m.group(3) else 0,
    }


def _parse_iso_ts(ts: object) -> Optional[float]:
    """Claude Code JSONL의 'timestamp' 필드 (ISO 8601 문자열) → Unix epoch float."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if not isinstance(ts, str):
        return None
    try:
        # "2026-04-13T14:54:12.013Z" 형식 지원
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return None


def _extract_tokens_from_jsonl(since: float, until: float) -> dict:
    """~/.claude/projects/<id>/*.jsonl에서 [since, until] 범위 assistant 레코드 토큰 합산.

    claude -p / interactive 모두 여기 기록됨. 가장 많이 쓰인 model 이름도 함께 반환
    (Langfuse가 자동 cost 계산하려면 model이 필요).

    Claude Code 폴더명 규칙 (관찰 기반):
      - cwd 전체에서 [^a-zA-Z0-9-] 문자를 모두 '-'로 치환
      - 대소문자는 보존
      - 예) "C:\\1.Project\\면접대비" → "C--1-Project-----"
           "C:\\1.Project\\THE_FORGE" → "c--1-Project-THE-FORGE"
             (사용자 환경별로 드라이브 문자 대소문자가 달라질 수 있음)
    """
    claude_home = Path.home() / ".claude" / "projects"
    totals = {"input": 0, "output": 0, "cache": 0, "model": ""}
    if not claude_home.exists():
        return totals

    cwd_raw = str(Path.cwd().resolve())
    # Claude Code 규칙: 영숫자와 '-' 외 모두 '-'로 치환, 대소문자 보존
    primary = re.sub(r"[^a-zA-Z0-9-]", "-", cwd_raw)
    # 구 규칙 폴백: 예전 버전은 '_' 기반이거나 다른 규칙을 썼을 수 있음
    legacy = re.sub(r"[:\\/._]", "-", cwd_raw.lower())
    candidates = [primary, primary.lower()]
    if legacy not in candidates:
        candidates.append(legacy)

    session_dir: Optional[Path] = None
    for cand in candidates:
        p = claude_home / cand
        if p.exists():
            session_dir = p
            break
    # 모두 실패 시: cwd 끝부분(폴더명)을 키워드로 유사 매칭 (한 글자 한글은 모두 '-'가 되므로
    # 마지막 폴더명은 정보량이 없을 수 있음. 상위 폴더 이름으로도 시도)
    if session_dir is None:
        path_tokens = [t for t in re.split(r"[\\/]", cwd_raw) if t]
        # 영숫자 토큰만 골라 2글자 이상만 유효 키로 사용
        keys = [re.sub(r"[^a-zA-Z0-9]", "", t) for t in path_tokens]
        keys = [k for k in keys if len(k) >= 2]
        if keys:
            pattern = re.compile(".*".join(re.escape(k) for k in keys))
            for sub in claude_home.iterdir():
                if sub.is_dir() and pattern.search(sub.name):
                    session_dir = sub
                    break
    if session_dir is None:
        return totals

    model_token_counts: dict[str, int] = {}

    for jsonl_file in session_dir.glob("*.jsonl"):
        try:
            with open(jsonl_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("type") != "assistant":
                        continue
                    ts = _parse_iso_ts(record.get("timestamp"))
                    if ts is None or not (since <= ts <= until):
                        continue
                    message = record.get("message") or {}
                    usage = message.get("usage") or {}
                    tok_in = usage.get("input_tokens", 0) or 0
                    tok_out = usage.get("output_tokens", 0) or 0
                    # cache_read + cache_creation 둘 다 청구 대상
                    tok_cache = (
                        (usage.get("cache_read_input_tokens", 0) or 0)
                        + (usage.get("cache_creation_input_tokens", 0) or 0)
                    )
                    totals["input"] += tok_in
                    totals["output"] += tok_out
                    totals["cache"] += tok_cache

                    model_name = message.get("model") or ""
                    if model_name:
                        model_token_counts[model_name] = (
                            model_token_counts.get(model_name, 0) + tok_in + tok_out
                        )
        except OSError:
            continue

    # 가장 많은 토큰을 쓴 모델을 대표 모델로 채택
    if model_token_counts:
        totals["model"] = max(model_token_counts, key=model_token_counts.get)

    return totals


def _truncate(text: str, limit: int, head: bool = True) -> str:
    """Langfuse 전송용 텍스트 자르기. head=False면 꼬리 유지 (대부분의 정보는 stdout 끝에 있음)."""
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= limit:
        return text
    if head:
        return text[:limit] + f"\n\n... (truncated {len(text) - limit} chars)"
    return f"... (truncated {len(text) - limit} chars)\n\n" + text[-limit:]


_DURATION_RE = re.compile(r"\|\s*([\d.]+)s\s*\|")


def parse_cost_log(cost_log_path: Path) -> float:
    """harness-cost-log.txt에서 누적 시간(분) 반환."""
    if not cost_log_path.exists():
        return 0.0
    total_seconds = 0.0
    for line in cost_log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _DURATION_RE.search(line)
        if m:
            total_seconds += float(m.group(1))
    return total_seconds / 60.0


# ── SprintTracer ────────────────────────────────────────────────────────────


class SprintTracer:
    """Langfuse 4.x OTEL 기반. 1 스프린트 = 루트 span, 에이전트별 중첩 span.

    v2.3: 시간 + 토큰 추적, sprint_totals() 메서드 추가.
    """

    def __init__(
        self,
        config,
        sprint_num: int,
        project_name: str,
        cost_log_path: Path,
    ):
        self.sprint_num = sprint_num
        self.project_name = project_name
        self.cost_log_path = cost_log_path
        self.spans: list[dict] = []
        self._lf_client = None
        self._root_span = None
        self._root_cm = None
        self._propagate_cm = None
        self._truncate_chars = int(getattr(config, "langfuse_truncate_chars", 8000))

        if config.langfuse_enabled:
            try:
                from langfuse import Langfuse, propagate_attributes

                self._lf_client = Langfuse(
                    public_key=config.langfuse_public_key,
                    secret_key=config.langfuse_secret_key,
                    host=config.langfuse_host,
                )
                try:
                    auth_ok = self._lf_client.auth_check()
                except Exception as e:
                    sys.stderr.write(f"[forge] Langfuse auth_check failed: {e!r}\n")
                    print(
                        f"[Langfuse] ❌ auth_check 실패: {type(e).__name__}: {e} "
                        f"(host={config.langfuse_host})",
                        flush=True,
                    )
                    auth_ok = False
                if not auth_ok:
                    print(
                        f"[Langfuse] ❌ 인증 실패 → 추적 비활성화 "
                        f"(host={config.langfuse_host}, public_key 앞 8자: "
                        f"{config.langfuse_public_key[:8] if config.langfuse_public_key else 'EMPTY'}...)",
                        flush=True,
                    )
                    self._lf_client = None
                else:
                    print(
                        f"[Langfuse] ✅ 인증 성공 → sprint-{sprint_num} 트레이스 시작 "
                        f"(host={config.langfuse_host}, project={project_name})",
                        flush=True,
                    )
                    from . import __version__

                    self._root_cm = self._lf_client.start_as_current_observation(
                        name=f"sprint-{sprint_num}",
                        as_type="span",
                        metadata={
                            "project": project_name,
                            "sprint": sprint_num,
                            "harness_version": __version__,
                        },
                    )
                    self._root_span = self._root_cm.__enter__()
                    try:
                        # v4: update_current_trace() 제거됨 → propagate_attributes CM으로 대체.
                        # root span 내부에 중첩해야 trace/자식 span에 전파됨.
                        self._propagate_cm = propagate_attributes(
                            trace_name=f"{project_name}-sprint-{sprint_num}",
                            session_id=project_name,
                            user_id=project_name,
                        )
                        self._propagate_cm.__enter__()
                    except Exception as e:
                        sys.stderr.write(f"[forge] Langfuse propagate_attributes failed: {e!r}\n")
                        print(
                            f"[Langfuse] ⚠ propagate_attributes 실패: {type(e).__name__}: {e}",
                            flush=True,
                        )
                        self._propagate_cm = None
            except ImportError as e:
                sys.stderr.write(f"[forge] Langfuse import failed: {e!r}\n")
                print(f"[Langfuse] ❌ import 실패: {e} — pip install langfuse", flush=True)
                self._lf_client = None
            except Exception as e:
                sys.stderr.write(f"[forge] Langfuse init failed: {e!r}\n")
                print(f"[Langfuse] ❌ 초기화 실패: {type(e).__name__}: {e}", flush=True)
                self._lf_client = None
        else:
            print(
                "[Langfuse] ⚪ 비활성 (FORGE_LANGFUSE_PUBLIC_KEY/SECRET_KEY 미설정) — 토큰 추적 생략",
                flush=True,
            )

    @contextmanager
    def span(self, agent_name: str, mode: str = "claude-p") -> Iterator[dict]:
        start = time.time()
        info: dict = {"agent": agent_name, "mode": mode, "start": start, "stdout": ""}
        lf_cm = None
        lf_span = None
        if self._lf_client is not None:
            try:
                # v4: as_type='generation' 이어야 usage_details/cost_details가 집계됨.
                # 'span' 타입은 Langfuse Usage/Cost 컬럼에 반영되지 않음.
                lf_cm = self._lf_client.start_as_current_observation(
                    name=agent_name,
                    as_type="generation",
                    metadata={"mode": mode, "agent": agent_name},
                )
                lf_span = lf_cm.__enter__()
            except Exception:
                lf_cm = None

        error: Optional[BaseException] = None
        try:
            yield info
        except BaseException as e:
            error = e
            raise
        finally:
            duration = time.time() - start
            timestamp = datetime.now().isoformat(timespec="seconds")
            status = "ERROR" if error else "OK"

            # 토큰 추출: jsonl이 가장 정확 (claude -p / interactive 모두 기록됨).
            # stdout 파싱은 fallback으로만 사용.
            tokens = _extract_tokens_from_jsonl(start, time.time())
            if tokens["input"] == 0 and tokens["output"] == 0:
                stdout_tokens = _extract_tokens_from_stdout(info.get("stdout", ""))
                if stdout_tokens["input"] or stdout_tokens["output"]:
                    tokens = {**stdout_tokens, "model": ""}

            info["duration_seconds"] = duration
            info["tokens_input"] = tokens.get("input", 0)
            info["tokens_output"] = tokens.get("output", 0)
            info["tokens_cache"] = tokens.get("cache", 0)
            info["model"] = tokens.get("model", "")
            self.spans.append(info)

            # harness-cost-log.txt 기록 (v2.3 형식: 시간 + 토큰)
            tok_in = info["tokens_input"]
            tok_out = info["tokens_output"]
            line = (
                f"[{timestamp}] sprint-{self.sprint_num} {agent_name:12}"
                f" | {duration:7.1f}s"
                f" | in {tok_in:>9,} / out {tok_out:>7,}"
                f" | {mode:11} | {status}\n"
            )
            self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cost_log_path.open("a", encoding="utf-8") as f:
                f.write(line)

            if lf_span is not None:
                try:
                    # Langfuse v4 usage_details 스펙:
                    # - input/output: generalized 표준 키 (pricing 자동 계산 대상)
                    # - cache_read_input_tokens: Anthropic 원본 키 (Langfuse가 자동 인식)
                    # 공식 참고: LangfuseGeneration.update 시그니처 (input/output/model/
                    # usage_details/metadata 모두 공식 파라미터, v4.5.0 검증됨)
                    update_kwargs: dict = {
                        "usage_details": {
                            "input": tok_in,
                            "output": tok_out,
                            "cache_read_input_tokens": info["tokens_cache"],
                        },
                        "metadata": {
                            "duration_seconds": duration,
                            "status": status,
                        },
                    }
                    # model 있으면 Langfuse가 내장 pricing 테이블로 cost 자동 계산.
                    if info["model"]:
                        update_kwargs["model"] = info["model"]
                    # input: 호출자가 info["input"]에 프롬프트를 기록했으면 전달.
                    limit = self._truncate_chars
                    user_input = info.get("input")
                    if user_input:
                        update_kwargs["input"] = (
                            user_input if limit <= 0 else _truncate(user_input, limit)
                        )
                    # output: stdout 전체는 크므로 꼬리 일부만 (Langfuse UI 가독성 + payload size).
                    stdout_raw = info.get("stdout", "") or ""
                    if stdout_raw:
                        update_kwargs["output"] = (
                            stdout_raw if limit <= 0 else _truncate(stdout_raw, limit, head=False)
                        )
                    lf_span.update(**update_kwargs)
                    has_input = "input" in update_kwargs
                    has_output = "output" in update_kwargs
                    print(
                        f"[Langfuse] ✉ {agent_name} span 전송 "
                        f"(in={tok_in:,}, out={tok_out:,}, "
                        f"cache={info['tokens_cache']:,}, "
                        f"prompt={'Y' if has_input else 'N'}, "
                        f"stdout={'Y' if has_output else 'N'}, "
                        f"model={info['model'] or 'unset'})",
                        flush=True,
                    )
                except Exception as e:
                    sys.stderr.write(f"[forge] Langfuse span.update failed: {e!r}\n")
                    print(
                        f"[Langfuse] ❌ {agent_name} span 전송 실패: {type(e).__name__}: {e}",
                        flush=True,
                    )
            elif self._lf_client is not None:
                print(
                    f"[Langfuse] ⚠ {agent_name} span 누락 — lf_span 초기화 실패",
                    flush=True,
                )
            if lf_cm is not None:
                try:
                    lf_cm.__exit__(type(error), error, error.__traceback__ if error else None)
                except Exception:
                    pass

    def sprint_totals(self) -> dict:
        """v2.3: 이번 스프린트 합계 (Telegram 알림용)."""
        return {
            "duration_seconds": sum(s.get("duration_seconds", 0) for s in self.spans),
            "tokens_input": sum(s.get("tokens_input", 0) for s in self.spans),
            "tokens_output": sum(s.get("tokens_output", 0) for s in self.spans),
            "tokens_cache": sum(s.get("tokens_cache", 0) for s in self.spans),
        }

    def finalize(self, status: str = "completed") -> None:
        if self._root_span is not None:
            try:
                self._root_span.update(metadata={"final_status": status})
            except Exception:
                pass
        # 역순으로 exit: propagate_attributes → root span.
        if self._propagate_cm is not None:
            try:
                self._propagate_cm.__exit__(None, None, None)
            except Exception:
                pass
        if self._root_cm is not None:
            try:
                self._root_cm.__exit__(None, None, None)
            except Exception:
                pass
        if self._lf_client is not None:
            try:
                self._lf_client.flush()
                print(
                    f"[Langfuse] 💾 sprint-{self.sprint_num} flush 완료 "
                    f"(status={status}, spans={len(self.spans)})",
                    flush=True,
                )
            except Exception as e:
                print(
                    f"[Langfuse] ❌ flush 실패: {type(e).__name__}: {e}",
                    flush=True,
                )
