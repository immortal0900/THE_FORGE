"""SprintTracer — Langfuse Trace/Span + harness-cost-log.txt 자동 기록."""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional


class SprintTracer:
    """Langfuse 4.x OTEL 기반. 1 스프린트 = 루트 span, 에이전트별 중첩 span.

    Langfuse 4.x는 트레이스가 루트 observation이며,
    `start_as_current_observation(as_type='span')`을 컨텍스트 매니저로 사용한다.
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
                    self._root_cm = self._lf_client.start_as_current_observation(
                        name=f"sprint-{sprint_num}",
                        as_type="span",
                        metadata={
                            "project": project_name,
                            "sprint": sprint_num,
                            "harness_version": "2.1.0",
                            "session_id": f"{project_name}-sprint-{sprint_num}",
                        },
                    )
                    self._root_span = self._root_cm.__enter__()
            except ImportError:
                self._lf_client = None
            except Exception:
                self._lf_client = None

    @contextmanager
    def span(self, agent_name: str, mode: str = "claude-p") -> Iterator[None]:
        start = time.time()
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
            yield
        except BaseException as e:
            error = e
            raise
        finally:
            duration = time.time() - start
            timestamp = datetime.now().isoformat(timespec="seconds")
            status = "ERROR" if error else "OK"
            line = (
                f"[{timestamp}] sprint-{self.sprint_num} {agent_name:12} "
                f"| {duration:7.1f}s | {mode:11} | {status}\n"
            )
            self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cost_log_path.open("a", encoding="utf-8") as f:
                f.write(line)
            if lf_span is not None:
                try:
                    lf_span.update(
                        metadata={
                            "duration_seconds": duration,
                            "status": status,
                        }
                    )
                except Exception:
                    pass
            if lf_cm is not None:
                try:
                    lf_cm.__exit__(type(error), error, error.__traceback__ if error else None)
                except Exception:
                    pass

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
