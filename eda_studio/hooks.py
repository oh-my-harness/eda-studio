"""日志/审计 hooks。senza 装饰器在 workflow.py 应用。"""
import logging
from .config import AppConfig

logger = logging.getLogger(__name__)


def make_hooks(config: AppConfig):
    """返回 hook 闭包列表(before_turn/after_turn/after_tool_call)。"""
    def log_before_turn(ctx: dict) -> None:
        step_id = ctx.get("step_id", "?")
        logger.info(f"▶ {step_id} 开始")

    def log_after_turn(ctx: dict) -> None:
        step_id = ctx.get("step_id", "?")
        duration = ctx.get("duration_ms", 0)
        logger.info(f"✓ {step_id} 完成 ({duration}ms)")

    def audit_tool_call(ctx: dict):
        tool_name = ctx.get("tool_name", "")
        logger.info(f"  tool call: {tool_name}")
        return None  # 审计只记录,不改结果

    return [log_before_turn, log_after_turn, audit_tool_call]
