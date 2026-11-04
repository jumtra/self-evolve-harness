from runner import run

STEPS = [{"id": f"s{i}", "cost": 2} for i in range(1, 5)]


def test_budget_is_never_exceeded(tmp_path):
    executed = []
    result = run(STEPS, 5, str(tmp_path / "state.json"), executed.append)
    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["spent"] <= 5
    assert executed == ["s1", "s2"]


def test_resume_does_not_repeat_completed_steps(tmp_path):
    state = str(tmp_path / "state.json")
    run(STEPS, 5, state, lambda _id: None)
    executed = []
    result = run(STEPS, 10, state, executed.append)
    assert executed == ["s3", "s4"]
    assert result["status"] == "COMPLETED"
    assert result["done"] == ["s1", "s2", "s3", "s4"]
