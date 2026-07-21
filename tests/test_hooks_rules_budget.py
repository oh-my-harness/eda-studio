import logging
from eda_studio.budget import make_budget_cb
from eda_studio.hooks import make_hooks, make_max_tokens_continue_hook
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



def test_max_tokens_auto_continue():
    """MaxTokens 截断时应返回 False(继续),让模型续输。"""
    should_stop = make_max_tokens_continue_hook(max_auto_continue=3)
    ctx = {"stop_reason": "max_tokens"}
    # 前 3 次返回 False(auto-continue)
    assert should_stop(ctx) is False
    assert should_stop(ctx) is False
    assert should_stop(ctx) is False
    # 第 4 次耗尽,返回 True(停止)
    assert should_stop(ctx) is True

def test_non_max_tokens_stops():
    """非 MaxTokens 停止原因 → 正常停止。"""
    should_stop = make_max_tokens_continue_hook()
    assert should_stop({"stop_reason": "end_turn"}) is True
    assert should_stop({"stop_reason": "tool_use"}) is True