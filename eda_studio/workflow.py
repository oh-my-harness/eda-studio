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
import json
from pathlib import Path
from senza import (
    WorkflowEngine, create_os_env, create_executor, create_tool,
    create_judge, create_openai_provider, create_anthropic_provider,
    create_pricing_provider,
    create_before_turn_hook, create_after_turn_hook, create_after_tool_call_hook,
    create_after_provider_response_hook,
    create_should_stop_hook, create_transform_context_hook,
    create_shell_executor,
)
from .config import AppConfig
from .prompts import build_prompts, load_requirement
from .judge import make_judge_fn
from .hooks import make_hooks, make_provider_response_logger, make_empty_response_nudge_hooks
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


def _build_tools(design_dir: Path) -> list:
    """构建 7 个 EDA tool(write/read/list + report + sdc)的 Tool 对象。

    用于 build_workflow 初始构建与 _re_register restore 后重注册:
    WorkflowEngine.restore 清空 extra_tools,需重新 with_tool 注册。
    """
    file_tools = make_file_tools(design_dir)
    report_tools = make_report_tools(design_dir)

    write_rtl_schema = json.dumps({
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "文件名,如 uart_tx.v"},
            "content": {"type": "string", "description": "Verilog 代码内容"},
        },
        "required": ["filename", "content"],
    })
    read_rtl_schema = json.dumps({
        "type": "object",
        "properties": {"filename": {"type": "string"}},
        "required": ["filename"],
    })
    no_arg_schema = json.dumps({"type": "object", "properties": {}})
    write_sdc_schema = json.dumps({
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"],
    })

    return [
        create_tool("write_rtl", "写 Verilog 文件", write_rtl_schema, file_tools["write_rtl"]),
        create_tool("read_rtl", "读 Verilog 文件", read_rtl_schema, file_tools["read_rtl"]),
        create_tool("list_design_files", "列出工作区文件", no_arg_schema, file_tools["list_design_files"]),
        create_tool("read_sim_report", "读仿真报告", no_arg_schema, report_tools["read_sim_report"]),
        create_tool("read_drc_report", "读 DRC 报告", no_arg_schema, report_tools["read_drc_report"]),
        create_tool("read_sdc", "读时序约束", no_arg_schema, file_tools["read_sdc"]),
        create_tool("write_sdc", "写时序约束", write_sdc_schema, file_tools["write_sdc"]),
    ]


def build_workflow(config: AppConfig, design_name: str) -> WorkflowEngine:
    """构建 WorkflowEngine:10 个 step + edges + executors + tools + hooks + budget + rules。"""
    design_dir = Path(f"designs/{design_name}")
    requirement = load_requirement(design_name)
    prompts = build_prompts(requirement)
    provider, pricing = build_providers(config)

    tool_specs = _build_tools(design_dir)

    workflow_dict = {
        "entry_step": "rtl_tx",
        "steps": [
            {"id": "rtl_tx", "name": "UART 发送器设计",
             "prompt": prompts["rtl_tx"],
             "allowed_tools": ["write_rtl", "read_rtl", "list_design_files"]},
            {"id": "rtl_rx", "name": "UART 接收器设计",
             "prompt": prompts["rtl_rx"],
             "allowed_tools": ["write_rtl", "read_rtl", "list_design_files"]},
            {"id": "rtl_top", "name": "顶层模块设计",
             "prompt": prompts["rtl_top"],
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
        # rtl_tx→rtl_rx, rtl_rx→rtl_top, rtl_top→simulate,
        # simulate→synthesize/debug_fix, debug_fix→simulate,
        # synthesize→pnr/debug_fix, pnr→drc/drc_fix, drc_fix→pnr, drc→gds/drc_fix。
        # gds 之后由 judge 返回 "done" 终止,无需 to:done 边(done 非 step)。
        "edges": [
            {"from": "rtl_tx", "to": "rtl_rx"},
            {"from": "rtl_rx", "to": "rtl_top"},
            {"from": "rtl_top", "to": "simulate"},
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
        # 7 个 tool(从 _build_tools 拿已构建好的 Tool 对象)
        .with_tool(tool_specs[0])
        .with_tool(tool_specs[1])
        .with_tool(tool_specs[2])
        .with_tool(tool_specs[3])
        .with_tool(tool_specs[4])
        .with_tool(tool_specs[5])
        .with_tool(tool_specs[6])
        .with_hooks(_wrap_hooks(make_hooks(config)))
        .with_task_store(f"designs/{design_name}/.taskstore")
        .with_max_tokens(32768)  # glm-5.2 thinking ~8K token,默认 8192 会截断导致 content/tool_call 无法输出
        .with_max_retries(config.workflow_config.max_fix_retries)  # judge 返回 "retry" 时的重试上限
    )

    # 空响应纠正:模型 EndTurn 没调工具 → should_stop 返回 False(继续 turn)
    # + transform_context 注入 nudge(响应式反馈)。有 max_retries 兜底。
    should_stop_cb, nudge_transform_cb = make_empty_response_nudge_hooks(
        max_retries=config.workflow_config.max_fix_retries
    )
    # provider 响应日志:记录 HTTP 状态码/延迟/token 用量(诊断用)
    engine = engine.with_hooks([
        create_should_stop_hook(should_stop_cb),
        create_transform_context_hook(nudge_transform_cb),
        create_after_provider_response_hook(make_provider_response_logger()),
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
