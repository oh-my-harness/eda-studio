"""日志/审计 hooks + 空响应纠正。

should_stop + transform_context 组合:
- should_stop: 检测模型 EndTurn 没调工具 → 返回 False(继续 turn) + 标记
- transform_context: 检测标记 → 往 messages 追加 nudge(响应式反馈)

这是响应式纠错:模型出错时反馈,不在 prompt 里主动注入。
有 max_retries 计数器防止无限循环。
"""
import datetime
import logging
from .config import AppConfig

logger = logging.getLogger(__name__)

_NUDGE_TEXT = (
    "你上一轮没有调用任何工具就直接结束了。"
    "请实际调用工具来推进任务:读取报告、读取 RTL、写入修复代码等。"
    "不要只在思考中计划,必须发出 tool_use。"
)


# ── 日志/审计 hooks ─────────────────────────────────────────────

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
        return "passthrough"

    return [log_before_turn, log_after_turn, audit_tool_call]


def make_provider_response_logger():
    """创建 after_provider_response hook,记录 HTTP 状态码/延迟/token 用量。"""
    def log_response(ctx: dict) -> None:
        status = ctx.get("status_code")
        latency = ctx.get("latency_ms")
        usage = ctx.get("usage") or {}
        logger.info(
            f"  provider: status={status} latency={latency}ms "
            f"in={usage.get('input_tokens')} out={usage.get('output_tokens')} "
            f"reasoning={usage.get('reasoning_tokens')}"
        )
    return log_response


# ── 空响应纠正 hooks ────────────────────────────────────────────

def _has_tool_use(content) -> bool:
    """assistant content 是否含 tool_use 块。"""
    if not isinstance(content, list):
        return False
    return any(b.get("type") == "tool_use" for b in content)


def make_empty_response_nudge_hooks(max_retries: int = 3):
    """创建 should_stop + transform_context hook 对,共享重试计数器。

    should_stop: 模型 EndTurn 且 last_assistant 无 tool_use → 返回 False
    (继续 turn),标记需要 nudge。有 max_retries 防止无限循环。
    transform_context: 检测标记 → 往 messages 追加 nudge user 消息。
    """
    state = {"empty_count": 0, "need_nudge": False}

    def should_stop_cb(ctx: dict) -> bool:
        stop_reason = ctx.get("stop_reason", "")
        last_assistant = ctx.get("last_assistant") or {}
        content = last_assistant.get("content", [])

        # 非 EndTurn(如 MaxTokens)或已调工具 → 正常停止
        if stop_reason != "end_turn" or _has_tool_use(content):
            state["need_nudge"] = False
            return True

        # EndTurn 且无 tool_use → 空响应
        state["empty_count"] += 1
        if state["empty_count"] > max_retries:
            logger.warning(f"空响应重试 {state['empty_count']} 次,超限放弃")
            state["need_nudge"] = False
            return True  # 停止,让 judge 决策(tool_calls_count=0 → retry/abort)

        logger.info(f"空响应(无 tool_use),注入 nudge 重试 {state['empty_count']}/{max_retries}")
        state["need_nudge"] = True
        return False  # 继续下一个 turn

    def transform_cb(ctx: dict) -> dict:
        if not state["need_nudge"]:
            return ctx

        state["need_nudge"] = False
        messages = ctx.get("messages", [])
        nudge_msg = {
            "role": "user",
            "content": [{"type": "text", "text": _NUDGE_TEXT}],
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        new_messages = list(messages) + [nudge_msg]
        logger.info("transform_context: 注入 nudge")
        return {
            "system_prompt": ctx.get("system_prompt"),
            "messages": new_messages,
        }

    return should_stop_cb, transform_cb
