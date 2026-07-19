"""Budget 超限回调(G1)。"""
import logging
from .config import AppConfig

logger = logging.getLogger(__name__)


def make_budget_cb(config: AppConfig):
    """返回 False 停止流程,True 继续。"""
    def on_budget_exceeded(cost: dict, limit: float) -> bool:
        logger.warning(f"预算超限!已用 ${cost.get('total_cost', 0):.2f} / ${limit:.2f}")
        return config.budget_exceeded_action == "continue"
    return on_budget_exceeded
