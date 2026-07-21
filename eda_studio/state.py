"""AppState — 共享应用状态,跨 HTTP/WS handler。

持有 workflow engine、event iterator、task 运行标志。
FastAPI 单 asyncio loop,workflow 跑后台线程;task_running/handles
靠 GIL + asyncio 协作调度串行化。
"""
from __future__ import annotations

from typing import Any


class AppState:
    """共享应用状态。

    Fields:
        task_running: 是否有 workflow 任务正在运行(单任务强制)。
        engine: 持久化的 WorkflowEngine。提交任务时设置。
        event_iterator: engine.subscribe() 返回的事件迭代器。
        task_id: workflow task ID(engine.task_id())。
        design_name: 当前运行的设计名(如 "uart")。
    """

    def __init__(self) -> None:
        self.task_running: bool = False
        self.engine: Any = None
        self.event_iterator: Any = None
        self.task_id: str | None = None
        self.design_name: str | None = None

    def status_snapshot(self) -> dict:
        """返回可序列化的 workflow 运行时状态快照。"""
        engine = self.engine
        if engine is None:
            return {
                "running": False,
                "state": "idle",
                "current_step": None,
                "task_id": None,
                "total_cost": None,
                "total_tokens": None,
                "step_history": [],
                "design": self.design_name,
            }
        try:
            cost_aggregate = engine.total_cost()
            total_cost = cost_aggregate.get("total_cost", 0.0)
            total_tokens = {
                "input": cost_aggregate.get("total_input_tokens", 0),
                "output": cost_aggregate.get("total_output_tokens", 0),
                "cache_read": cost_aggregate.get("total_cache_read_tokens", 0),
                "cache_write": cost_aggregate.get("total_cache_write_tokens", 0),
                "reasoning": cost_aggregate.get("total_reasoning_tokens", 0),
            }
        except Exception:
            total_cost = 0.0
            total_tokens = None
        try:
            history = engine.step_history()
        except Exception:
            history = []
        return {
            "running": self.task_running,
            "state": engine.state(),
            "current_step": engine.current_step(),
            "task_id": self.task_id,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "step_history": history,
            "design": self.design_name,
        }

    def clear_active_task(self) -> None:
        """清除任务运行时句柄(engine/iterator/task_id),保留 design_name。

        design_name 保留是因为 workflow 完成后前端仍要按它取产物
        (render.png / report)。engine 等句柄不可继续使用,必须清掉。
        """
        self.engine = None
        self.event_iterator = None
        self.task_id = None
