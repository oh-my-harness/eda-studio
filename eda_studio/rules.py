"""G3 Rules 审批:限制 LLM tool_call。RuleBasedApprovalHook 实现 BeforeToolCallHook,
只拦截 LLM tool_call,拦不到 executor 内的 subprocess。
EDA 工具 shell 安全由 run_shell 白名单负责(shell_safety.py, S6a)。"""
from .config import AppConfig


def make_rules_hook(config: AppConfig):
    """构建 LLM tool_call 审批规则链。

    顺序:先 deny 危险 tool,再 allow 白名单,fallback deny。
    RuleChain 首条匹配生效,通配 Allow 必须排在特定 Deny 之后。
    """
    from senza import (
        create_rule_chain, create_contains_predicate, create_rule_approval_hook,
    )
    builder = create_rule_chain()

    builder = builder.rule(
        tool_name="*",
        predicate=create_contains_predicate(["read_drc_report", "write_sdc"]),
        on_match="deny",
    )
    builder = builder.rule(
        tool_name="*",
        predicate=create_contains_predicate(
            ["write_rtl", "read_rtl", "list_design_files", "read_sim_report", "read_sdc"]
        ),
        on_match="allow",
    )
    builder = builder.fallback("deny")
    chain = builder.build()
    return create_rule_approval_hook(chain)
