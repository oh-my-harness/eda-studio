"""FastAPI web server — HTTP endpoints + WebSocket handler。

路由:
- POST /api/task        提交设计名,启动 workflow(202);409 if running
- GET  /api/status      返回 workflow 运行时状态快照
- GET  /api/report/{step}  返回对应 step 的 EDA 报告文件内容
- WS   /ws              转发 WorkflowEvent
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .state import AppState

logger = logging.getLogger(__name__)

# WebSocket 事件轮询超时(秒)
_WS_EVENT_TIMEOUT = 30.0

# step_id → 报告文件路径(相对 design_dir)的映射
_REPORT_PATHS = {
    "simulate": "sim/report.txt",
    "synthesize": "synth/report.txt",
    "pnr": "pnr/report.txt",
    "drc": "pnr/drc.rpt",
    "gds": "gds/report.txt",
    "render": None,  # 特殊处理:路径为 gds/<design_name>.png,在 get_report 里动态拼
}


class TaskRequest(BaseModel):
    """POST /api/task request body."""
    design: str = "uart"


def _next_event(iterator: Any) -> Any:
    """调用 iterator 的 next(),StopIteration 或异常时返回 None。"""
    try:
        return next(iterator)
    except StopIteration:
        return None
    except Exception:
        return None


def create_app(
    workflow_runner: Callable[[AppState, str], Any] | None = None,
    static_dir: str = "static",
) -> FastAPI:
    """创建 FastAPI 应用。

    Args:
        workflow_runner: callable(state, design_name) 跑 workflow。None 时 POST /api/task 返回 202 但不执行。
        static_dir: 静态文件目录(前端 index.html)。
    """
    state = AppState()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(lifespan=lifespan)
    app.state = state  # type: ignore[assignment]

    # ── POST /api/task ──────────────────────────────────────────
    @app.post("/api/task")
    async def submit_task(req: TaskRequest):
        if state.task_running:
            return JSONResponse(
                status_code=409,
                content={"error": "a task is already running"},
            )

        state.task_running = True

        def _run_in_background():
            try:
                if workflow_runner is not None:
                    logger.info("workflow starting: design=%s", req.design)
                    workflow_runner(state, req.design)
                    logger.info("workflow completed")
            except Exception:
                logger.exception("workflow failed")
            finally:
                state.task_running = False
                state.clear_active_task()

        import threading
        thread = threading.Thread(target=_run_in_background, daemon=True)
        thread.start()

        return JSONResponse(
            status_code=202,
            content={"message": "task started", "design": req.design},
        )

    # ── GET /api/status ─────────────────────────────────────────
    @app.get("/api/status")
    async def get_status():
        return JSONResponse(status_code=200, content=state.status_snapshot())

    # ── GET /api/designs ────────────────────────────────────────
    @app.get("/api/designs")
    async def list_designs():
        """列出可用的 design 模板(eda_studio/templates/ 下的子目录)。"""
        import importlib.resources as resources
        try:
            pkg_root = resources.files("eda_studio") / "templates"
            names = sorted([p.name for p in pkg_root.iterdir() if p.is_dir() and not p.name.startswith("_")])
        except Exception:
            names = []
        return JSONResponse(status_code=200, content={"designs": names})

    # ── GET /api/workflow-steps ────────────────────────────────
    @app.get("/api/workflow-steps")
    async def get_workflow_steps():
        """返回当前 design 的 workflow step 列表(从 design.yaml 动态生成)。"""
        if not state.design_name:
            return JSONResponse(status_code=404, content={"error": "no active design"})
        from pathlib import Path
        from .design_config import load_design_config
        dcfg = load_design_config(Path(f"designs/{state.design_name}"))
        steps = []
        for m in dcfg.modules:
            steps.append({"id": f"rtl_{m.id}", "name": m.name, "type": "LLM",
                          "icon": "📐", "desc": f"设计 {m.file}"})
        fixed = [
            {"id": "simulate", "name": "仿真验证", "type": "EXEC", "icon": "🔬", "desc": "Verilator 仿真"},
            {"id": "debug_fix", "name": "仿真修复", "type": "LLM", "icon": "🛠️", "desc": "分析报告修复 RTL"},
            {"id": "synthesize", "name": "逻辑综合", "type": "EXEC", "icon": "⚙️", "desc": "Yosys 综合"},
            {"id": "pnr", "name": "布局布线", "type": "EXEC", "icon": "📐", "desc": "OpenROAD PnR"},
            {"id": "drc_fix", "name": "DRC 修复", "type": "LLM", "icon": "🔧", "desc": "修复 DRC 违规"},
            {"id": "drc", "name": "DRC 检查", "type": "EXEC", "icon": "✅", "desc": "Magic DRC"},
            {"id": "gds", "name": "GDS 导出", "type": "EXEC", "icon": "📦", "desc": "导出 GDS"},
            {"id": "render", "name": "渲染预览", "type": "EXEC", "icon": "🖼️", "desc": "GDS → PNG"},
        ]
        steps.extend(fixed)
        return JSONResponse(status_code=200, content={"steps": steps})

    # ── GET /api/report/{step} ──────────────────────────────────
    @app.get("/api/report/{step}")
    async def get_report(step: str):
        """返回对应 step 的 EDA 报告文件内容。"""
        rel = _REPORT_PATHS.get(step)
        if rel is None:
            return PlainTextResponse(f"unknown step: {step}", status_code=404)
        if not state.design_name:
            return PlainTextResponse("no active design", status_code=404)
        path = Path(f"designs/{state.design_name}") / rel
        if not path.is_file():
            return PlainTextResponse(f"report not found: {rel}", status_code=404)
        return PlainTextResponse(path.read_text())

    # ── GET /api/render.png ─────────────────────────────────────
    @app.get("/api/render.png")
    async def get_render_png():
        """返回 render step 产出的 PNG 预览图。"""
        if not state.design_name:
            return PlainTextResponse("no active design", status_code=404)
        path = Path(f"designs/{state.design_name}") / "gds" / f"{state.design_name}.png"
        if not path.is_file():
            return PlainTextResponse("render not found", status_code=404)
        return FileResponse(path, media_type="image/png")

    # ── GET /api/file/{path:path} ───────────────────────────────
    @app.get("/api/file/{file_path:path}")
    async def get_design_file(file_path: str):
        """返回 design 目录下的文件(rtl/sim/synth/pnr/gds 产物)。"""
        if not state.design_name:
            return PlainTextResponse("no active design", status_code=404)
        # 防 path traversal:只允许 designs/<design>/ 下
        safe = os.path.normpath(file_path).lstrip("/")
        if safe.startswith("..") or "/.." in safe:
            return PlainTextResponse("forbidden", status_code=403)
        path = Path(f"designs/{state.design_name}") / safe
        if not path.is_file():
            return PlainTextResponse(f"not found: {file_path}", status_code=404)
        return PlainTextResponse(path.read_text())

    # ── WS /ws ──────────────────────────────────────────────────
    @app.websocket("/ws")
    async def ws_handler(websocket: WebSocket):
        """转发 WorkflowEvent 到客户端。"""
        await websocket.accept()

        # 轮询等待 event iterator 可用(最多 30s)
        iterator = None
        deadline = asyncio.get_event_loop().time() + _WS_EVENT_TIMEOUT
        while iterator is None:
            iterator = state.event_iterator
            if iterator is not None:
                break
            if asyncio.get_event_loop().time() >= deadline:
                await websocket.close()
                return
            await asyncio.sleep(0.1)

        try:
            while True:
                t0 = time.monotonic()
                event = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _next_event(iterator)
                )
                elapsed = time.monotonic() - t0

                if event is None:
                    if elapsed < 1.0:
                        # 通道关闭
                        break
                    # 超时,继续轮询保持 WS 存活
                    continue

                if isinstance(event, dict) and event.get("type") == "lagged":
                    continue

                await websocket.send_text(json.dumps(event))
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error("websocket error: %s", e)
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    # ── 静态文件(必须放在所有 API 路由之后)──
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
