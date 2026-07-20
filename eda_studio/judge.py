"""judge 逻辑:报告解析 → 路由决策。闭包维护 per-环节 回环计数。"""
from .config import AppConfig


def make_judge_fn(config: AppConfig, rtl_ids: list = None):
    """构造 judge closure。

    Args:
        config: AppConfig
        rtl_ids: rtl step id 列表(如 ['rtl_tx','rtl_rx','rtl_top']),
                从 design_config 动态传入。None 时 fallback 到 uart 默认值。

    judge ctx 是只读 dict,字段:step_id / output / step_count / retry_count / structured。
    retry_count 是 engine 维护的连续 Retry 次数,只对 "retry" 累加;to: 回环不累加。
    per-环节 回环计数用闭包变量自行维护。
    """
    if rtl_ids is None:
        rtl_ids = ["rtl_tx", "rtl_rx", "rtl_top"]
    fix_counts = {"simulate": 0, "pnr": 0, "drc": 0}
    max_fix = config.workflow_config.max_fix_retries

    def judge(ctx: dict) -> str:
        step_id = ctx["step_id"]
        structured = ctx.get("structured") or {}
        success = structured.get("success", False)
        tool_calls_count = ctx.get("tool_calls_count", 0)
        retry_count = ctx.get("retry_count", 0)
        import logging
        logging.getLogger(__name__).info(
            f"judge: step={step_id} success={success} tool_calls={tool_calls_count} "
            f"retry={retry_count} structured={structured}"
        )
        # RTL 步骤:模型必须调了工具(write/edit)才算完成。
        # 不用 output 判断 —— runtime FinalAnswer 空文本会覆盖 text_delta。
        # 没调工具就 EndTurn → retry 让模型重试,耗尽则 abort。
        rtl_done = tool_calls_count > 0
        rtl_retry_exhausted = retry_count >= max_fix

        # 动态 rtl 路由:rtl_ids[i] → rtl_ids[i+1],最后一个 → simulate
        if step_id in rtl_ids:
            if not rtl_done:
                return "abort:done" if rtl_retry_exhausted else "retry"
            idx = rtl_ids.index(step_id)
            if idx < len(rtl_ids) - 1:
                return f"to:{rtl_ids[idx + 1]}"
            return "to:simulate"

        if step_id == "simulate":
            if success:
                fix_counts["simulate"] = 0
                return "to:synthesize"
            fix_counts["simulate"] += 1
            if fix_counts["simulate"] > max_fix:
                return "abort:done"
            return "to:debug_fix"

        if step_id == "debug_fix":
            # debug_fix 必须调了工具(读报告/改 RTL)才允许回 simulate 重试
            if tool_calls_count > 0:
                return "to:simulate"
            return "abort:done" if retry_count >= max_fix else "retry"

        if step_id == "synthesize":
            return "to:pnr" if success else "to:debug_fix"

        if step_id == "pnr":
            if success:
                fix_counts["pnr"] = 0
                return "to:drc"
            fix_counts["pnr"] += 1
            if fix_counts["pnr"] > max_fix:
                return "abort:done"
            return "to:drc_fix"

        if step_id == "drc_fix":
            # drc_fix 必须调了工具(读报告/改 SDC/RTL)才允许回 pnr 重试
            if tool_calls_count > 0:
                return "to:pnr"
            return "abort:done" if retry_count >= max_fix else "retry"

        if step_id == "drc":
            if success:
                fix_counts["drc"] = 0
                return "to:gds"
            fix_counts["drc"] += 1
            if fix_counts["drc"] > max_fix:
                return "abort:done"
            return "to:drc_fix"

        if step_id == "gds":
            return "to:render" if success else "abort:done"

        if step_id == "render":
            return "abort:done"

        return "abort:done"

    return judge
