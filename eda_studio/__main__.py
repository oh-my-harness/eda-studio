"""CLI 入口:run / restore / status。

Usage:
  python -m eda_studio run <design> [--config config.yaml]
  python -m eda_studio restore <design> [--config config.yaml]
  python -m eda_studio status <design>

senza 0.4.1 API 偏差(以实际 pyi/runtime 为准):
1. WorkflowEngine.total_cost() 返回 dict(含 total_cost 字段),非 float。
   cmd_run 用 .get("total_cost", 0.0) 取值;PricingProvider 无处挂载到
   WorkflowEngine(仅 HarnessBuilder 有 .pricing()),因此实际值常为 0.0
   ——这是已知 SDK 限制,不修复。
2. set_context_variable 要求 JSON 可序列化值,dataclass 实例需 asdict()。
3. WorkflowEngine.restore 是 classmethod,签名:
   restore(task_store_dir, task_id, provider, model, judge,
           session_base_dir="sessions", env=None)
   brief 调用 WorkflowEngine.restore(store_dir, task_id, provider=...,
   model=..., judge=..., env=env) 匹配。
4. BudgetExceededHook 非 Hook 子类,无法用 with_hooks 挂载;沿用 workflow.py
   的 should_stop 适配方案(_re_register 不再注册 budget hook,restore 后
   budget 检查复用同款 should_stop 逻辑由 build_workflow 已建立的 taskstore
   之外——此处仅恢复 executors/rules/context,budget 由 runtime 内置记账)。
"""
import sys
from dataclasses import asdict
from pathlib import Path
from senza import (
    WorkflowEngine, create_os_env, create_executor, create_judge,
    create_should_stop_hook, create_shell_executor,
)
from .config import load_config
from .workflow import build_workflow, build_providers, _wrap_hooks, _build_tools
from .judge import make_judge_fn
from .hooks import make_hooks
from .executors import (
    simulate_executor, synthesize_executor, pnr_executor,
    drc_executor, gds_executor,
)


def _re_register(engine, config, design_name):
    """restore 后重新注册 executors/hooks/tools/context 变量。

    WorkflowEngine.restore 只恢复 workflow 定义与 taskstore 状态,
    不恢复 with_executor/with_tool/with_hooks/set_context_variable 的注册,
    且 restore 会清空 extra_tools(engine.rs:491/561 extra_tools: vec![]),
    需在此重新挂载——否则 LLM step 的 allowed_tools 找不到 tool 实现。
    """
    design_dir = Path(f"designs/{design_name}")
    tools = _build_tools(design_dir)
    engine = (engine
        .with_executor("simulate", create_executor(simulate_executor))
        .with_executor("synthesize", create_executor(synthesize_executor))
        .with_executor("pnr", create_executor(pnr_executor))
        .with_executor("drc", create_executor(drc_executor))
        .with_executor("gds", create_executor(gds_executor))
        .with_executor("shell", create_shell_executor(["echo", "python3"]))
        # restore 清空 extra_tools,需重新注册 7 个 tool
        .with_tool(tools[0])
        .with_tool(tools[1])
        .with_tool(tools[2])
        .with_tool(tools[3])
        .with_tool(tools[4])
        .with_tool(tools[5])
        .with_tool(tools[6])
        .with_hooks(_wrap_hooks(make_hooks(config)))
    )

    # budget:restore 后用 should_stop 适配(senza 无 BudgetExceededHook 挂载点)
    _engine_ref = []
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
            return not _continue_on_exceed
        return False

    budget_hook = create_should_stop_hook(_budget_should_stop)
    engine = engine.with_hooks([budget_hook])
    _engine_ref.append(engine)

    # context 变量:dataclass 需 asdict 才能 JSON 序列化
    engine.set_context_variable("design_dir", f"designs/{design_name}")
    engine.set_context_variable("docker_config", asdict(config.docker_config))
    engine.set_context_variable("shell_config", asdict(config.shell_config))
    return engine


def cmd_run(design_name: str, config_path: str):
    config = load_config(config_path)
    engine = build_workflow(config, design_name)
    print(f"启动 {design_name} 设计流程...")
    engine.run()
    print(f"流程结束,state={engine.state()}")
    # total_cost() 返回 dict;PricingProvider 无处挂载时常为 0.0(已知 SDK 限制)
    cost = engine.total_cost().get("total_cost", 0.0)
    print(f"总成本: ${cost:.4f}")
    print(f"已完成 {len(engine.step_history())} 步")
    gds = Path(f"designs/{design_name}/gds/uart.gds")
    if gds.exists():
        print(f"✓ GDS 产物: {gds}")
    else:
        print(f"✗ 未产出 GDS")


def cmd_restore(design_name: str, config_path: str):
    config = load_config(config_path)
    store_dir = f"designs/{design_name}/.taskstore"
    task_id_file = Path(store_dir) / "task_id"
    if not task_id_file.exists():
        print(f"未找到 taskstore: {task_id_file}")
        sys.exit(1)
    task_id = task_id_file.read_text().strip()

    env = create_os_env(working_dir=".")
    provider, _pricing = build_providers(config)
    engine = WorkflowEngine.restore(
        store_dir, task_id,
        provider=provider,
        model=config.model,
        judge=create_judge(make_judge_fn(config)),
        env=env,
    )
    engine = _re_register(engine, config, design_name)
    print(f"恢复到步骤: {engine.current_step()}")
    print(f"已完成: {len(engine.step_history())} 步")
    engine.run()
    print(f"流程结束,state={engine.state()}")


def cmd_status(design_name: str):
    store_dir = f"designs/{design_name}/.taskstore"
    task_id_file = Path(store_dir) / "task_id"
    if not task_id_file.exists():
        print(f"未找到 taskstore: {task_id_file}")
        return
    task_id = task_id_file.read_text().strip()
    print(f"design={design_name} task_id={task_id} store={store_dir}")


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="eda-studio")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="运行设计流程")
    p_run.add_argument("design")
    p_run.add_argument("--config", default="config.yaml")
    p_restore = sub.add_parser("restore", help="从断点恢复")
    p_restore.add_argument("design")
    p_restore.add_argument("--config", default="config.yaml")
    p_status = sub.add_parser("status", help="查看状态")
    p_status.add_argument("design")

    args = parser.parse_args(argv)
    if args.command == "run":
        cmd_run(args.design, args.config)
    elif args.command == "restore":
        cmd_restore(args.design, args.config)
    elif args.command == "status":
        cmd_status(args.design)


if __name__ == "__main__":
    main()
