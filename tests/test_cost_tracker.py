import time

from forge.config import ForgeConfig
from forge.cost_tracker import (
    SprintTracer,
    _extract_tokens_from_stdout,
    parse_cost_log,
)


def test_span_appends_to_log(tmp_path):
    config = ForgeConfig()
    log = tmp_path / "harness-cost-log.txt"
    tracer = SprintTracer(config, sprint_num=1, project_name="demo", cost_log_path=log)
    with tracer.span("planner"):
        time.sleep(0.01)
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    assert "sprint-1" in content
    assert "planner" in content
    assert "OK" in content


def test_span_records_error(tmp_path):
    config = ForgeConfig()
    log = tmp_path / "cost.log"
    tracer = SprintTracer(config, 2, "demo", log)
    try:
        with tracer.span("evaluator"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert "ERROR" in log.read_text(encoding="utf-8")


def test_finalize_noop_without_langfuse(tmp_path):
    config = ForgeConfig()
    tracer = SprintTracer(config, 1, "demo", tmp_path / "log")
    tracer.finalize()  # 예외 없어야 함


def test_span_yields_info_dict(tmp_path):
    """v2.3: span()이 info dict를 yield하는지 확인."""
    config = ForgeConfig()
    log = tmp_path / "log.txt"
    tracer = SprintTracer(config, 1, "demo", log)
    with tracer.span("planner") as info:
        assert isinstance(info, dict)
        assert info["agent"] == "planner"
        assert "start" in info
        info["stdout"] = "Tokens: input 1,234 / output 567 / cache 890"
    assert info["tokens_input"] == 1234
    assert info["tokens_output"] == 567
    assert info["tokens_cache"] == 890


def test_extract_tokens_from_stdout():
    """v2.3: stdout 토큰 파싱."""
    stdout = """
Some output...
Tokens: input 45,231 / output 12,456 / cache 3,200
More output...
Tokens: input 100,000 / output 20,000
"""
    tokens = _extract_tokens_from_stdout(stdout)
    # 마지막 매치 사용
    assert tokens["input"] == 100_000
    assert tokens["output"] == 20_000
    assert tokens["cache"] == 0


def test_extract_tokens_empty():
    tokens = _extract_tokens_from_stdout("no token info here")
    assert tokens == {"input": 0, "output": 0, "cache": 0}


def test_sprint_totals(tmp_path):
    """v2.3: sprint_totals() 합산 확인."""
    config = ForgeConfig()
    log = tmp_path / "log.txt"
    tracer = SprintTracer(config, 1, "demo", log)
    with tracer.span("planner") as info:
        info["stdout"] = "Tokens: input 1,000 / output 200 / cache 50"
    with tracer.span("evaluator") as info:
        info["stdout"] = "Tokens: input 2,000 / output 300 / cache 100"
    totals = tracer.sprint_totals()
    assert totals["tokens_input"] == 3000
    assert totals["tokens_output"] == 500
    assert totals["tokens_cache"] == 150
    assert totals["duration_seconds"] >= 0


def test_parse_cost_log(tmp_path):
    """v2.3: 누적 시간 파싱."""
    log = tmp_path / "harness-cost-log.txt"
    log.write_text(
        "[2026-04-15T14:30:00] sprint-1 planner      |   120.0s | in     1,000 / out     200 | claude-p    | OK\n"
        "[2026-04-15T14:32:00] sprint-1 evaluator     |    60.0s | in       500 / out     100 | claude-p    | OK\n",
        encoding="utf-8",
    )
    total_mins = parse_cost_log(log)
    assert total_mins == 3.0  # (120+60)/60


def test_parse_cost_log_missing(tmp_path):
    assert parse_cost_log(tmp_path / "nonexistent.txt") == 0.0


def test_log_format_includes_tokens(tmp_path):
    """v2.3: 로그 라인에 토큰 정보가 포함되는지 확인."""
    config = ForgeConfig()
    log = tmp_path / "log.txt"
    tracer = SprintTracer(config, 1, "demo", log)
    with tracer.span("planner") as info:
        info["stdout"] = "Tokens: input 5,000 / output 1,000"
    content = log.read_text(encoding="utf-8")
    assert "5,000" in content
    assert "1,000" in content
