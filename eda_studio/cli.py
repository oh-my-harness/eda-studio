"""EDA Studio CLI:run / restore / status / serve / init / check 子命令。

合并自原 __main__.py + cli_commands.py + main.py,集中 CLI 入口便于维护。

Usage:
  eda-studio run <design> [--config config.yaml]
  eda-studio restore <design> [--config config.yaml]
  eda-studio status <design>
  eda-studio serve [--config config.yaml] [--port 3000] [--host 0.0.0.0]
  eda-studio init <design>
  eda-studio check [--config config.yaml]

senza API 偏差(以实际 pyi/runtime 为准):
1. WorkflowEngine.total_cost() 返回 dict(含 total_cost 字段),非 float。
   cmd_run 用 .get("total_cost", 0.0) 取值。PricingProvider 通过
   WorkflowEngine.with_pricing() 挂载(Senza #20 修复),build_workflow
   已调用,total_cost 反映真实成本。
2. set_context_variable 要求 JSON 可序列化值,dataclass 实例需 asdict()。
3. WorkflowEngine.restore 是 classmethod,签名:
   restore(task_store_dir, task_id, provider, model, judge,
           session_base_dir="sessions", env=None)
4. config.yaml 的 budget 字段(limit/exceeded_action)当前未在应用层挂 hook,
   AppConfig 保留字段供未来用 create_budget_exceeded_hook 接入。
"""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from senza import (
    WorkflowEngine, create_os_env,
)

from .config import load_config
from .workflow import build_workflow, build_providers, _session_base_dir
from .judge import make_judge_fn

logger = logging.getLogger(__name__)

# ── restore 后重新注册 ──────────────────────────────────────────────────────

def _re_register(engine, config, design_name, rtl_ids):
    """restore 后重新注册 executors/hooks/plugin/context 变量。

    薄包装:委托 workflow._register_engine(与 build_workflow 共用同一份注册逻辑)。
    WorkflowEngine.restore 只恢复 workflow 定义与 taskstore 状态,
    不恢复 with_executor/with_step_plugin/with_hooks/set_context_variable 的注册。
    """
    from .workflow import _register_engine
    return _register_engine(engine, config, design_name, rtl_ids)


# ── 事件打印 ────────────────────────────────────────────────────────────────

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


def _persist_task_id(design_name: str, task_id: str) -> None:
    """Issue #1: 将 task_id 写入 designs/<name>/.taskstore/task_id。

    Senza 的 JsonlTaskStore 不写这个文件;cmd_run 在 engine 构建后、
    run 前写入,使 restore/status/_print_run_summary 能立即工作。
    """
    store_dir = Path(f"designs/{design_name}/.taskstore")
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "task_id").write_text(task_id)

def _print_run_summary(design_name: str) -> None:
    """workflow 结束后打印每个 step 的状态表。

    从 taskstore workflow.json 读 step_history。
    """
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


# ── 子命令:run / restore / status ───────────────────────────────────────────

def cmd_run(design_name: str, config_path: str):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = load_config(config_path)
    engine = build_workflow(config, design_name)
    # Issue #1: engine 构建时即生成 task_id,在 run 前持久化,
    # 确保 restore/status 能立即工作(即使 run 中途崩溃)。
    _persist_task_id(design_name, engine.task_id())
    print(f"启动 {design_name} 设计流程 (task_id={engine.task_id()})...")
    _run_with_events(engine, design_name)
    print(f"\n流程结束,state={engine.state()}")
    cost = engine.total_cost().get("total_cost", 0.0)
    print(f"总成本: ${cost:.4f}")
    print(f"已完成 {len(engine.step_history())} 步")
    gds = Path(f"designs/{design_name}/gds/{design_name}.gds")
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
    dcfg = load_design_config(Path(f"designs/{design_name}"))
    engine = WorkflowEngine.restore(
        store_dir, task_id,
        provider=provider,
        model=config.model,
        judge=make_judge_fn(config, rtl_ids=dcfg.rtl_step_ids),
        env=env,
        session_base_dir=_session_base_dir(design_name),
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


# ── 子命令:serve ────────────────────────────────────────────────────────────

# static 目录:优先用仓库根的 static/,回退到包内 static/
_STATIC_CANDIDATES = [
    Path.cwd() / "static",
    Path(__file__).resolve().parent / "static",
]


def _resolve_static_dir() -> str:
    for p in _STATIC_CANDIDATES:
        if (p / "index.html").is_file():
            return str(p)
    # 都没有就用仓库根 static/(mount 时会报错,但让错误显式)
    return str(_STATIC_CANDIDATES[0])


def _workflow_runner(state, design_name: str) -> None:
    """构建并运行 workflow。在后台线程中执行(server.py 负责起线程)。

    1. 从 config 构建 provider + engine
    2. engine.subscribe() 存到 state.event_iterator(供 WS 转发)
    3. engine.run() 阻塞直到完成
    """
    config_path = os.environ.get("EDA_STUDIO_CONFIG", "config.yaml")
    config = load_config(config_path)
    engine = build_workflow(config, design_name)

    state.engine = engine
    state.task_id = engine.task_id()
    state.design_name = design_name
    # subscribe() 必须在 run() 之前调用,这样 WS 能拿到所有事件
    state.event_iterator = engine.subscribe(timeout_ms=2000)

    logger.info("starting workflow engine: task_id=%s design=%s", state.task_id, design_name)
    engine.run()
    logger.info("workflow engine finished: task_id=%s", state.task_id)


def run_server(config_path: str, host: str, port: int) -> None:
    """启动 uvicorn server。

    config_path 存到环境变量,供 _workflow_runner 读取
    (workflow_runner 在后台线程执行,无法直接传参)。
    """
    os.environ["EDA_STUDIO_CONFIG"] = config_path

    # 配置日志,确保 workflow 日志能输出
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    static_dir = _resolve_static_dir()
    logger.info("static dir: %s", static_dir)

    from .server import create_app

    app = create_app(
        workflow_runner=_workflow_runner,
        static_dir=static_dir,
    )

    logger.info("EDA Studio Web UI: http://%s:%d", host if host != "0.0.0.0" else "localhost", port)
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


def cmd_serve(config_path: str, port: int, host: str = "0.0.0.0"):
    """启动 Web UI(uvicorn + FastAPI)。"""
    run_server(config_path, host, port)

def cmd_gui(config_path: str):
    """启动桌面应用(NiceGUI native webview)。"""
    from .webui_nicegui import run_nicegui_desktop
    run_nicegui_desktop(config_path)


# ── 子命令:init ─────────────────────────────────────────────────────────────

def _templates_dir() -> Path:
    """定位 eda_studio/templates/ 目录。"""
    import eda_studio
    return Path(eda_studio.__file__).parent / "templates"


def _list_templates() -> list:
    """列出可用模板名。"""
    tdir = _templates_dir()
    if not tdir.is_dir():
        return []
    return [d.name for d in tdir.iterdir() if d.is_dir() and not d.name.startswith("_")]


def cmd_init(name: str) -> int:
    """从 templates/<name>/ 复制 design 输入文件到 designs/<name>/。

    Returns:
        0 成功, 1 失败
    """
    src = _templates_dir() / name
    if not src.is_dir():
        print(f"✗ 未知模板: {name}")
        available = _list_templates()
        if available:
            print(f"  可用模板: {', '.join(available)}")
        return 1

    dst = Path(f"designs/{name}")
    if dst.exists():
        print(f"✗ 目标已存在: {dst}(避免覆盖运行产物)")
        return 1

    shutil.copytree(src, dst)
    print(f"✓ 已初始化 {name} → {dst}")
    print(f"  下一步:")
    print(f"    docker run -d --name eda-tools -v $(pwd)/designs:/work/designs \\")
    print(f"      -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity")
    print(f"    eda-studio check")
    print(f"    eda-studio run {name}")
    return 0


# ── 子命令:check ────────────────────────────────────────────────────────────

def _check_config(config_path: str) -> tuple:
    """检查 config.yaml 可解析。返回 (ok, detail, fix_hint)。"""
    try:
        load_config(config_path)
        return (True, "config.yaml 可解析", None)
    except FileNotFoundError:
        return (False, "config.yaml 不存在", "cp config.example.yaml config.yaml")
    except Exception as e:
        return (False, f"config.yaml 解析失败: {e}", "检查 YAML 语法")


def _check_api_key(config_path: str) -> tuple:
    """检查 API key 非空。"""
    try:
        cfg = load_config(config_path)
        key = cfg.provider_spec.get("api_key", "")
        if not key:
            return (False, "API key 为空", "export OPENAI_API_KEY=... 并在 config.yaml 用 ${OPENAI_API_KEY}")
        return (True, f"API key 已设置({key[:4]}...{key[-4:]})", None)
    except Exception as e:
        return (False, f"读取 config 失败: {e}", None)


def _check_api_reachable(config_path: str) -> tuple:
    """检查 API 端点可达 + 模型可用。"""
    try:
        cfg = load_config(config_path)
        key = cfg.provider_spec.get("api_key", "")
        base_url = cfg.provider_spec.get("base_url") or "https://api.openai.com/v1"
        # base_url 可能不含 /v1(如 http://api.example.com/),自动补
        if not base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        model = cfg.model
        url = base_url + "/chat/completions"
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        })
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            elapsed = (time.monotonic() - t0) * 1000
            choices = data.get("choices", [])
            if choices:
                return (True, f"API 端点可达({base_url}, {elapsed:.0f}ms), 模型 {model} 可用", None)
            return (False, f"API 响应无 choices: {data}", "检查 model 名是否正确")
    except Exception as e:
        return (False, f"API 不可达: {e}", "检查 base_url / api_key / 网络")


def _check_docker() -> tuple:
    """检查 docker 可用。"""
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return (True, "docker 可用", None)
        return (False, "docker 不可用", "启动 Docker Desktop")
    except FileNotFoundError:
        return (False, "docker 命令不存在", "安装 Docker")
    except subprocess.TimeoutExpired:
        return (False, "docker info 超时", None)


def _check_container() -> tuple:
    """检查 eda-tools 容器在跑。"""
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", "name=eda-tools", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=5)
        if "eda-tools" in r.stdout:
            return (True, "eda-tools 容器在运行", None)
        return (False, "eda-tools 容器未运行",
                "docker run -d --name eda-tools -v $(pwd)/designs:/work/designs "
                "-e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity")
    except Exception as e:
        return (False, f"检查容器失败: {e}", None)


def _check_eda_tools() -> list:
    """检查容器内 EDA 工具可用,返回 [(tool, ok, detail), ...]。"""
    # 各工具版本检查命令(部分工具不认 --version)
    version_cmds = {
        "verilator": "verilator --version",
        "yosys": "yosys -V",
        "openroad": "openroad -version",
        "magic": "magic -noconsole -dnull <<< 'exit'",
        "klayout": "klayout -v",
    }
    results = []
    for tool, vcmd in version_cmds.items():
        try:
            cmd = ["docker", "exec", "eda-tools", "bash", "-lc", vcmd]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            output = "\n".join(l for l in (r.stdout + r.stderr).split("\n") if not l.startswith("[INFO]"))
            ok = r.returncode == 0 or (tool == "magic" and "Magic 8" in output)
            results.append((tool, ok, output.strip()[:60] if ok else f"exit {r.returncode}"))
        except subprocess.TimeoutExpired:
            results.append((tool, False, "timeout"))
        except Exception as e:
            results.append((tool, False, str(e)[:60]))
    return results


def _check_pdk() -> tuple:
    """检查 Sky130 PDK 存在。"""
    try:
        r = subprocess.run(
            ["docker", "exec", "eda-tools", "bash", "-lc",
             "ls /foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd/lib/"],
            capture_output=True, text=True, timeout=10)
        output = "\n".join(l for l in r.stdout.split("\n") if not l.startswith("[INFO]"))
        if r.returncode == 0 and output.strip():
            return (True, "Sky130 PDK 存在", None)
        return (False, "PDK 未找到", "检查容器 PDK 安装")
    except Exception as e:
        return (False, f"PDK 检查失败: {e}", None)


def cmd_check(config_path: str = "config.yaml") -> int:
    """预检环境:config / API / docker / 容器 / EDA 工具 / PDK。

    Returns:
        0 全部通过, 1 有失败项
    """
    checks = []

    ok_cfg, detail, hint = _check_config(config_path)
    checks.append(("config", ok_cfg, detail, hint))
    if ok_cfg:
        ok_key, detail, hint = _check_api_key(config_path)
        checks.append(("api_key", ok_key, detail, hint))
        if ok_key:
            ok_api, detail, hint = _check_api_reachable(config_path)
            checks.append(("api", ok_api, detail, hint))

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_docker = pool.submit(_check_docker)
        f_container = pool.submit(_check_container)
        f_pdk = pool.submit(_check_pdk)
        f_tools = pool.submit(_check_eda_tools)

        ok_d, detail, hint = f_docker.result()
        checks.append(("docker", ok_d, detail, hint))

        ok_c, detail, hint = f_container.result()
        checks.append(("container", ok_c, detail, hint))

        if ok_c:
            tool_results = f_tools.result()
            for tool, ok, detail in tool_results:
                checks.append((f"tool:{tool}", ok, detail, None if ok else f"容器内 {tool} 不可用"))

            ok_pdk, detail, hint = f_pdk.result()
            checks.append(("pdk", ok_pdk, detail, hint))

    all_ok = True
    for name, ok, detail, hint in checks:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {detail}")
        if not ok and hint:
            print(f"    → {hint}")
            all_ok = False
        elif not ok:
            all_ok = False

    print()
    if all_ok:
        print("✓ 环境检查通过,可以运行 eda-studio run <design>")
        return 0
    print("✗ 环境检查未通过,请修复上述问题")
    return 1


# ── argparse 入口 ───────────────────────────────────────────────────────────

def main(argv=None):
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
    p_gui = sub.add_parser("gui", help="启动桌面应用(NiceGUI native)")
    p_gui.add_argument("--config", default="config.yaml")

    args = parser.parse_args(argv)
    if args.command == "run":
        cmd_run(args.design, args.config)
    elif args.command == "restore":
        cmd_restore(args.design, args.config)
    elif args.command == "status":
        cmd_status(args.design)
    elif args.command == "serve":
        cmd_serve(args.config, args.port, args.host)
    elif args.command == "gui":
        cmd_gui(args.config)
    elif args.command == "init":
        sys.exit(cmd_init(args.design))
    elif args.command == "check":
        sys.exit(cmd_check(args.config))


if __name__ == "__main__":
    main()
