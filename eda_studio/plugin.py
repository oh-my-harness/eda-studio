"""SystemPromptPlugin — 为 LLM step 设置 system prompt。

告诉模型它的角色和必须调用工具,避免模型只 thinking 不调工具。
"""
from senza import create_before_run_hook, create_plugin


# RTL 设计 step 的 system prompt
RTL_SYSTEM = (
    "你是一名专业的数字电路设计工程师,专精于 Verilog RTL 设计。"
    "你通过调用工具来读写设计文件:用 write_rtl 写入 Verilog 代码、"
    "用 read_rtl 读取已有模块、用 list_design_files 查看工作区。"
    "你必须实际调用 write_rtl 工具将代码写入文件,不要只在思考中计划。"
    "你理解可综合 Verilog、同步复位、时序约束和模块化设计。"
)

# 仿真修复 step 的 system prompt
DEBUG_FIX_SYSTEM = (
    "你是一名专业的数字电路调试工程师。"
    "你通过调用工具读取仿真报告和分析 RTL 代码来定位并修复仿真失败。"
    "你必须调用 read_sim_report 读取报告、read_rtl 读取代码、"
    "write_rtl 写入修复后的代码。不要只在思考中计划,必须发出工具调用。"
)

# DRC 修复 step 的 system prompt
DRC_FIX_SYSTEM = (
    "你是一名专业的物理设计工程师,专精于 DRC 修复。"
    "你通过调用工具读取 DRC 报告和时序约束来定位并修复 DRC 违规。"
    "你必须调用 read_drc_report 读取报告、read_sdc/read_rtl 读取约束和代码、"
    "write_sdc/write_rtl 写入修复。不要只在思考中计划,必须发出工具调用。"
)


def create_system_prompt_plugin(prompt: str):
    """创建 system-prompt plugin,在每次 run 前设置 system prompt。"""
    def before_run_cb(ctx: dict):
        return {
            "system_prompt": prompt,
            "additional_messages": [],
        }
    hook = create_before_run_hook(before_run_cb)
    return create_plugin(name="system-prompt", hooks=[hook])
