"""judge 逻辑:报告解析 → 路由决策。CompositeJudge 按节点分发,fix_counts 闭包维护 per-环节 回环计数。"""
from senza import CompositeJudge, create_composite_judge

from .config import AppConfig


def _rtl_handler(ctx: dict, idx: int, rtl_ids: list, max_fix: int) -> str:
    """RTL step 路由:模型调了工具才算完成,否则 retry,耗尽 abort。

    计数机制:用 retry_count(engine 维护的连续 Retry 次数)判断耗尽。
    to: 回环不累加 retry_count,但 RTL 链是线性推进不走回环,所以无冲突。

    Args:
        ctx: judge ctx dict(step_id / tool_calls_count / retry_count / structured)
        idx: 当前 step 在 rtl_ids 中的下标
        rtl_ids: rtl step id 列表
        max_fix: 最大重试次数
    """
    tool_calls_count = ctx.get("tool_calls_count", 0)
    retry_count = ctx.get("retry_count", 0)
    if tool_calls_count > 0:
        if idx < len(rtl_ids) - 1:
            return f"to:{rtl_ids[idx + 1]}"
        return "to:simulate"
    return "abort:done" if retry_count >= max_fix else "retry"


def _simulate_handler(ctx: dict, fix_counts: dict, max_fix: int) -> str:
    """simulate 路由:成功 → synthesize(重置计数);失败 → debug_fix(计数++),超限 abort。

    计数机制:用 fix_counts["simulate"](闭包维护),不是 retry_count。
    原因:simulate 失败走 "to:debug_fix" 回环,engine 的 retry_count 只对 "retry" 累加,
    "to:" 回环不累加,故需自行维护 per-环节 计数。

    Args:
        ctx: judge ctx dict
        fix_counts: 共享可变 dict,key="simulate"/"pnr"/"drc",本 handler 读写 "simulate"
        max_fix: 最大修复次数
    """
    structured = ctx.get("structured") or {}
    success = structured.get("success", False)
    if success:
        fix_counts["simulate"] = 0
        return "to:synthesize"
    fix_counts["simulate"] += 1
    if fix_counts["simulate"] > max_fix:
        return "abort:done"
    return "to:debug_fix"


def _debug_fix_handler(ctx: dict, max_fix: int) -> str:
    """debug_fix 路由:调了工具(读报告/改 RTL)才回 simulate,否则 retry,耗尽 abort。

    计数机制:用 retry_count(engine 维护)。debug_fix 走 "retry" 路径,engine 会累加
    retry_count;"to:simulate" 回环不累加,但 debug_fix→simulate 是前进不是回环重试。
    """
    tool_calls_count = ctx.get("tool_calls_count", 0)
    retry_count = ctx.get("retry_count", 0)
    if tool_calls_count > 0:
        return "to:simulate"
    return "abort:done" if retry_count >= max_fix else "retry"


def _synthesize_handler(ctx: dict) -> str:
    """synthesize 路由:成功 → pnr;失败 → debug_fix。无计数。"""
    structured = ctx.get("structured") or {}
    success = structured.get("success", False)
    return "to:pnr" if success else "to:debug_fix"


def _pnr_handler(ctx: dict, fix_counts: dict, max_fix: int) -> str:
    """pnr 路由:成功 → drc(重置计数);失败 → drc_fix(计数++),超限 abort。

    计数机制:用 fix_counts["pnr"](闭包维护),原因同 _simulate_handler。
    """
    structured = ctx.get("structured") or {}
    success = structured.get("success", False)
    if success:
        fix_counts["pnr"] = 0
        return "to:drc"
    fix_counts["pnr"] += 1
    if fix_counts["pnr"] > max_fix:
        return "abort:done"
    return "to:drc_fix"


def _drc_fix_handler(ctx: dict, max_fix: int) -> str:
    """drc_fix 路由:调了工具(读报告/改 SDC/RTL)才回 pnr,否则 retry,耗尽 abort。

    计数机制:用 retry_count(engine 维护),原因同 _debug_fix_handler。
    """
    tool_calls_count = ctx.get("tool_calls_count", 0)
    retry_count = ctx.get("retry_count", 0)
    if tool_calls_count > 0:
        return "to:pnr"
    return "abort:done" if retry_count >= max_fix else "retry"


def _drc_handler(ctx: dict, fix_counts: dict, max_fix: int) -> str:
    """drc 路由:成功 → gds(重置计数);失败 → drc_fix(计数++),超限 abort。

    计数机制:用 fix_counts["drc"](闭包维护),原因同 _simulate_handler。
    """
    structured = ctx.get("structured") or {}
    success = structured.get("success", False)
    if success:
        fix_counts["drc"] = 0
        return "to:gds"
    fix_counts["drc"] += 1
    if fix_counts["drc"] > max_fix:
        return "abort:done"
    return "to:drc_fix"


def _gds_handler(ctx: dict) -> str:
    """gds 路由:成功 → render;失败 → abort。无计数。"""
    structured = ctx.get("structured") or {}
    success = structured.get("success", False)
    return "to:render" if success else "abort:done"


def _render_handler(ctx: dict) -> str:
    """render 路由:恒终止。无计数。"""
    return "abort:done"

KNOWN_FIXED_STEPS = (
    "simulate", "debug_fix", "synthesize",
    "pnr", "drc_fix", "drc", "gds", "render",
)

def make_judge_fn(config: AppConfig, rtl_ids: list = None) -> CompositeJudge:
    """构造 CompositeJudge,按 step 注册独立 handler。

    Args:
        config: AppConfig
        rtl_ids: rtl step id 列表(如 ['rtl_tx','rtl_rx','rtl_top']),
                从 design_config 动态传入。None 时 fallback 到 uart 默认值。

    judge ctx 是只读 dict,字段:step_id / output / step_count / retry_count /
    tool_calls_count / structured。
    retry_count 是 engine 维护的连续 Retry 次数,只对 "retry" 累加;to: 回环不累加。
    per-环节 回环计数用 fix_counts 闭包维护,被 simulate/pnr/drc 三个 handler 共享。
    """
    if rtl_ids is None:
        rtl_ids = ["rtl_tx", "rtl_rx", "rtl_top"]
    max_fix = config.workflow_config.max_fix_retries
    fix_counts = {"simulate": 0, "pnr": 0, "drc": 0}

    cj = create_composite_judge()
    for i, sid in enumerate(rtl_ids):
        cj.on(sid, lambda ctx, i=i: _rtl_handler(ctx, i, rtl_ids, max_fix))
    cj.on("simulate",    lambda ctx: _simulate_handler(ctx, fix_counts, max_fix))
    cj.on("debug_fix",   lambda ctx: _debug_fix_handler(ctx, max_fix))
    cj.on("synthesize",  lambda ctx: _synthesize_handler(ctx))
    cj.on("pnr",         lambda ctx: _pnr_handler(ctx, fix_counts, max_fix))
    cj.on("drc_fix",     lambda ctx: _drc_fix_handler(ctx, max_fix))
    cj.on("drc",         lambda ctx: _drc_handler(ctx, fix_counts, max_fix))
    cj.on("gds",         lambda ctx: _gds_handler(ctx))
    cj.on("render",      lambda ctx: _render_handler(ctx))
    cj.fallback(lambda ctx: "abort:unknown_step")
    return cj
