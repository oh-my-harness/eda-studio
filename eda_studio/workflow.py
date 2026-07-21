"""workflow 组装:WorkflowEngine 构建。senza 依赖集中在此。

senza API 偏差(以实际 pyi/runtime 为准):
1. create_tool 的 parameters_schema 形参类型是 str(JSON 字符串),不是 dict。
   brief 直接传 dict 会 TypeError;此处用 json.dumps 序列化。
2. workflow_dict 的 edges 中 `to` 必须指向 steps 里已声明的 step_id;
   没有 `done` 这个内置终止 step。终止由 judge 返回 "done" / "abort:done"
   / "fail:<reason>" 实现,不需要 `{"from":...,"to":"done"}` 这样的边。
   因此删除 brief 中的 `{"from":"gds","to":"done"}` 边(gds 之后由
   judge 返回 "done" 终止)。
"""
from pathlib import Path
from senza import (
    WorkflowEngine, create_os_env, create_executor,
    create_judge, create_openai_provider, create_anthropic_provider,
    create_pricing_provider, create_fs_tools_plugin,
    create_before_turn_hook, create_after_turn_hook, create_after_tool_call_hook,
    create_after_provider_response_hook,
    create_before_run_hook,
    create_should_stop_hook, create_shell_executor,
)
from .config import AppConfig
from .prompts import build_prompts, load_requirement
from .judge import make_judge_fn
from .hooks import make_hooks, make_provider_response_logger, make_max_tokens_continue_hook
from .plugin import RTL_SYSTEM, DEBUG_FIX_SYSTEM, DRC_FIX_SYSTEM
from .executors import (
    simulate_executor, synthesize_executor, pnr_executor,
    drc_executor, gds_executor, render_executor,
)


def build_providers(config: AppConfig):
    """从 provider_spec/pricing_spec 创建 senza Provider + PricingProvider。"""
    spec = config.provider_spec
    if spec["type"] == "openai":
        provider = create_openai_provider(
            api_key=spec["api_key"], base_url=spec.get("base_url"),
            thinking_scheme="reasoning_effort",  # 与 omp 一致:thinking_level → reasoning_effort
        )
    elif spec["type"] == "anthropic":
        provider = create_anthropic_provider(api_key=spec["api_key"])
    else:
        raise ValueError(f"未知 provider type: {spec['type']}")
    pricing = create_pricing_provider(config.pricing_spec)
    return provider, pricing


def _wrap_hooks(raw_hooks):
    """用 senza 装饰器包装 Task 8 的纯闭包(before_turn/after_turn/after_tool_call)。"""
    before_turn, after_turn, after_tool_call = raw_hooks
    return [
        create_before_turn_hook(before_turn),
        create_after_turn_hook(after_turn),
        create_after_tool_call_hook(after_tool_call),
    ]




def build_workflow(config: AppConfig, design_name: str) -> WorkflowEngine:
    """构建 WorkflowEngine:根据 design_config 动态生成 steps + edges。"""
    design_dir = Path(f"designs/{design_name}").resolve()
    requirement = load_requirement(design_name)
    from .design_config import load_design_config
    dcfg = load_design_config(design_dir)
    prompts = build_prompts(requirement, dcfg.modules)
    provider, pricing = build_providers(config)

    # 内置 FsToolsPlugin 提供 read/write/edit/bash 四件套,替代本地文件工具。
    # read↔edit 通过 FileSnapshotStore 耦合,hashline tag 防止 stale edit。
    fs_plugin = create_fs_tools_plugin()

    # 动态生成 rtl steps(每个模块一个)+ 固定 executor/fix steps
    rtl_steps = []
    for m in dcfg.modules:
        sid = f"rtl_{m.id}"
        rtl_steps.append({
            "id": sid, "name": m.name,
            "prompt": prompts[sid],
            "allowed_tools": ["write", "read", "edit"],
        })
    fixed_steps = [
        {"id": "simulate", "name": "仿真验证", "executor": "simulate"},
        {"id": "debug_fix", "name": "仿真修复",
         "prompt": prompts["debug_fix"],
         "allowed_tools": ["read", "write", "edit"]},  # sim/report.txt + rtl/*.v
        {"id": "synthesize", "name": "逻辑综合", "executor": "synthesize"},
        {"id": "pnr", "name": "布局布线", "executor": "pnr"},
        {"id": "drc_fix", "name": "DRC 修复",
         "prompt": prompts["drc_fix"],
         "allowed_tools": ["read", "write", "edit"]},  # pnr/drc.rpt + pnr/*.sdc + rtl/*.v
        {"id": "drc", "name": "DRC 检查", "executor": "drc"},
        {"id": "gds", "name": "GDS 导出", "executor": "gds"},
        {"id": "render", "name": "渲染预览", "executor": "render"},
    ]
    all_steps = rtl_steps + fixed_steps
    rtl_ids = dcfg.rtl_step_ids

    # 动态生成 edges:
    # rtl_0→rtl_1→...→rtl_last→simulate
    # simulate→synthesize/debug_fix, debug_fix→simulate
    # synthesize→pnr/debug_fix, pnr→drc/drc_fix, drc_fix→pnr, drc→gds/drc_fix, gds→render
    edges = []
    for i in range(len(rtl_ids) - 1):
        edges.append({"from": rtl_ids[i], "to": rtl_ids[i + 1]})
    edges.append({"from": rtl_ids[-1], "to": "simulate"})
    edges.extend([
        {"from": "simulate", "to": "synthesize"},
        {"from": "simulate", "to": "debug_fix"},
        {"from": "debug_fix", "to": "simulate"},
        {"from": "synthesize", "to": "pnr"},
        {"from": "synthesize", "to": "debug_fix"},
        {"from": "pnr", "to": "drc"},
        {"from": "pnr", "to": "drc_fix"},
        {"from": "drc_fix", "to": "pnr"},
        {"from": "drc", "to": "gds"},
        {"from": "drc", "to": "drc_fix"},
        {"from": "gds", "to": "render"},
    ])

    workflow_dict = {
        "entry_step": rtl_ids[0],
        "steps": all_steps,
        "edges": edges,
    }

    judge = create_judge(make_judge_fn(config, rtl_ids=rtl_ids))
    env = create_os_env(working_dir=str(design_dir))
    engine = WorkflowEngine(
        workflow_dict, provider, config.model, judge, env=env,
    )

    engine = (
        engine
        # 5 个 EDA executor + 1 个 shell executor(教学)
        .with_executor("simulate", create_executor(simulate_executor))
        .with_executor("synthesize", create_executor(synthesize_executor))
        .with_executor("pnr", create_executor(pnr_executor))
        .with_executor("drc", create_executor(drc_executor))
        .with_executor("gds", create_executor(gds_executor))
        .with_executor("render", create_executor(render_executor))
        .with_executor("shell", create_shell_executor(["echo", "python3"]))
        .with_hooks(_wrap_hooks(make_hooks(config)))
        .with_task_store(f"designs/{design_name}/.taskstore")
        .with_max_tokens(16384)  # glm-5.2 thinking 动辄 8000+ tokens,8192 全被吃完;adapter timeout 已修复连接超时
        .with_thinking_level("high")  # 与 omp 一致:reasoning_effort=high
        .with_max_retries(config.workflow_config.max_fix_retries)  # judge 返回 "retry" 时的重试上限
    )
    # FsToolsPlugin 通过 with_step_plugin 注册到每个 LLM step。
    # 注意:with_step_plugin 是 insert(覆盖),一个 step 只能有一个 plugin。
    # system_prompt 改用 before_run hook(见下方),不占用 with_step_plugin 槽位。
    for sid in rtl_ids + ["debug_fix", "drc_fix"]:
        engine = engine.with_step_plugin(sid, fs_plugin)

    # MaxTokens auto-continue:thinking 链被截断时让模型续输
    # + provider 响应日志 + system_prompt(通过 before_run hook)
    # system_prompt 用 before_run hook 而非 with_step_plugin(后者是 insert 覆盖)
    def set_system_prompt_cb(ctx: dict):
        prompt_text = ctx.get("prompt_text", "")
        if "DRC" in prompt_text or "drc" in prompt_text:
            sp = DRC_FIX_SYSTEM
        elif "仿真" in prompt_text or "sim" in prompt_text.lower():
            sp = DEBUG_FIX_SYSTEM
        else:
            sp = RTL_SYSTEM
        return {"system_prompt": sp, "additional_messages": []}

    engine = engine.with_hooks([
        create_should_stop_hook(make_max_tokens_continue_hook()),
        create_after_provider_response_hook(make_provider_response_logger()),
        create_before_run_hook(set_system_prompt_cb),
    ])
    # context 变量:design_dir / docker_config / shell_config。
    # 不把整个 config 放进 context,避免 API key 落盘到 taskstore。
    # senza 偏差:set_context_variable 要求 JSON 可序列化值,
    # dataclass 实例(DockerConfig/ShellConfig)无法直接序列化,转 dict。
    from dataclasses import asdict
    engine.set_context_variable("design_dir", f"designs/{design_name}")
    engine.set_context_variable("docker_config", asdict(config.docker_config))
    engine.set_context_variable("shell_config", asdict(config.shell_config))

    return engine
