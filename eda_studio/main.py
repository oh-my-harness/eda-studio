"""serve 入口:启动 uvicorn + workflow_runner。

workflow_runner 在后台线程跑 engine.run()(阻塞),主线程的
FastAPI 通过 engine.subscribe() 拿事件转发给 WebSocket。
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 3000

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
    from .config import load_config
    from .workflow import build_workflow

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
