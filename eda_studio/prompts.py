"""LLM 步骤的 prompt 模板。无 senza 依赖。"""
from pathlib import Path

RTL_DESIGN_PROMPT = """你是一个数字电路设计专家。请根据以下需求设计 Verilog RTL:

设计需求:
{requirement}

要求:
1. 写出可综合的 Verilog 代码(不含 initial、$display 等不可综合结构)
2. 用 write_rtl 工具将代码写入 rtl/ 目录(filename 用模块名,如 uart_tx.v)
3. 用 list_design_files 确认文件已写入
4. testbench(tb_uart.v)已预置,不要写 testbench
"""

DEBUG_FIX_PROMPT = """仿真失败了。请分析报告并修复 RTL。

1. 用 read_sim_report 读取仿真报告(含错误行和失败断言)
2. 用 read_rtl 读取当前 RTL 代码
3. 分析失败原因(语法错误、时序违例、功能错误等)
4. 用 write_rtl 写入修复后的代码(保持 filename 不变)
"""

DRC_FIX_PROMPT = """DRC 检查失败了。请分析报告并修复。

1. 用 read_drc_report 读取 DRC 报告
2. 用 read_sdc 读取时序约束
3. 用 read_rtl 读取相关 RTL
4. 分析失败原因(可能是约束问题或 RTL 问题)
5. 用 write_sdc 或 write_rtl 写入修复
"""


def load_requirement(design_name: str) -> str:
    """从 designs/<design_name>/requirement.md 读取设计需求文本。"""
    path = Path(f"designs/{design_name}/requirement.md")
    return path.read_text() if path.exists() else ""


def build_prompts(requirement: str) -> dict:
    """构建各 LLM 步骤的 prompt,注入设计需求。"""
    return {
        "rtl_design": RTL_DESIGN_PROMPT.format(requirement=requirement),
        "debug_fix": DEBUG_FIX_PROMPT,
        "drc_fix": DRC_FIX_PROMPT,
    }
