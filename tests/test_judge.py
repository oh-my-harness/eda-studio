from eda_studio.judge import make_judge_fn
from eda_studio.config import AppConfig, WorkflowConfig, ShellConfig, DockerConfig

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
def test_rtl_tx_done_when_tool_called():
    judge = make_judge_fn(make_config())
    assert judge(ctx("rtl_tx", tool_calls_count=1)) == "to:rtl_rx"

def test_rtl_tx_retries_when_no_tool():
    judge = make_judge_fn(make_config())
    assert judge(ctx("rtl_tx", tool_calls_count=0)) == "retry"

def test_rtl_tx_aborts_when_retry_exhausted():
    judge = make_judge_fn(make_config(max_fix=2))
    assert judge(ctx("rtl_tx", tool_calls_count=0, retry_count=2)) == "abort:done"

def test_rtl_rx_done_when_tool_called():
    judge = make_judge_fn(make_config())
    assert judge(ctx("rtl_rx", tool_calls_count=1)) == "to:rtl_top"

def test_rtl_rx_retries_when_no_tool():
    judge = make_judge_fn(make_config())
    assert judge(ctx("rtl_rx", tool_calls_count=0)) == "retry"

def test_rtl_top_done_when_tool_called():
    judge = make_judge_fn(make_config())
    assert judge(ctx("rtl_top", tool_calls_count=1)) == "to:simulate"

def test_rtl_top_retries_when_no_tool():
    judge = make_judge_fn(make_config())
    assert judge(ctx("rtl_top", tool_calls_count=0)) == "retry"

def test_simulate_success_to_synthesize():
    judge = make_judge_fn(make_config())
    assert judge(ctx("simulate", success=True)) == "to:synthesize"

def test_simulate_fail_to_debug_fix():
    judge = make_judge_fn(make_config())
    assert judge(ctx("simulate", success=False)) == "to:debug_fix"

def test_simulate_fix_count_exceeds_max_aborts():
    judge = make_judge_fn(make_config(max_fix=2))
    assert judge(ctx("simulate", success=False)) == "to:debug_fix"
    assert judge(ctx("simulate", success=False)) == "to:debug_fix"
    assert judge(ctx("simulate", success=False)) == "abort:done"

def test_simulate_success_resets_count():
    judge = make_judge_fn(make_config(max_fix=2))
    judge(ctx("simulate", success=False))
    judge(ctx("simulate", success=False))
    judge(ctx("simulate", success=True))
    assert judge(ctx("simulate", success=False)) == "to:debug_fix"

def test_debug_fix_to_simulate():
    judge = make_judge_fn(make_config())
    assert judge(ctx("debug_fix")) == "to:simulate"

def test_synthesize_success_to_pnr():
    judge = make_judge_fn(make_config())
    assert judge(ctx("synthesize", success=True)) == "to:pnr"

def test_synthesize_fail_to_debug_fix():
    judge = make_judge_fn(make_config())
    assert judge(ctx("synthesize", success=False)) == "to:debug_fix"

def test_pnr_success_to_drc():
    judge = make_judge_fn(make_config())
    assert judge(ctx("pnr", success=True)) == "to:drc"

def test_pnr_fail_to_drc_fix():
    judge = make_judge_fn(make_config())
    assert judge(ctx("pnr", success=False)) == "to:drc_fix"

def test_pnr_fix_count_exceeds():
    judge = make_judge_fn(make_config(max_fix=1))
    assert judge(ctx("pnr", success=False)) == "to:drc_fix"
    assert judge(ctx("pnr", success=False)) == "abort:done"

def test_drc_fix_to_pnr():
    judge = make_judge_fn(make_config())
    assert judge(ctx("drc_fix")) == "to:pnr"

def test_drc_success_to_gds():
    judge = make_judge_fn(make_config())
    assert judge(ctx("drc", success=True)) == "to:gds"

def test_drc_fail_to_drc_fix():
    judge = make_judge_fn(make_config())
    assert judge(ctx("drc", success=False)) == "to:drc_fix"

def test_gds_done():
    judge = make_judge_fn(make_config())
    assert judge(ctx("gds", success=True)) == "abort:done"

def test_unknown_step_aborts():
    judge = make_judge_fn(make_config())
    assert judge(ctx("unknown")) == "abort:done"
