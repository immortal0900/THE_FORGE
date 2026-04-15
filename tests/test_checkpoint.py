from forge.checkpoint import Checkpoint, Phase


def test_default_checkpoint():
    cp = Checkpoint()
    assert cp.phase == Phase.NONE
    assert cp.should_run(Phase.PLANNING)
    assert cp.should_run(Phase.EVALUATING_DONE)


def test_should_run_monotonic():
    cp = Checkpoint(phase=Phase.CONTRACT_DONE)
    assert not cp.should_run(Phase.PLANNING)
    assert not cp.should_run(Phase.CONTRACT)
    assert cp.should_run(Phase.CONTRACT_DONE)
    assert cp.should_run(Phase.GENERATING)


def test_round_trip(tmp_path):
    cp = Checkpoint(phase=Phase.GENERATING, detail="mid-session")
    path = tmp_path / ".harness-checkpoint"
    cp.save(path)
    loaded = Checkpoint.load(path)
    assert loaded.phase == Phase.GENERATING
    assert loaded.detail == "mid-session"
    assert loaded.timestamp


def test_load_missing_returns_default(tmp_path):
    loaded = Checkpoint.load(tmp_path / "missing")
    assert loaded.phase == Phase.NONE


def test_load_corrupted_returns_default(tmp_path):
    path = tmp_path / "bad"
    path.write_text("not json{")
    loaded = Checkpoint.load(path)
    assert loaded.phase == Phase.NONE


def test_advance():
    cp = Checkpoint()
    cp.advance(Phase.PLANNING_DONE, "ready")
    assert cp.phase == Phase.PLANNING_DONE
    assert cp.detail == "ready"
