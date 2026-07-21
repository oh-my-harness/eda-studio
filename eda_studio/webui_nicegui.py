"""NiceGUI 桌面版 WebUI — 三栏 + 流程图 + 事件流,原生窗口替代 static/index.html。

架构:
- ui.run(native=True, window_size=(1280,800)) 启动 pywebview 桌面窗口
- NiceGUI 后台跑 uvicorn+socketio(固定端口 8080),前端走 localhost HTTP
- ui.timer(0.3, pump) 轮询 state.event_iterator,拿到 WorkflowEvent 后更新 UI
- @ui.page('/') 为每个客户端创建独立作用域(stepStore/viewStepId 等 per-client)
- 暗色主题,三栏布局:左流程图 / 中 step card / 右事件时间线

与 server.py 的关系:
- 共用 register_api_routes() — 所有 /api/* REST 端点逻辑一致
- 共用 AppState / _workflow_runner / _next_event
- 不做直接函数调用,全部走 HTTP REST(与旧 WebUI 对称,可独立测试)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable

from .state import AppState

logger = logging.getLogger(__name__)

# 固定端口(native 模式也用此端口,httpx 调本机 REST)
_DEFAULT_PORT = 8080

_COLORS = {
    "bg": "#1a1a2e", "panel": "#16213e", "border": "#0f3460",
    "accent": "#e94560", "text": "#eee", "text_dim": "#aaa",
    "ok": "#4ecca3", "err": "#ff4444", "warn": "#ffc107", "info": "#58a6ff",
}

_BADGE_COLORS = {
    "idle": "#555", "running": "#e94560", "paused": "#ffc107",
    "failed": "#ff4444", "done": "#4ecca3", "succeeded": "#4ecca3",
    "aborted": "#ff4444", "cancelled": "#ff4444",
}


def _next_event(iterator: Any) -> Any:
    """调用 iterator 的 next(),StopIteration 或异常时返回 None。"""
    try:
        return next(iterator)
    except StopIteration:
        return None
    except Exception:
        return None


def _format_token_meta(cost: dict | None) -> str:
    if not cost:
        return ""
    parts = []
    if cost.get("total_input_tokens", 0) > 0: parts.append(f"in: {cost['total_input_tokens']:,}")
    if cost.get("total_output_tokens", 0) > 0: parts.append(f"out: {cost['total_output_tokens']:,}")
    if cost.get("total_cache_read_tokens", 0) > 0: parts.append(f"cache_r: {cost['total_cache_read_tokens']:,}")
    if cost.get("total_cache_write_tokens", 0) > 0: parts.append(f"cache_w: {cost['total_cache_write_tokens']:,}")
    if cost.get("total_reasoning_tokens", 0) > 0: parts.append(f"reasoning: {cost['total_reasoning_tokens']:,}")
    if cost.get("total_cost", 0) > 0: parts.append(f"${cost['total_cost']:.4f}")
    return "  ".join(parts)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") \
        .replace('"', "&quot;").replace("'", "&#39;")


# ── HTTP 辅助:调本机 REST 端点 ─────────────────────────────────────

async def _api_get(port: int, path: str) -> dict:
    import httpx
    async with httpx.AsyncClient() as c:
        r = await c.get(f"http://127.0.0.1:{port}{path}")
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}


async def _api_post(port: int, path: str, body: dict) -> tuple[int, dict]:
    import httpx
    async with httpx.AsyncClient() as c:
        r = await c.post(f"http://127.0.0.1:{port}{path}", json=body)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}


def create_app(
    workflow_runner: Callable[[AppState, str], Any] | None = None,
    port: int = _DEFAULT_PORT,
) -> Any:
    """创建 NiceGUI 桌面应用。

    Args:
        workflow_runner: callable(state, design_name) 跑 workflow。
        port: uvicorn 监听端口(httpx 调本机 REST 用)。
    """
    from nicegui import ui, app
    from .server import register_api_routes

    state = AppState()

    # 注册全部 /api/* REST 端点(与 server.py 共用)
    register_api_routes(app, state, workflow_runner)

    # ── 全局 CSS ──────────────────────────────────────────────
    ui.add_css(f"""
    .nicegui-content {{ padding: 0 !important; max-width: 100% !important; }}
    body {{ background: {_COLORS['bg']} !important; color: {_COLORS['text']} !important; }}

    .flow-node {{
        display: flex; align-items: center; gap: 10px; padding: 10px;
        margin-bottom: 6px; background: {_COLORS['bg']}; border-radius: 6px;
        border-left: 3px solid #333; transition: all 0.2s; cursor: pointer;
    }}
    .flow-node.pending {{ opacity: 0.5; }}
    .flow-node.active {{ border-left-color: {_COLORS['accent']}; background: #1f2a4a; opacity: 1; }}
    .flow-node.view {{ box-shadow: 0 0 0 2px {_COLORS['info']} inset; }}
    .flow-node.done {{ border-left-color: {_COLORS['ok']}; opacity: 0.8; }}
    .flow-node.failed {{ border-left-color: {_COLORS['err']}; }}
    .flow-node-icon {{ font-size: 18px; }}
    .flow-node-info {{ flex: 1; }}
    .flow-node-name {{ font-size: 13px; font-weight: 600; }}
    .type-badge {{ font-size: 9px; font-weight: 700; padding: 1px 5px; border-radius: 3px; margin-left: 4px; }}
    .type-llm {{ background: {_COLORS['ok']}; color: #0d1117; }}
    .type-exec {{ background: {_COLORS['info']}; color: #0d1117; }}

    .center-empty {{ text-align: center; margin-top: 80px; color: #555; }}
    .big-icon {{ font-size: 48px; margin-bottom: 12px; }}

    .step-card {{
        background: {_COLORS['panel']}; border: 1px solid {_COLORS['border']};
        border-radius: 8px; padding: 14px; margin-bottom: 12px;
    }}
    .step-card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
    .step-card-icon {{ font-size: 20px; }}
    .step-card-name {{ font-weight: 600; flex: 1; }}
    .step-card-round {{ font-size: 11px; color: #888; background: {_COLORS['bg']}; padding: 2px 6px; border-radius: 3px; }}
    .step-output {{
        font-family: 'SF Mono', monospace; font-size: 12px; white-space: pre-wrap;
        max-height: 300px; overflow-y: auto; background: #0d1117;
        padding: 10px; border-radius: 4px; color: #ccc;
    }}
    .step-meta {{ font-size: 11px; color: #888; margin-top: 6px; }}
    .tool-line {{ font-family: monospace; font-size: 12px; padding: 2px 0 2px 16px; color: #aaa; }}
    .tool-line.ok {{ color: {_COLORS['ok']}; }}
    .tool-line.err {{ color: #ff6b6b; }}

    .event-item {{ display: flex; gap: 8px; padding: 6px 0; border-bottom: 1px solid {_COLORS['bg']}; font-size: 12px; }}
    .event-icon {{ flex: 0 0 20px; }}
    .event-body {{ flex: 1; }}
    .event-text {{ color: #ccc; }}
    .event-meta {{ font-size: 10px; color: #666; }}
    .event-ts {{ font-size: 10px; color: #555; font-family: monospace; }}
    .event-step_started .event-icon {{ color: {_COLORS['accent']}; }}
    .event-step_finished .event-icon {{ color: {_COLORS['ok']}; }}
    .event-failed .event-icon {{ color: {_COLORS['err']}; }}
    .event-paused .event-icon {{ color: {_COLORS['warn']}; }}

    .spinner {{
        display: inline-block; width: 16px; height: 16px;
        border: 2px solid #333; border-top-color: {_COLORS['accent']};
        border-radius: 50%; animation: spin 0.8s linear infinite;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    .report-link {{ display: inline-block; margin-top: 6px; color: {_COLORS['info']}; font-size: 12px; text-decoration: none; }}
    """, shared=True)

    @ui.page("/")
    async def main_page():
        cs = {  # client state
            "step_round": {}, "current_step_id": None, "view_step_id": None,
            "step_store": {}, "step_config": {}, "step_order": [],
            "total_cost": 0.0,
            "total_tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "reasoning": 0},
            "banner_shown": False,
        }
        node_refs: dict[str, Any] = {}

        # ── 顶栏 ──────────────────────────────────────────────
        with ui.element("div").style(
            f"display:flex;align-items:center;gap:12px;width:100%;"
            f"background:{_COLORS['panel']};border-bottom:1px solid {_COLORS['border']};"
            "padding:10px 16px;height:53px;box-sizing:border-box;flex-wrap:nowrap;"
        ):
            ui.html('<span style="font-size:18px;font-weight:700;color:#e94560;white-space:nowrap;">🔧 EDA Studio</span>')
            design_select = ui.select(
                options=["uart"], value="uart",
            ).props("dark").style(
                "flex:0 0 200px;background:#1a1a2e;"
                "border:1px solid #0f3460;border-radius:6px;"
            )
            submit_btn = ui.button("运行", on_click=lambda: do_submit()).props("unelevated").style(
                "flex:0 0 auto;background:#e94560;border:none;border-radius:6px;"
                "color:#fff;font-size:14px;padding:8px 20px;"
            )
            ui.html(f'<div style="width:1px;height:24px;background:{_COLORS["border"]};flex:0 0 auto;"></div>')
            with ui.element("div").style("display:flex;align-items:center;gap:6px;font-size:14px;flex:0 1 auto;"):
                step_icon = ui.html('⚪').style("font-size:16px;")
                step_name = ui.html('Idle').style("font-size:14px;")
            ui.html(f'<div style="width:1px;height:24px;background:{_COLORS["border"]};flex:0 0 auto;"></div>')
            cost_disp = ui.html('$0.0000').style(
                "font-family:monospace;background:#e94560;padding:2px 8px;border-radius:4px;"
                "color:#fff;font-size:13px;flex:0 0 auto;"
            )
            token_disp = ui.html('').style(
                "font-family:monospace;font-size:12px;color:#aaa;background:#1a1a2e;"
                "padding:2px 8px;border-radius:4px;flex:0 1 auto;"
            )
            with ui.element("div").style("display:flex;align-items:center;gap:6px;font-size:13px;flex:0 0 auto;margin-left:auto;"):
                badge_dot = ui.html('').style(
                    "width:8px;height:8px;border-radius:50%;background:#555;display:inline-block;flex:0 0 auto;"
                )
                badge_text = ui.html('Idle').style("font-size:13px;")

        # ── 三栏 ──────────────────────────────────────────────
        with ui.element("div").style(
            "display:flex;width:100%;height:calc(100vh - 53px);margin:0;"
        ):
            left_col = ui.element("div").style(
                f"flex:0 0 260px;overflow-y:auto;padding:12px;"
                f"background:{_COLORS['panel']};border-right:1px solid {_COLORS['border']};"
                "box-sizing:border-box;"
            )
            center_col = ui.element("div").style(
                "flex:1 1 0;overflow-y:auto;padding:16px;box-sizing:border-box;"
            )
            right_col = ui.element("div").style(
                f"flex:0 0 340px;overflow-y:auto;padding:12px;"
                f"background:{_COLORS['panel']};border-left:1px solid {_COLORS['border']};"
                "box-sizing:border-box;"
            )
            with right_col:
                ui.html('<div style="font-size:13px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">Event Timeline</div>')
                events_container = ui.html('<ul id="events" style="list-style:none;padding:0;margin:0;"></ul>')

        # ── UI 更新函数 ───────────────────────────────────────

        def update_cost_display():
            cost_disp.set_content(f'${cs["total_cost"]:.4f}')
            t = cs["total_tokens"]
            parts = []
            if t["input"]: parts.append(f"in: {t['input']:,}")
            if t["output"]: parts.append(f"out: {t['output']:,}")
            if t["cache_read"]: parts.append(f"cache_r: {t['cache_read']:,}")
            if t["cache_write"]: parts.append(f"cache_w: {t['cache_write']:,}")
            token_disp.set_content("  ".join(parts))

        def set_status_badge(key: str, text: str):
            color = _BADGE_COLORS.get(key, "#555")
            badge_dot.style(f"background:{color};")
            badge_text.set_content(_esc(text))

        def update_topbar_step(sid: str | None):
            if not sid:
                step_icon.set_content('⚪')
                step_name.set_content('Idle')
                return
            cfg = cs["step_config"].get(sid, {"icon": "🔹", "name": sid})
            step_icon.set_content(cfg.get("icon", "🔹"))
            step_name.set_content(_esc(cfg.get("name", sid)))

        def build_flowchart():
            left_col.clear()
            node_refs.clear()
            with left_col:
                for sid in cs["step_order"]:
                    cfg = cs["step_config"].get(sid, {"name": sid, "icon": "🔹", "type": "", "desc": ""})
                    badge_cls = "type-llm" if cfg.get("type") == "LLM" else "type-exec"
                    badge = f'<span class="type-badge {badge_cls}">{cfg.get("type","")}</span>' if cfg.get("type") else ""
                    node = ui.element("div").classes("flow-node pending").style("cursor:pointer;")
                    node.on("click", lambda _, s=sid: show_step(s))
                    with node:
                        ui.html(
                            f'<span class="flow-node-icon">{cfg.get("icon","🔹")}</span>'
                            f'<div class="flow-node-info">'
                            f'<div class="flow-node-name">{_esc(cfg.get("name",sid))} {badge}</div>'
                            f'<div class="flow-node-desc" style="font-size:11px;color:#666;">{_esc(cfg.get("desc",""))}</div>'
                            f'</div>'
                        )
                    node_refs[sid] = node

        def set_active_node(active_id: str | None):
            view = cs["view_step_id"]
            for sid, node in node_refs.items():
                cls = "flow-node"
                if sid == active_id: cls += " active"
                if sid == view: cls += " view"
                s = cs["step_store"].get(sid)
                if s and s.get("finished"):
                    if s.get("success"): cls += " done"
                    else: cls += " failed"
                elif sid != active_id and sid != view:
                    cls += " pending"
                node.classes(replace=cls)

        def reset_center_empty():
            center_col.clear()
            with center_col:
                ui.html('<div class="center-empty"><div class="big-icon">🔧</div>'
                        '<div style="font-size:14px;">输入设计名,点击运行开始 EDA 流程</div></div>')

        def _ensure_store(sid: str) -> dict:
            if sid not in cs["step_store"]:
                cs["step_store"][sid] = {
                    "round": 0, "lines": [], "output": "", "cost": None,
                    "finished": False, "success": None,
                }
            return cs["step_store"][sid]

        def init_center_for_step(sid: str):
            s = _ensure_store(sid)
            s["round"] = cs["step_round"].get(sid, 0)
            s["lines"] = []; s["output"] = ""; s["cost"] = None
            s["finished"] = False; s["success"] = None
            cs["view_step_id"] = sid
            set_active_node(sid)
            render_step_view(sid)

        def append_step_output(sid: str, text: str, cls: str = ""):
            s = _ensure_store(sid)
            s["lines"].append({"text": text, "cls": cls})
            if sid == cs["view_step_id"]:
                render_step_view(sid)

        def update_step_card_finished(sid: str, output: str, cost: dict | None, success: bool | None):
            s = _ensure_store(sid)
            s["output"] = output or ""
            s["cost"] = cost
            s["finished"] = True
            s["success"] = (success is not False)
            if sid == cs["view_step_id"]:
                render_step_view(sid)

        def render_step_view(sid: str):
            cfg = cs["step_config"].get(sid, {"name": sid, "icon": "🔹", "desc": ""})
            s = _ensure_store(sid)
            lines_html = "".join(
                f'<div class="tool-line {l["cls"]}">{_esc(l["text"])}</div>'
                for l in s["lines"]
            )
            extra = ""
            if s["output"]:
                preview = s["output"][:2000]
                if len(s["output"]) > 2000:
                    preview += "\n...(截断)"
                extra += f'<div class="tool-line">--- 输出 ---</div><div class="tool-line">{_esc(preview)}</div>'
            report_steps = ["simulate", "synthesize", "pnr", "drc", "gds"]
            if sid in report_steps and s["finished"]:
                extra += f'<a class="report-link" href="/api/report/{sid}" target="_blank">查看完整报告 →</a>'
            if sid == "render" and s["finished"]:
                if s["success"]:
                    extra += (f'<img src="/api/render.png?t={int(time.time()*1000)}" '
                              f'alt="GDS 渲染预览" style="width:100%;margin-top:12px;'
                              f'border:1px solid {_COLORS["border"]};border-radius:6px;background:#fff;">')
                else:
                    extra += (f'<div style="margin-top:12px;padding:10px;background:#3a1515;'
                              f'border:1px solid {_COLORS["err"]};border-radius:6px;color:#ff6b6b;'
                              f'font-size:12px;">渲染失败 — 见上方输出</div>')
            meta = _format_token_meta(s["cost"])
            meta_html = f'<div class="step-meta">{_esc(meta)}</div>' if meta else ""
            spinner = "" if s["finished"] else '<span class="spinner"></span>'
            round_badge = f'<span class="step-card-round">round {s["round"]}</span>' if s["round"] > 1 else ""
            card_html = f"""
            <div class="step-card">
                <div class="step-card-header">
                    <span class="step-card-icon">{cfg.get("icon","🔹")}</span>
                    <span class="step-card-name">{_esc(cfg.get("name",sid))}</span>
                    {round_badge}
                    {spinner}
                </div>
                <div class="step-output">{lines_html}{extra}</div>
                {meta_html}
            </div>
            """
            center_col.clear()
            with center_col:
                ui.html(card_html)

        def show_step(sid: str):
            cs["view_step_id"] = sid
            set_active_node(cs["current_step_id"])
            render_step_view(sid)

        def prepend_event(item_html: str, item_class: str):
            js = """
            (function(){
                var list = document.getElementById('events');
                if (!list) return;
                var li = document.createElement('li');
                li.className = %r;
                li.innerHTML = %r;
                list.insertBefore(li, list.firstChild);
                while (list.children.length > 30) list.removeChild(list.lastChild);
            })();
            """ % (item_class, item_html)
            ui.run_javascript(js)

        # ── 事件处理 ──────────────────────────────────────────

        def handle_event(event: dict):
            if not isinstance(event, dict):
                return
            etype = event.get("type")
            if etype == "lagged":
                return
            ts = time.strftime("%H:%M:%S")

            if etype == "step_progress":
                _handle_step_progress(event)
                return

            if etype == "step_started":
                sid = event.get("step_id", "")
                if sid not in cs["step_config"]:
                    cs["step_config"][sid] = {
                        "name": event.get("step_name", sid), "icon": "🔹", "type": "LLM", "desc": "",
                    }
                    cs["step_order"].append(sid)
                    build_flowchart()
                cs["step_round"][sid] = cs["step_round"].get(sid, 0) + 1
                cs["current_step_id"] = sid
                rnd = cs["step_round"][sid]
                rnd_meta = f'<div class="event-meta">round {rnd}</div>' if rnd > 1 else ""
                cfg = cs["step_config"].get(sid, {"name": sid})
                prepend_event(
                    f'<span class="event-icon">▶</span><div class="event-body">'
                    f'<span class="event-text">{_esc(cfg["name"])} 开始</span>{rnd_meta}</div>'
                    f'<span class="event-ts">{ts}</span>',
                    "event-item event-step_started",
                )
                set_active_node(sid)
                update_topbar_step(sid)
                set_status_badge("running", "Running")
                init_center_for_step(sid)

            elif etype == "step_finished":
                sid = event.get("step_id", "")
                cfg = cs["step_config"].get(sid, {"name": sid, "icon": "🔹"})
                output = event.get("output", "") or ""
                structured = event.get("structured")
                success = structured.get("success") if structured else True
                cost = event.get("cost")
                if cost:
                    if cost.get("total_cost"):
                        cs["total_cost"] += cost["total_cost"]
                    cs["total_tokens"]["input"] += cost.get("total_input_tokens", 0)
                    cs["total_tokens"]["output"] += cost.get("total_output_tokens", 0)
                    cs["total_tokens"]["cache_read"] += cost.get("total_cache_read_tokens", 0)
                    cs["total_tokens"]["cache_write"] += cost.get("total_cache_write_tokens", 0)
                    cs["total_tokens"]["reasoning"] += cost.get("total_reasoning_tokens", 0)
                update_cost_display()
                meta = _format_token_meta(cost)
                meta_div = f'<div class="event-meta">{_esc(meta)}</div>' if meta else ""
                icon = "✔" if success else "✗"
                ecls = "event-step_finished" if success else "event-failed"
                prepend_event(
                    f'<span class="event-icon">{icon}</span><div class="event-body">'
                    f'<span class="event-text">{_esc(cfg["name"])} {"完成" if success else "失败"}</span>{meta_div}</div>'
                    f'<span class="event-ts">{ts}</span>',
                    f"event-item {ecls}",
                )
                _ensure_store(sid)
                cs["step_store"][sid]["finished"] = True
                cs["step_store"][sid]["success"] = success
                set_active_node(cs["current_step_id"])
                update_step_card_finished(sid, output, cost, success)

            elif etype == "paused":
                prepend_event(
                    f'<span class="event-icon">⏸</span><div class="event-body">'
                    f'<span class="event-text">暂停: {_esc(event.get("reason",""))}</span></div>'
                    f'<span class="event-ts">{ts}</span>',
                    "event-item event-paused",
                )
                set_status_badge("paused", "Paused")

            elif etype == "resumed":
                prepend_event(
                    f'<span class="event-icon">▶</span><div class="event-body">'
                    f'<span class="event-text">恢复</span></div><span class="event-ts">{ts}</span>',
                    "event-item",
                )
                set_status_badge("running", "Running")

            elif etype == "failed":
                prepend_event(
                    f'<span class="event-icon">✗</span><div class="event-body">'
                    f'<span class="event-text">失败: {_esc(event.get("error",""))}</span></div>'
                    f'<span class="event-ts">{ts}</span>',
                    "event-item event-failed",
                )
                if cs["current_step_id"]:
                    _ensure_store(cs["current_step_id"])
                    cs["step_store"][cs["current_step_id"]]["finished"] = True
                    cs["step_store"][cs["current_step_id"]]["success"] = False
                set_active_node(cs["current_step_id"])
                set_status_badge("failed", "Failed")
                submit_btn.enable()

            elif etype == "cancelled":
                prepend_event(
                    f'<span class="event-icon">✗</span><div class="event-body">'
                    f'<span class="event-text">取消: {_esc(event.get("reason",""))}</span></div>'
                    f'<span class="event-ts">{ts}</span>',
                    "event-item event-failed",
                )
                set_status_badge("cancelled", "Cancelled")
                submit_btn.enable()

            elif etype in ("succeeded", "aborted"):
                if not cs["banner_shown"]:
                    cs["banner_shown"] = True
                    ok = etype == "succeeded"
                    done_c = sum(1 for v in cs["step_store"].values() if v.get("finished") and v.get("success"))
                    fail_c = sum(1 for v in cs["step_store"].values() if v.get("finished") and not v.get("success"))
                    total = done_c + fail_c
                    label = "完成" if ok else ("终止" if etype == "aborted" else "失败")
                    ui.notify(
                        f"{'✓' if ok else '✗'} Workflow {label} — {done_c}/{total} 步成功",
                        type="positive" if ok else "negative", timeout=8000,
                    )
                    submit_btn.enable()
                    set_status_badge("done" if ok else "aborted", "Done" if ok else "Aborted")

            else:
                prepend_event(
                    f'<span class="event-icon">•</span><div class="event-body">'
                    f'<span class="event-text">{_esc(str(event))}</span></div>'
                    f'<span class="event-ts">{ts}</span>',
                    "event-item",
                )

        def _handle_step_progress(event: dict):
            sid = event.get("step_id", "")
            prog = event.get("progress") or {}
            if not prog:
                return
            ptype = prog.get("type")
            if ptype == "message_end":
                if "progress" in (prog.get("kind", "")).lower():
                    append_step_output(sid, "💭 模型思考中...\n")
            elif ptype == "tool_call_start":
                append_step_output(sid, f"🔧 调用工具: {prog.get('name','')}\n", "tool")
            elif ptype == "tool_execution_end":
                if prog.get("ok"):
                    append_step_output(sid, f"✓ {prog.get('tool_name','')} 完成\n", "ok")
                else:
                    append_step_output(sid, f"✗ {prog.get('tool_name','')} 失败: {prog.get('error','')}\n", "err")

        # ── 提交任务(走 HTTP REST) ───────────────────────────

        async def do_submit():
            design = design_select.value
            if not design:
                return
            submit_btn.disable()
            cs["step_round"] = {}; cs["current_step_id"] = None; cs["view_step_id"] = None
            cs["step_store"] = {}; cs["total_cost"] = 0.0
            cs["total_tokens"] = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "reasoning": 0}
            cs["banner_shown"] = False
            cs["_finished_hook_done"] = False
            update_cost_display()
            # 加载 workflow steps(HTTP)
            try:
                # POST /api/task 会设置 state.design_name,之后 /api/workflow-steps 才能用
                code, body = await _api_post(port, "/api/task", {"design": design})
                if code != 202:
                    ui.notify(body.get("error", "启动失败"), type="negative")
                    submit_btn.enable()
                    return
                ws = await _api_get(port, "/api/workflow-steps")
                cs["step_order"] = [s["id"] for s in ws.get("steps", [])]
                for st in ws.get("steps", []):
                    cs["step_config"][st["id"]] = st
            except Exception as e:
                ui.notify(f"加载失败: {e}", type="negative")
                submit_btn.enable()
                return
            build_flowchart()
            reset_center_empty()
            timer.activate()

        # ── 事件泵 ────────────────────────────────────────────

        async def pump_events():
            iterator = state.event_iterator
            if iterator is None:
                # iterator 被清意味着 workflow 结束(engine.run() 返回,
                # _run_in_background 的 finally 调了 clear_active_task)。
                # Senza 不发 succeeded/aborted 事件,这里做收尾。
                if not cs.get("_finished_hook_done"):
                    cs["_finished_hook_done"] = True
                    timer.deactivate()
                    submit_btn.enable()
                    # 查最终 status 更新状态徽章
                    try:
                        s = await _api_get(port, "/api/status")
                        st = s.get("state", "")
                        if st == "succeeded":
                            set_status_badge("done", "Done")
                        elif st == "failed":
                            set_status_badge("failed", "Failed")
                        elif st == "cancelled":
                            set_status_badge("cancelled", "Cancelled")
                        else:
                            set_status_badge("done", st.capitalize())
                        if s.get("total_cost") is not None:
                            cs["total_cost"] = s["total_cost"]
                        if s.get("total_tokens"):
                            cs["total_tokens"] = s["total_tokens"]
                        update_cost_display()
                    except Exception:
                        pass
                return
            loop = asyncio.get_event_loop()
            for _ in range(20):
                event = await loop.run_in_executor(None, _next_event, iterator)
                if event is None:
                    break
                if isinstance(event, dict) and event.get("type") == "lagged":
                    continue
                handle_event(event)

        timer = ui.timer(0.3, pump_events)
        timer.deactivate()

        # ── 初始化:加载 designs + 同步 status(全走 HTTP) ─────

        async def init_load():
            try:
                d = await _api_get(port, "/api/designs")
                names = d.get("designs") or ["uart"]
                logger.info("init_load: designs=%s", names)
                design_select.set_options(names)
                if state.design_name:
                    design_select.value = state.design_name
            except Exception as e:
                logger.warning("init_load: designs failed: %s", e)
            try:
                s = await _api_get(port, "/api/status")
                if s.get("running"):
                    submit_btn.disable()
                    if s.get("design"):
                        try:
                            ws = await _api_get(port, "/api/workflow-steps")
                            cs["step_order"] = [x["id"] for x in ws.get("steps", [])]
                            for st in ws.get("steps", []):
                                cs["step_config"][st["id"]] = st
                            build_flowchart()
                        except Exception as e:
                            logger.warning("init_load: workflow-steps failed: %s", e)
                    timer.activate()
                if s.get("total_cost") is not None:
                    cs["total_cost"] = s["total_cost"]
                if s.get("total_tokens"):
                    cs["total_tokens"] = s["total_tokens"]
                update_cost_display()
            except Exception as e:
                logger.warning("init_load: status failed: %s", e)

        await init_load()

    return app


def run_nicegui_desktop(config_path: str, window_size: tuple[int, int] = (1280, 800)) -> None:
    """启动 NiceGUI 桌面窗口。"""
    os.environ["EDA_STUDIO_CONFIG"] = config_path
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    from .cli import _workflow_runner
    app = create_app(workflow_runner=_workflow_runner, port=_DEFAULT_PORT)
    from nicegui import ui
    logger.info("启动 EDA Studio 桌面应用 (window %dx%d)", *window_size)
    ui.run(
        native=True,
        window_size=window_size,
        title="EDA Studio",
        dark=True,
        reload=False,
        show=False,
        port=_DEFAULT_PORT,
        uvicorn_logging_level="warning",
    )
