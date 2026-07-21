from eda_studio.state import AppState


class FakeEngine:
    """Mock engine for status_snapshot tests."""

    def total_cost(self):
        return {
            "total_input_tokens": 100,
            "total_output_tokens": 50,
            "total_cache_read_tokens": 10,
            "total_cache_write_tokens": 5,
            "total_reasoning_tokens": 0,
            "total_cost": 0.0025,
            "by_model": {},
        }

    def state(self):
        return "running"

    def current_step(self):
        return "rtl_tx"

    def step_history(self):
        return []


def test_status_snapshot_includes_total_tokens():
    s = AppState()
    s.engine = FakeEngine()
    s.task_running = True
    snap = s.status_snapshot()
    assert snap["total_cost"] == 0.0025
    assert snap["total_tokens"] == {
        "input": 100,
        "output": 50,
        "cache_read": 10,
        "cache_write": 5,
        "reasoning": 0,
    }


def test_status_snapshot_idle_total_tokens_none():
    s = AppState()
    snap = s.status_snapshot()
    assert snap["total_tokens"] is None
    assert snap["total_cost"] is None
