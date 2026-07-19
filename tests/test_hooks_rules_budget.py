import logging
from eda_studio.budget import make_budget_cb
from eda_studio.hooks import make_hooks, make_empty_response_nudge_hooks
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
    assert hooks[0]({"turn_index": 0}) is None
    assert hooks[1]({"turn_index": 0}) is None
    assert hooks[2]({"tool_name": "write_rtl"}) == "passthrough"


def test_nudge_turn0_empty_response_returns_false():
    should_stop, _ = make_empty_response_nudge_hooks()
    ctx = {"turn_index": 0, "stop_reason": "end_turn", "last_assistant": {"content": []}}
    assert should_stop(ctx) is False  # 继续 turn

def test_nudge_turn0_has_tool_use_returns_true():
    should_stop, _ = make_empty_response_nudge_hooks()
    ctx = {"turn_index": 0, "stop_reason": "end_turn",
           "last_assistant": {"content": [{"type": "tool_use", "id": "1", "name": "x"}]}}
    assert should_stop(ctx) is True

def test_nudge_turn_gt0_empty_returns_true():
    # turn > 0 的 EndTurn 是正常完成(前面 turn 已调过工具)
    should_stop, _ = make_empty_response_nudge_hooks()
    ctx = {"turn_index": 1, "stop_reason": "end_turn", "last_assistant": {"content": []}}
    assert should_stop(ctx) is True

def test_nudge_max_tokens_returns_true():
    should_stop, _ = make_empty_response_nudge_hooks()
    ctx = {"turn_index": 0, "stop_reason": "max_tokens", "last_assistant": {"content": []}}
    assert should_stop(ctx) is True

def test_nudge_transform_injects_message():
    should_stop, transform = make_empty_response_nudge_hooks()
    should_stop({"turn_index": 0, "stop_reason": "end_turn", "last_assistant": {"content": []}})
    result = transform({"messages": [{"role": "user", "content": []}], "system_prompt": "x"})
    assert len(result["messages"]) == 2
    assert result["messages"][1]["role"] == "user"
    assert "tool_use" in result["messages"][1]["content"][0]["text"]

def test_nudge_transform_noop_without_should_stop():
    _, transform = make_empty_response_nudge_hooks()
    result = transform({"messages": [{"role": "user", "content": []}], "system_prompt": "x"})
    assert len(result["messages"]) == 1