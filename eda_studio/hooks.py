"""日志/审计 hooks + 空响应纠正 + MaxTokens auto-continue。

should_stop + transform_context 组合:
- should_stop: MaxTokens 截断 → 返回 False(继续)让模型续输,最多 max_auto_continue 次。
  turn 0 EndTurn 且无 tool_use → 返回 False(继续) + 标记 nudge。
  其他情况 → 正常停止。
- transform_context: 检测 nudge 标记 → 往 messages 追加 nudge user 消息。

这是响应式纠错:模型出错时反馈,不在 prompt 里主动注入。
每个 step 最多 nudge 一次;MaxTokens 续输有独立计数器。
judge retry 重跑 step 时 turn 0 重新计数(但 auto_continue_count 不重置——
一个 step 内的续输预算是全局的,避免复杂 step 反复截断重试)。
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
        new_msgs = ctx.get("new_messages") or []
        # 找最后一条 assistant 消息,记录其 content 摘要(诊断空响应用)
        for m in reversed(new_msgs):
            if m.get("role") == "assistant":
                content = m.get("content", [])
                if isinstance(content, list):
                    types = [b.get("type", "?") for b in content]
                    text_preview = ""
                    for b in content:
                        if b.get("type") == "text":
                            text_preview = (b.get("text", "") or "")[:200]
                            break
                    logger.info(f"✓ turn {turn} 完成 content={types} text={text_preview!r}")
                else:
                    logger.info(f"✓ turn {turn} 完成 content={str(content)[:200]!r}")
                break
        else:
            logger.info(f"✓ turn {turn} 完成 (无 assistant 消息)")

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


def make_empty_response_nudge_hooks(max_auto_continue: int = 3, max_nudge: int = 3):
    """创建 should_stop + transform_context hook 对,共享 nudge 标记。

    should_stop 逻辑:
    1. MaxTokens 截断 → 返回 False(继续),让模型从断点续输。
       续输次数上限 max_auto_continue,超限则停止(防失控)。
    2. EndTurn 且无 tool_use → 返回 False(继续) + 标记 need_nudge。
       注入 nudge 提示必须调工具。最多 nudge max_nudge 次,超限停止(防死循环)。
    3. 已调工具 → 正常停止。

    transform_context: 检测 need_nudge 标记 → 往 messages 追加 nudge user 消息。

    reset() 在每次 step run 开始时调用(before_run hook),重置 nudge 计数。
    """
    state = {"need_nudge": False}
    auto_continue_count = 0
    nudge_count = 0

    def reset():
        """新 step run 开始时重置 nudge 计数。"""
        nonlocal nudge_count
        nudge_count = 0
        state["need_nudge"] = False

    def should_stop_cb(ctx: dict) -> bool:
        nonlocal auto_continue_count, nudge_count
        stop_reason = ctx.get("stop_reason", "")
        last_assistant = ctx.get("last_assistant") or {}
        content = last_assistant.get("content", [])

        # MaxTokens 截断:模型输出被 max_tokens 截断。
        if stop_reason == "max_tokens":
            if auto_continue_count < max_auto_continue:
                auto_continue_count += 1
                logger.info(
                    f"MaxTokens 截断,auto-continue ({auto_continue_count}/{max_auto_continue})"
                )
                state["need_nudge"] = False
                return False
            else:
                logger.warning(
                    f"MaxTokens 截断,auto-continue 次数耗尽({max_auto_continue}),停止"
                )
                state["need_nudge"] = False
                return True

        # 已调工具 → 正常停止
        if _has_tool_use(content):
            state["need_nudge"] = False
            return True

        # EndTurn 无 tool_use → nudge
        if nudge_count < max_nudge:
            nudge_count += 1
            logger.info(f"空响应(无 tool_use),注入 nudge ({nudge_count}/{max_nudge})")
            state["need_nudge"] = True
            return False
        else:
            logger.warning(f"nudge 次数耗尽({max_nudge}),停止")
            state["need_nudge"] = False
            return True

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

    return should_stop_cb, transform_cb, reset
