"""LLM 步骤的 prompt 模板。无 senza 依赖。"""
from pathlib import Path

RTL_TX_PROMPT = """你是一个数字电路设计专家。请根据以下需求设计 UART 发送器模块。

设计需求:
{requirement}

本次任务:只设计 `uart_tx` 发送器模块。
- 输入: clk, rst_n, tx_start, tx_data[7:0]
- 输出: tx_busy, txd
- 波特率 115200,时钟 50MHz,数据位 8,停止位 1,无校验
- 可综合 Verilog(不含 initial/$display/$finish 等)
- 同步复位(rst_n 低有效)

要求:
1. 用 write_rtl 工具(filename 参数传 "uart_tx.v")将代码写入
2. 用 list_design_files 确认文件已写入
3. 不要写 testbench,不要写其他模块
"""

RTL_RX_PROMPT = """你是一个数字电路设计专家。请根据以下需求设计 UART 接收器模块。

设计需求:
{requirement}

本次任务:只设计 `uart_rx` 接收器模块。
- 输入: clk, rst_n, rxd
- 输出: rx_busy, rx_data[7:0], rx_valid
- 波特率 115200,时钟 50MHz,数据位 8,停止位 1,无校验
- 可综合 Verilog(不含 initial/$display/$finish 等)
- 同步复位(rst_n 低有效)

要求:
1. 用 read_rtl 读取已有的 uart_tx.v 了解接口风格
2. 用 write_rtl 工具(filename 参数传 "uart_rx.v")将代码写入
3. 用 list_design_files 确认文件已写入
4. 不要写 testbench,不要写其他模块
"""

RTL_TOP_PROMPT = """你是一个数字电路设计专家。请设计 UART 顶层模块。

设计需求:
{requirement}

本次任务:设计顶层模块 `uart`,例化已写好的 uart_tx 和 uart_rx。
- 对外暴露:clk, rst_n, tx_start, tx_data[7:0], tx_busy, txd, rxd, rx_busy, rx_data[7:0], rx_valid
- 内部例化 uart_tx 和 uart_rx,连接对应信号

要求:
1. 用 read_rtl 读取 uart_tx.v 和 uart_rx.v 确认端口
2. 用 write_rtl 工具(filename 参数传 "uart.v")将代码写入
3. 用 list_design_files 确认所有文件已写入(uart_tx.v, uart_rx.v, uart.v)
4. 不要写 testbench
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
4. 用 write_sdc 或 write_rtl 写入修复
"""


def load_requirement(design_name: str) -> str:
    """从 designs/<design_name>/requirement.md 读取设计需求文本。"""
    path = Path(f"designs/{design_name}/requirement.md")
    return path.read_text() if path.exists() else ""


def build_prompts(requirement: str) -> dict:
    """构建各 LLM 步骤的 prompt,注入设计需求。"""
    return {
        "rtl_tx": RTL_TX_PROMPT.format(requirement=requirement),
        "rtl_rx": RTL_RX_PROMPT.format(requirement=requirement),
        "rtl_top": RTL_TOP_PROMPT.format(requirement=requirement),
        "debug_fix": DEBUG_FIX_PROMPT,
        "drc_fix": DRC_FIX_PROMPT,
    }
