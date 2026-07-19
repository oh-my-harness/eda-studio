"""judge 逻辑:报告解析 → 路由决策。闭包维护 per-环节 回环计数。"""
from .config import AppConfig


def make_judge_fn(config: AppConfig):
    """构造 judge closure。

    judge ctx 是只读 dict,字段:step_id / output / step_count / retry_count / structured。
    retry_count 是 engine 维护的连续 Retry 次数,只对 "retry" 累加;to: 回环不累加。
    per-环节 回环计数用闭包变量自行维护。
    """
    fix_counts = {"simulate": 0, "pnr": 0, "drc": 0}
    max_fix = config.workflow_config.max_fix_retries

    def judge(ctx: dict) -> str:
        step_id = ctx["step_id"]
        structured = ctx.get("structured") or {}
        success = structured.get("success", False)

        if step_id == "rtl_design":
            return "to:simulate" if ctx.get("output") else "abort:done"

        if step_id == "simulate":
            if success:
                fix_counts["simulate"] = 0
                return "to:synthesize"
            fix_counts["simulate"] += 1
            if fix_counts["simulate"] > max_fix:
                return "abort:done"
            return "to:debug_fix"

        if step_id == "debug_fix":
            return "to:simulate"

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
            return "to:pnr"

        if step_id == "drc":
            if success:
                fix_counts["drc"] = 0
                return "to:gds"
            fix_counts["drc"] += 1
            if fix_counts["drc"] > max_fix:
                return "abort:done"
            return "to:drc_fix"

        if step_id == "gds":
            return "done"

        return "abort:done"

    return judge
