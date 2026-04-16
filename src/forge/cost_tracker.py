"""SprintTracer — Langfuse Trace/Span + harness-cost-log.txt + 토큰 추적 (v2.3)."""

from __future__ import annotations

import json
import re
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


def _extract_tokens_from_jsonl(since: float, until: float) -> dict:
    """interactive 세션용: ~/.claude/projects/ JSONL에서 시간 범위 내 토큰 합산."""
    claude_home = Path.home() / ".claude" / "projects"
    totals = {"input": 0, "output": 0, "cache": 0}
    if not claude_home.exists():
        return totals

    cwd = str(Path.cwd().resolve()).lower()
    project_id = re.sub(r"[:\\/._]", "-", cwd)
    session_dir = claude_home / project_id
    if not session_dir.exists():
        return totals

    for jsonl_file in session_dir.glob("*.jsonl"):
        try:
            with open(jsonl_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        ts = record.get("timestamp", 0)
                        if not (since <= ts <= until):
                            continue
                        if record.get("type") != "assistant":
                            continue
                        usage = record.get("message", {}).get("usage", {})
                        totals["input"] += usage.get("input_tokens", 0)
                        totals["output"] += usage.get("output_tokens", 0)
                        totals["cache"] += usage.get("cache_read_input_tokens", 0)
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
        except OSError:
            continue

    return totals


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

        if config.langfuse_enabled:
            try:
                from langfuse import Langfuse

                self._lf_client = Langfuse(
                    public_key=config.langfuse_public_key,
                    secret_key=config.langfuse_secret_key,
                    host=config.langfuse_host,
                )
                if not self._lf_client.auth_check():
                    self._lf_client = None
                else:
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
                        self._lf_client.update_current_trace(
                            name=f"{project_name}-sprint-{sprint_num}",
                            session_id=project_name,
                            user_id=project_name,
                        )
                    except Exception:
                        pass
            except ImportError:
                self._lf_client = None
            except Exception:
                self._lf_client = None

    @contextmanager
    def span(self, agent_name: str, mode: str = "claude-p") -> Iterator[dict]:
        start = time.time()
        info: dict = {"agent": agent_name, "mode": mode, "start": start, "stdout": ""}
        lf_cm = None
        lf_span = None
        if self._lf_client is not None:
            try:
                lf_cm = self._lf_client.start_as_current_observation(
                    name=agent_name,
                    as_type="span",
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

            # v2.3: 토큰 추출
            if mode == "interactive":
                tokens = _extract_tokens_from_jsonl(start, time.time())
            else:
                tokens = _extract_tokens_from_stdout(info.get("stdout", ""))

            info["duration_seconds"] = duration
            info["tokens_input"] = tokens.get("input", 0)
            info["tokens_output"] = tokens.get("output", 0)
            info["tokens_cache"] = tokens.get("cache", 0)
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
                    lf_span.update(
                        usage_details={
                            "input": tok_in,
                            "output": tok_out,
                            "cache_read": info["tokens_cache"],
                        },
                        metadata={
                            "duration_seconds": duration,
                            "status": status,
                        },
                    )
                except Exception:
                    pass
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
        if self._root_cm is not None:
            try:
                self._root_cm.__exit__(None, None, None)
            except Exception:
                pass
        if self._lf_client is not None:
            try:
                self._lf_client.flush()
            except Exception:
                pass
