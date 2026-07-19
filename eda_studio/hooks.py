"""日志/审计 hooks。senza 装饰器在 workflow.py 应用。"""
import logging
from .config import AppConfig

logger = logging.getLogger(__name__)


def make_hooks(config: AppConfig):
    """返回 hook 闭包列表(before_turn/after_turn/after_tool_call)。"""
    def log_before_turn(ctx: dict) -> None:
        turn = ctx.get("turn_index", "?")
        logger.info(f"▶ turn {turn} 开始")

    def log_after_turn(ctx: dict) -> None:
        turn = ctx.get("turn_index", "?")
        logger.info(f"✓ turn {turn} 完成")

    def audit_tool_call(ctx: dict) -> str:
        tool_name = ctx.get("tool_name", "")
        logger.info(f"  tool call: {tool_name}")
        return "passthrough"  # 审计只记录,不改结果

    return [log_before_turn, log_after_turn, audit_tool_call]
