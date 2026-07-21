from eda_studio.config import AppConfig, DockerConfig, ShellConfig, WorkflowConfig
from eda_studio.judge import (
    _debug_fix_handler,
    _drc_fix_handler,
    _drc_handler,
    _gds_handler,
    _pnr_handler,
    _render_handler,
    _rtl_handler,
    _simulate_handler,
    _synthesize_handler,
    make_judge_fn,
)


def make_config(max_fix=3):
    return AppConfig(
        provider_spec={"type": "openai", "api_key": "x", "base_url": None},
        model="gpt-4o",
        pricing_spec={},
        budget_limit=5.0,
        budget_exceeded_action="stop",
        workflow_config=WorkflowConfig(max_steps=50, max_fix_retries=max_fix),
        shell_config=ShellConfig(allowed_commands=[], denied_args=[]),
        docker_config=DockerConfig(image="i", container="c", workdir="/w", pdk="sky130A"),
    )

def ctx(step_id, success=None, output="", retry_count=0, tool_calls_count=0):
    return {"step_id": step_id, "output": output, "step_count": 1, "retry_count": retry_count,
            "tool_calls_count": tool_calls_count,
            "structured": {"success": success} if success is not None else {}}

def _fix_counts():
    return {"simulate": 0, "pnr": 0, "drc": 0}

RTL_IDS = ["rtl_tx", "rtl_rx", "rtl_top"]

def test_rtl_tx_done_when_tool_called():
    assert _rtl_handler(ctx("rtl_tx", tool_calls_count=1), idx=0,
                        rtl_ids=RTL_IDS, max_fix=3) == "to:rtl_rx"

def test_rtl_tx_retries_when_no_tool():
    assert _rtl_handler(ctx("rtl_tx", tool_calls_count=0), idx=0,
                        rtl_ids=RTL_IDS, max_fix=3) == "retry"

def test_rtl_tx_aborts_when_retry_exhausted():
    assert _rtl_handler(ctx("rtl_tx", tool_calls_count=0, retry_count=2),
                        idx=0, rtl_ids=RTL_IDS, max_fix=2) == "abort:done"

def test_rtl_rx_done_when_tool_called():
    assert _rtl_handler(ctx("rtl_rx", tool_calls_count=1), idx=1,
                        rtl_ids=RTL_IDS, max_fix=3) == "to:rtl_top"

def test_rtl_rx_retries_when_no_tool():
    assert _rtl_handler(ctx("rtl_rx", tool_calls_count=0), idx=1,
                        rtl_ids=RTL_IDS, max_fix=3) == "retry"

def test_rtl_top_done_when_tool_called():
    assert _rtl_handler(ctx("rtl_top", tool_calls_count=1), idx=2,
                        rtl_ids=RTL_IDS, max_fix=3) == "to:simulate"

def test_rtl_top_retries_when_no_tool():
    assert _rtl_handler(ctx("rtl_top", tool_calls_count=0), idx=2,
                        rtl_ids=RTL_IDS, max_fix=3) == "retry"

def test_simulate_success_to_synthesize():
    assert _simulate_handler(ctx("simulate", success=True), _fix_counts(), max_fix=3) == "to:synthesize"

def test_simulate_fail_to_debug_fix():
    assert _simulate_handler(ctx("simulate", success=False), _fix_counts(), max_fix=3) == "to:debug_fix"

def test_simulate_fix_count_exceeds_max_aborts():
    fc = _fix_counts()
    assert _simulate_handler(ctx("simulate", success=False), fc, max_fix=2) == "to:debug_fix"
    assert _simulate_handler(ctx("simulate", success=False), fc, max_fix=2) == "to:debug_fix"
    assert _simulate_handler(ctx("simulate", success=False), fc, max_fix=2) == "abort:done"
    assert fc["simulate"] == 3

def test_simulate_success_resets_count():
    fc = _fix_counts()
    _simulate_handler(ctx("simulate", success=False), fc, max_fix=2)
    _simulate_handler(ctx("simulate", success=False), fc, max_fix=2)
    _simulate_handler(ctx("simulate", success=True), fc, max_fix=2)
    assert _simulate_handler(ctx("simulate", success=False), fc, max_fix=2) == "to:debug_fix"
    assert fc["simulate"] == 1

def test_debug_fix_to_simulate_when_tool_called():
    assert _debug_fix_handler(ctx("debug_fix", tool_calls_count=1), max_fix=3) == "to:simulate"

def test_debug_fix_retries_when_no_tool():
    assert _debug_fix_handler(ctx("debug_fix", tool_calls_count=0), max_fix=3) == "retry"

def test_debug_fix_aborts_when_retry_exhausted():
    assert _debug_fix_handler(ctx("debug_fix", tool_calls_count=0, retry_count=2), max_fix=2) == "abort:done"

def test_synthesize_success_to_pnr():
    assert _synthesize_handler(ctx("synthesize", success=True)) == "to:pnr"

def test_synthesize_fail_to_debug_fix():
    assert _synthesize_handler(ctx("synthesize", success=False)) == "to:debug_fix"

def test_pnr_success_to_drc():
    assert _pnr_handler(ctx("pnr", success=True), _fix_counts(), max_fix=3) == "to:drc"

def test_pnr_fail_to_drc_fix():
    assert _pnr_handler(ctx("pnr", success=False), _fix_counts(), max_fix=3) == "to:drc_fix"

def test_pnr_fix_count_exceeds():
    fc = _fix_counts()
    assert _pnr_handler(ctx("pnr", success=False), fc, max_fix=1) == "to:drc_fix"
    assert _pnr_handler(ctx("pnr", success=False), fc, max_fix=1) == "abort:done"
    assert fc["pnr"] == 2

def test_drc_fix_to_pnr_when_tool_called():
    assert _drc_fix_handler(ctx("drc_fix", tool_calls_count=1), max_fix=3) == "to:pnr"

def test_drc_fix_retries_when_no_tool():
    assert _drc_fix_handler(ctx("drc_fix", tool_calls_count=0), max_fix=3) == "retry"

def test_drc_success_to_gds():
    assert _drc_handler(ctx("drc", success=True), _fix_counts(), max_fix=3) == "to:gds"

def test_drc_fail_to_drc_fix():
    assert _drc_handler(ctx("drc", success=False), _fix_counts(), max_fix=3) == "to:drc_fix"

def test_gds_to_render():
    assert _gds_handler(ctx("gds", success=True)) == "to:render"
    assert _gds_handler(ctx("gds", success=False)) == "abort:done"

def test_render_done():
    assert _render_handler(ctx("render", success=True)) == "abort:done"

from senza import CompositeJudge

from eda_studio.judge import KNOWN_FIXED_STEPS


def test_make_judge_fn_returns_composite_judge():
    cj = make_judge_fn(make_config())
    assert isinstance(cj, CompositeJudge)

def test_known_fixed_steps_constant():
    assert KNOWN_FIXED_STEPS == (
        "simulate", "debug_fix", "synthesize",
        "pnr", "drc_fix", "drc", "gds", "render",
    )

import inspect

from eda_studio import judge as judge_module


def test_fallback_returns_sentinel():
    """验证 make_judge_fn 源码中 fallback 返回哨兵字符串。

    CompositeJudge 不可 call、不暴露 dispatch,无法运行时验证 fallback 行为。
    退而验证源码中 fallback lambda 返回 'abort:unknown_step'。
    """
    src = inspect.getsource(judge_module.make_judge_fn)
    assert "abort:unknown_step" in src, "fallback 哨兵字符串缺失,注册测试无法区分已注册/未注册"
