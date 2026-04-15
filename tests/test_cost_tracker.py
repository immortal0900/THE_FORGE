import time

from forge.config import ForgeConfig
from forge.cost_tracker import SprintTracer


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
