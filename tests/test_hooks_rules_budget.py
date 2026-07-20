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
    assert hooks[2]({"tool_name": "write"}) == "passthrough"


def test_nudge_turn0_empty_response_returns_false():
    should_stop, _, _ = make_empty_response_nudge_hooks()
    ctx = {"turn_index": 0, "stop_reason": "end_turn", "last_assistant": {"content": []}}
    assert should_stop(ctx) is False  # 继续 turn

def test_nudge_turn0_has_tool_use_returns_true():
    should_stop, _, _ = make_empty_response_nudge_hooks()
    ctx = {"turn_index": 0, "stop_reason": "end_turn",
           "last_assistant": {"content": [{"type": "tool_use", "id": "1", "name": "x"}]}}
    assert should_stop(ctx) is True

def test_nudge_turn_gt0_empty_nudges_again():
    # turn > 0 空响应(无 tool_use) → 继续 nudge(最多 max_nudge 次)
    should_stop, _, _ = make_empty_response_nudge_hooks(max_nudge=3)
    ctx = {"turn_index": 1, "stop_reason": "end_turn", "last_assistant": {"content": []}}
    # 前 3 次返回 False(nudge)
    assert should_stop(ctx) is False
    assert should_stop(ctx) is False
    assert should_stop(ctx) is False
    # 第 4 次耗尽,返回 True(停止)
    assert should_stop(ctx) is True

def test_nudge_max_tokens_auto_continue():
    """MaxTokens 截断时应返回 False(继续),让模型续输。"""
    should_stop, _, _ = make_empty_response_nudge_hooks(max_auto_continue=3)
    ctx = {"turn_index": 0, "stop_reason": "max_tokens", "last_assistant": {"content": []}}
    # 前 3 次返回 False(auto-continue)
    assert should_stop(ctx) is False
    assert should_stop(ctx) is False
    assert should_stop(ctx) is False
    # 第 4 次耗尽,返回 True(停止)
    assert should_stop(ctx) is True

def test_nudge_transform_injects_message():
    should_stop, transform, _ = make_empty_response_nudge_hooks()
    should_stop({"turn_index": 0, "stop_reason": "end_turn", "last_assistant": {"content": []}})
    result = transform({"messages": [{"role": "user", "content": []}], "system_prompt": "x"})
    assert len(result["messages"]) == 2
    assert result["messages"][1]["role"] == "user"
    assert "tool_use" in result["messages"][1]["content"][0]["text"]

def test_nudge_transform_noop_without_should_stop():
    _, transform, _ = make_empty_response_nudge_hooks()
    result = transform({"messages": [{"role": "user", "content": []}], "system_prompt": "x"})
    assert len(result["messages"]) == 1

def test_nudge_reset_clears_count():
    """reset() 后 nudge 计数归零,可以重新 nudge。"""
    should_stop, _, reset = make_empty_response_nudge_hooks(max_nudge=2)
    ctx = {"turn_index": 0, "stop_reason": "end_turn", "last_assistant": {"content": []}}
    # 用完 2 次 nudge
    assert should_stop(ctx) is False
    assert should_stop(ctx) is False
    assert should_stop(ctx) is True  # 耗尽
    # reset 后重新计数
    reset()
    assert should_stop(ctx) is False