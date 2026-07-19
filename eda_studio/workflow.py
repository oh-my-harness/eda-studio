"""workflow 组装:WorkflowEngine 构建。senza 依赖集中在此。

senza API 偏差(以实际 0.4.1 pyi/runtime 为准):
1. create_tool 的 parameters_schema 形参类型是 str(JSON 字符串),不是 dict。
   brief 直接传 dict 会 TypeError;此处用 json.dumps 序列化。
2. workflow_dict 的 edges 中 `to` 必须指向 steps 里已声明的 step_id;
   没有 `done` 这个内置终止 step。终止由 judge 返回 "done" / "abort:done"
   / "fail:<reason>" 实现,不需要 `{"from":...,"to":"done"}` 这样的边。
   因此删除 brief 中的 `{"from":"gds","to":"done"}` 边(gds 之后由
   judge 返回 "done" 终止)。
"""
import json
from pathlib import Path
from senza import (
    WorkflowEngine, create_os_env, create_executor, create_tool,
    create_judge, create_openai_provider, create_anthropic_provider,
    create_pricing_provider,
    create_before_turn_hook, create_after_turn_hook, create_after_tool_call_hook,
    create_should_stop_hook,
    create_shell_executor,
)
from .config import AppConfig
from .prompts import build_prompts, load_requirement
from .judge import make_judge_fn
from .hooks import make_hooks
from .rules import make_rules_hook
from .tools.file_tools import make_file_tools
from .tools.report_tools import make_report_tools
from .executors import (
    simulate_executor, synthesize_executor, pnr_executor,
    drc_executor, gds_executor,
)


def build_providers(config: AppConfig):
    """从 provider_spec/pricing_spec 创建 senza Provider + PricingProvider。"""
    spec = config.provider_spec
    if spec["type"] == "openai":
        provider = create_openai_provider(
            api_key=spec["api_key"], base_url=spec.get("base_url"),
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
    """构建 WorkflowEngine:8 个 step + edges + executors + tools + hooks + budget + rules。"""
    design_dir = Path(f"designs/{design_name}")
    requirement = load_requirement(design_name)
    prompts = build_prompts(requirement)
    provider, pricing = build_providers(config)

    file_tools = make_file_tools(design_dir)
    report_tools = make_report_tools(design_dir)

    # tool 参数 schema(简化的 JSON schema)。create_tool 要求 JSON 字符串。
    WRITE_RTL_SCHEMA = json.dumps({
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "文件名,如 uart_tx.v"},
            "content": {"type": "string", "description": "Verilog 代码内容"},
        },
        "required": ["filename", "content"],
    })
    READ_RTL_SCHEMA = json.dumps({
        "type": "object",
        "properties": {"filename": {"type": "string"}},
        "required": ["filename"],
    })
    NO_ARG_SCHEMA = json.dumps({"type": "object", "properties": {}})
    WRITE_SDC_SCHEMA = json.dumps({
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"],
    })

    workflow_dict = {
        "entry_step": "rtl_design",
        "steps": [
            {"id": "rtl_design", "name": "RTL 设计",
             "prompt": prompts["rtl_design"],
             "allowed_tools": ["write_rtl", "read_rtl", "list_design_files"]},
            {"id": "simulate", "name": "仿真验证", "executor": "simulate"},
            {"id": "debug_fix", "name": "仿真修复",
             "prompt": prompts["debug_fix"],
             "allowed_tools": ["read_sim_report", "read_rtl", "write_rtl"]},
            {"id": "synthesize", "name": "逻辑综合", "executor": "synthesize"},
            {"id": "pnr", "name": "布局布线", "executor": "pnr"},
            {"id": "drc_fix", "name": "DRC 修复",
             "prompt": prompts["drc_fix"],
             "allowed_tools": ["read_drc_report", "read_sdc", "write_sdc", "read_rtl", "write_rtl"]},
            {"id": "drc", "name": "DRC 检查", "executor": "drc"},
            {"id": "gds", "name": "GDS 导出", "executor": "gds"},
        ],
        # edges 覆盖 judge 所有 to: 目标:
        # rtl_design→simulate, simulate→synthesize/debug_fix, debug_fix→simulate,
        # synthesize→pnr/debug_fix, pnr→drc/drc_fix, drc_fix→pnr, drc→gds/drc_fix。
        # gds 之后由 judge 返回 "done" 终止,无需 to:done 边(done 非 step)。
        "edges": [
            {"from": "rtl_design", "to": "simulate"},
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
        ],
    }

    judge = create_judge(make_judge_fn(config))
    env = create_os_env(working_dir=".")
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
        .with_executor("shell", create_shell_executor(["echo", "python3"]))
        # 7 个 tool(闭包从 make_file_tools / make_report_tools 拿)
        .with_tool(create_tool("write_rtl", "写 Verilog 文件", WRITE_RTL_SCHEMA, file_tools["write_rtl"]))
        .with_tool(create_tool("read_rtl", "读 Verilog 文件", READ_RTL_SCHEMA, file_tools["read_rtl"]))
        .with_tool(create_tool("list_design_files", "列出工作区文件", NO_ARG_SCHEMA, file_tools["list_design_files"]))
        .with_tool(create_tool("read_sim_report", "读仿真报告", NO_ARG_SCHEMA, report_tools["read_sim_report"]))
        .with_tool(create_tool("read_drc_report", "读 DRC 报告", NO_ARG_SCHEMA, report_tools["read_drc_report"]))
        .with_tool(create_tool("read_sdc", "读时序约束", NO_ARG_SCHEMA, file_tools["read_sdc"]))
        .with_tool(create_tool("write_sdc", "写时序约束", WRITE_SDC_SCHEMA, file_tools["write_sdc"]))
        .with_hooks(_wrap_hooks(make_hooks(config)))
        .with_task_store(f"designs/{design_name}/.taskstore")
        .with_max_steps(config.workflow_config.max_steps)
    )

    # budget + rules hooks(累加 with_hooks)
    # senza 0.4.1 偏差:WorkflowEngine.with_hooks 只接受 list[Hook],
    # 而 create_budget_exceeded_hook 返回 BudgetExceededHook(非 Hook 子类),
    # 且 WorkflowEngine 没有 .budget()/.pricing() 注册方法(仅 HarnessBuilder 有)。
    # 因此无法直接挂载 BudgetExceededHook。这里把预算超限语义适配为
    # should_stop hook:每轮后用 engine.total_cost() 比对 limit,超限即停。
    # engine 引用在链式构建完成后回填到 _engine_ref,should_stop 闭包通过它
    # 读取实时 cost。
    _engine_ref = []  # 占位,构建完成后回填 engine
    _limit = config.budget_limit
    _continue_on_exceed = config.budget_exceeded_action == "continue"

    def _budget_should_stop(ctx: dict) -> bool:
        eng = _engine_ref[0] if _engine_ref else None
        if eng is None:
            return False
        cost = eng.total_cost().get("total_cost", 0.0)
        if cost > _limit:
            import logging
            logging.getLogger(__name__).warning(
                f"预算超限!已用 ${cost:.2f} / ${_limit:.2f}"
            )
            return not _continue_on_exceed  # stop→True, continue→False
        return False

    budget_hook = create_should_stop_hook(_budget_should_stop)
    rules_hook = make_rules_hook(config)  # create_rule_approval_hook → Hook
    engine = engine.with_hooks([budget_hook, rules_hook])
    _engine_ref.append(engine)  # 回填,供 should_stop 闭包读取

    # context 变量:design_dir / docker_config / shell_config。
    # 不把整个 config 放进 context,避免 API key 落盘到 taskstore。
    # senza 0.4.1 偏差:set_context_variable 要求 JSON 可序列化值,
    # dataclass 实例(DockerConfig/ShellConfig)无法直接序列化,转 dict。
    from dataclasses import asdict
    engine.set_context_variable("design_dir", f"designs/{design_name}")
    engine.set_context_variable("docker_config", asdict(config.docker_config))
    engine.set_context_variable("shell_config", asdict(config.shell_config))

    return engine
