"""CLI 入口:run / restore / status。

Usage:
  python -m eda_studio run <design> [--config config.yaml]
  python -m eda_studio restore <design> [--config config.yaml]
  python -m eda_studio status <design>

senza API 偏差(以实际 pyi/runtime 为准):
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
4. budget 由 runtime 内置记账,不在应用层挂 hook(should_stop 做预算
   控制会让 EndTurn 后无限继续 turn)。
"""
import sys
from dataclasses import asdict
from pathlib import Path
from senza import (
    WorkflowEngine, create_os_env, create_executor, create_judge,
    create_fs_tools_plugin, create_before_run_hook,
    create_should_stop_hook, create_transform_context_hook,
)
from .workflow import build_workflow, build_providers, _wrap_hooks
from .judge import make_judge_fn
from .hooks import make_hooks, make_provider_response_logger, make_empty_response_nudge_hooks
from .executors import (
    simulate_executor, synthesize_executor, pnr_executor,
    drc_executor, gds_executor,
)


def _re_register(engine, config, design_name, rtl_ids):
    """restore 后重新注册 executors/hooks/plugin/context 变量。

    WorkflowEngine.restore 只恢复 workflow 定义与 taskstore 状态,
    不恢复 with_executor/with_step_plugin/with_hooks/set_context_variable
    的注册,需在此重新挂载——否则 LLM step 的 allowed_tools 找不到 tool 实现。
    """
    design_dir = Path(f"designs/{design_name}").resolve()
    fs_plugin = create_fs_tools_plugin()
    engine = (engine
        .with_executor("simulate", create_executor(simulate_executor))
        .with_executor("synthesize", create_executor(synthesize_executor))
        .with_executor("pnr", create_executor(pnr_executor))
        .with_executor("drc", create_executor(drc_executor))
        .with_executor("gds", create_executor(gds_executor))
        .with_executor("shell", create_shell_executor(["echo", "python3"]))
        # 内置 fs tools 注册到每个 LLM step
        .with_step_plugin(rtl_ids[0], fs_plugin)
        .with_hooks(_wrap_hooks(make_hooks(config)))
    )
    for sid in rtl_ids[1:] + ["debug_fix", "drc_fix"]:
        engine = engine.with_step_plugin(sid, fs_plugin)
    # 空响应纠正 + provider 日志 + system_prompt(同 build_workflow)
    should_stop_cb, nudge_transform_cb, reset_nudge = make_empty_response_nudge_hooks()
    from .plugin import RTL_SYSTEM, DEBUG_FIX_SYSTEM, DRC_FIX_SYSTEM
    def set_system_prompt_cb(ctx: dict):
        reset_nudge()
        prompt_text = ctx.get("prompt_text", "")
        if "DRC" in prompt_text or "drc" in prompt_text:
            sp = DRC_FIX_SYSTEM
        elif "仿真" in prompt_text or "sim" in prompt_text.lower():
            sp = DEBUG_FIX_SYSTEM
        else:
            sp = RTL_SYSTEM
        return {"system_prompt": sp, "additional_messages": []}
    engine = engine.with_hooks([
        create_should_stop_hook(should_stop_cb),
        create_transform_context_hook(nudge_transform_cb),
        create_after_provider_response_hook(make_provider_response_logger()),
        create_before_run_hook(set_system_prompt_cb),
    ])

    # context 变量:dataclass 需 asdict 才能 JSON 序列化
    engine.set_context_variable("design_dir", f"designs/{design_name}")
    engine.set_context_variable("docker_config", asdict(config.docker_config))
    engine.set_context_variable("shell_config", asdict(config.shell_config))
    return engine


def _print_event(event: dict) -> None:
    """将 WorkflowEvent dict 实时打印到终端。"""
    if not isinstance(event, dict):
        return
    etype = event.get("type")
    if etype == "step_started":
        print(f"\n▶ {event.get('step_name', event.get('step_id', '?'))} 开始")
    elif etype == "step_finished":
        print(f"✓ {event.get('step_name', event.get('step_id', '?'))} 完成")
    elif etype == "step_progress":
        prog = event.get("progress") or {}
        ptype = prog.get("type")
        if ptype == "tool_call_start":
            print(f"  🔧 调用工具: {prog.get('name', '?')}")
        elif ptype == "tool_execution_end":
            ok = prog.get("ok", False)
            if ok:
                print(f"  ✓ 工具完成: {prog.get('tool_name', '?')}")
            else:
                err = prog.get("error") or "未知错误"
                print(f"  ✗ 工具失败: {prog.get('tool_name', '?')} — {err}")
        elif ptype == "message_end":
            kind = (prog.get("kind") or "").lower()
            if "progress" in kind:
                print(f"  💭 模型思考中...")
    elif etype == "paused":
        print(f"⏸ 暂停: {event.get('reason', '')}")
    elif etype == "resumed":
        print(f"▶ 恢复")
    elif etype == "failed":
        print(f"✗ 失败: {event.get('error', '')}")
    elif etype == "cancelled":
        print(f"✗ 取消: {event.get('reason', '')}")


def _run_with_events(engine, design_name: str) -> None:
    """后台线程跑 engine.run(),主线程迭代 subscribe() 实时打印事件。

    engine.run() 阻塞(senza 内部 rt.block_on),必须放后台线程。
    subscribe() 返回 WorkflowEventIterator,同一 engine 实例的 broadcast channel。
    """
    import threading, time
    done = threading.Event()
    error_box = []

    def _runner():
        try:
            engine.run()
        except Exception as e:
            error_box.append(e)
        finally:
            done.set()

    # subscribe 必须在 run() 之前调用,否则早期事件会被 broadcast channel 丢弃
    iterator = engine.subscribe(timeout_ms=1000)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()

    # 主线程:迭代事件直到 run() 结束
    while not done.is_set():
        try:
            ev = next(iterator)
            if ev is not None:
                _print_event(ev)
        except StopIteration:
            # senza iterator 超时也抛 StopIteration —— 不退出,继续轮询
            # 只有 done.is_set()(run() 结束)才退出
            time.sleep(0.2)
        except Exception:
            # 其他异常 —— 忽略,继续轮询
            time.sleep(0.2)

    thread.join(timeout=5)
    if error_box:
        raise error_box[0]


def _print_run_summary(design_name: str) -> None:
    """workflow 结束后打印每个 step 的状态表。

    从 taskstore workflow.json 读 step_history。
    """
    import json
    store_dir = Path(f"designs/{design_name}/.taskstore")
    task_id_file = store_dir / "task_id"
    if not task_id_file.exists():
        print(f"未找到 taskstore: {store_dir}")
        return
    task_id = task_id_file.read_text().strip()
    wf_file = store_dir / task_id / "workflow.json"
    if not wf_file.exists():
        print(f"未找到 workflow.json: {wf_file}")
        return
    wf = json.loads(wf_file.read_text())
    status = wf.get("status", "unknown")
    history = wf.get("step_history", [])

    print(f"\n═══ Workflow 完成 ({status}) ═══")
    for step in history:
        sid = step["step_id"]
        result = step.get("result", {})
        structured = result.get("structured") or {}
        success = structured.get("success")
        output = result.get("output", "")
        cost = result.get("cost") or {}
        in_tok = cost.get("total_input_tokens", 0)
        out_tok = cost.get("total_output_tokens", 0)

        if success is None:
            # LLM step:有 tool_calls 算成功
            success = result.get("tool_calls_count", 0) > 0

        mark = "✓" if success else "✗"
        if in_tok > 0 or out_tok > 0:
            detail = f"{in_tok//1000}k↓ {out_tok//1000}k↑"
        else:
            detail = "executor"
        line = f"  {sid:<12} {mark}  {detail}"
        if not success and output:
            # 错误摘要:取最后一行非空、非 [INFO] 的内容
            lines = [l for l in output.split("\n") if l.strip() and not l.startswith("[INFO]")]
            err = lines[-1][:70] if lines else output[:70]
            line += f"  ← {err}"
        print(line)

def cmd_run(design_name: str, config_path: str):
    import logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = load_config(config_path)
    engine = build_workflow(config, design_name)
    print(f"启动 {design_name} 设计流程...")
    _run_with_events(engine, design_name)
    print(f"\n流程结束,state={engine.state()}")
    cost = engine.total_cost().get("total_cost", 0.0)
    print(f"总成本: ${cost:.4f}")
    print(f"已完成 {len(engine.step_history())} 步")
    gds = Path(f"designs/{design_name}/gds/uart.gds")
    if gds.exists():
        print(f"✓ GDS 产物: {gds}")
    else:
        print(f"✗ 未产出 GDS")
    _print_run_summary(design_name)


def cmd_restore(design_name: str, config_path: str):
    config = load_config(config_path)
    store_dir = f"designs/{design_name}/.taskstore"
    task_id_file = Path(store_dir) / "task_id"
    if not task_id_file.exists():
        print(f"未找到 taskstore: {task_id_file}")
        sys.exit(1)
    task_id = task_id_file.read_text().strip()

    env = create_os_env(working_dir=str(Path(f"designs/{design_name}").resolve()))
    provider, _pricing = build_providers(config)
    from .design_config import load_design_config
    from pathlib import Path as _Path
    dcfg = load_design_config(_Path(f"designs/{design_name}"))
    engine = WorkflowEngine.restore(
        store_dir, task_id,
        provider=provider,
        model=config.model,
        judge=create_judge(make_judge_fn(config, rtl_ids=dcfg.rtl_step_ids)),
        env=env,
    )
    engine = _re_register(engine, config, design_name, dcfg.rtl_step_ids)
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


def cmd_serve(config_path: str, port: int, host: str = "0.0.0.0"):
    """启动 Web UI(uvicorn + FastAPI)。"""
    from .main import run_server
    run_server(config_path, host, port)


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
    p_serve = sub.add_parser("serve", help="启动 Web UI")
    p_serve.add_argument("--config", default="config.yaml")
    p_serve.add_argument("--port", type=int, default=3000)
    p_serve.add_argument("--host", default="0.0.0.0")
    p_init = sub.add_parser("init", help="初始化 design(从模板复制)")
    p_init.add_argument("design")
    p_check = sub.add_parser("check", help="预检环境(config/API/docker/PDK)")
    p_check.add_argument("--config", default="config.yaml")


    args = parser.parse_args(argv)
    if args.command == "run":
        cmd_run(args.design, args.config)
    elif args.command == "restore":
        cmd_restore(args.design, args.config)
    elif args.command == "status":
        cmd_status(args.design)
    elif args.command == "serve":
        cmd_serve(args.config, args.port, args.host)
    elif args.command == "init":
        from .cli_commands import cmd_init
        sys.exit(cmd_init(args.design))
    elif args.command == "check":
        from .cli_commands import cmd_check
        sys.exit(cmd_check(args.config))


if __name__ == "__main__":
    main()
