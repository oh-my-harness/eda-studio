import logging
from eda_studio.budget import make_budget_cb
from eda_studio.hooks import make_hooks
from eda_studio.config import AppConfig, WorkflowConfig, ShellConfig, DockerConfig

def make_config(action="stop"):
    return AppConfig(
        provider_spec={"type": "openai", "api_key": "x", "base_url": None},
        model="gpt-4o",
        pricing_spec={},
        budget_limit=5.0,
        budget_exceeded_action=action,
        workflow_config=WorkflowConfig(max_steps=50, max_fix_retries=3),
        shell_config=ShellConfig(allowed_commands=[], denied_args=[]),
        docker_config=DockerConfig(image="i", container="c", workdir="/w", pdk="sky130A"),
    )

def test_budget_cb_stop_returns_false():
    cb = make_budget_cb(make_config("stop"))
    assert cb({"total_cost": 6.0}, 5.0) is False

def test_budget_cb_continue_returns_true():
    cb = make_budget_cb(make_config("continue"))
    assert cb({"total_cost": 6.0}, 5.0) is True

def test_budget_cb_logs_warning(caplog):
    cb = make_budget_cb(make_config("stop"))
    with caplog.at_level(logging.WARNING):
        cb({"total_cost": 6.0}, 5.0)
    assert any("预算超限" in r.message for r in caplog.records)

def test_make_hooks_returns_three_closures():
    hooks = make_hooks(make_config())
    assert len(hooks) == 3
    assert hooks[0]({"step_id": "x"}) is None
    assert hooks[1]({"step_id": "x", "duration_ms": 10}) is None
    assert hooks[2]({"tool_name": "write_rtl"}) is None
