"""日志/审计 hooks + MaxTokens auto-continue。

should_stop: MaxTokens 截断 → 返回 False(继续)让模型续输,最多 max_auto_continue 次。
其他情况 → 正常停止。

MaxTokens 续输有独立计数器。judge retry 重跑 step 时计数不重置——
一个 step 内的续输预算是全局的,避免复杂 step 反复截断重试。
"""
import logging

from .config import AppConfig

logger = logging.getLogger(__name__)


# ── 日志/审计 hooks ─────────────────────────────────────────────

def make_hooks(config: AppConfig):
    """返回 hook 闭包列表(before_turn/after_turn/after_tool_call)。"""
    def log_before_turn(ctx: dict) -> None:
        turn = ctx.get("turn_index", "?")
        sp = ctx.get("system_prompt")
        sp_preview = (sp[:80] + "...") if sp and len(sp) > 80 else sp
        logger.info(f"▶ turn {turn} 开始 system_prompt={sp_preview!r}")

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
        latency = ctx.get("latency_ms", 0)
        usage = ctx.get("usage") or {}
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        reasoning = usage.get("reasoning_tokens", 0)
        logger.info(
            f"  provider: status={status} latency={latency}ms "
            f"in={inp} out={out} reasoning={reasoning}"
        )
    return log_response


# ── MaxTokens auto-continue ────────────────────────────────────

def make_max_tokens_continue_hook(max_auto_continue: int = 3):
    """创建 should_stop hook:MaxTokens 截断时返回 False 让模型续输。

    glm-5.2 的 thinking 链可能超过 max_tokens 被截断,此时模型还没输出
    tool_call。返回 False 让 runtime 自动续输,模型从断点继续输出。
    最多续输 max_auto_continue 次,超限则停止(防失控)。
    """
    auto_continue_count = 0

    def should_stop_cb(ctx: dict) -> bool:
        nonlocal auto_continue_count
        stop_reason = ctx.get("stop_reason", "")

        if stop_reason == "max_tokens":
            if auto_continue_count < max_auto_continue:
                auto_continue_count += 1
                logger.info(
                    f"MaxTokens 截断,auto-continue ({auto_continue_count}/{max_auto_continue})"
                )
                return False
            else:
                logger.warning(
                    f"auto-continue 次数耗尽({max_auto_continue}),停止"
                )
                return True

        return True

    return should_stop_cb
