"""LLM 步骤的 prompt 模板。无 senza 依赖。

根据 design_config 的 modules 动态生成 rtl step prompt,
不再硬编码 UART 模块名。
"""
from pathlib import Path

RTL_MODULE_PROMPT = """你是一个数字电路设计专家。请根据以下需求设计模块。

设计需求:
{requirement}

本次任务:只设计 `{module_name}` 模块({step_name})。
{prompt_hint}

约束:
- 可综合 Verilog(不含 initial/$display/$finish 等)
- 同步复位(rst_n 低有效)
- 顶层双向 pad(inout)用三态赋值 `assign sda = drv ? 1'bz : 1'b0` 可综合,
  但 yosys 对 tri-state 支持有限会告警;ASIC pad 流程建议用专用 IO 单元

要求:
1. 用 read 工具读取 rtl/ 下已写的模块了解接口风格(第一个模块跳过);read 目录可列文件
2. 如果 rtl/{file} 已存在,先 read 检查内容是否已满足需求——若完全正确可跳过 write,说明理由即可
3. 否则用 write 工具(path 参数传 "rtl/{file}")写入模块代码
4. 如果模块较大,先 write 写端口和骨架,再用 edit 逐步追加状态机/逻辑(每次 <100 行)
5. 用 read 目录 rtl/ 确认文件已写入
6. 不要写 testbench,不要写其他模块

重要:每次 write 的 content 不要太长(建议 <100 行)。"""

DEBUG_FIX_PROMPT = """仿真失败了。请分析报告并修复 RTL。

1. 用 read 工具读取 sim/report.txt(仿真报告)
2. 用 read 工具读取 rtl/ 下的相关 RTL 代码
3. 分析失败原因(语法错误、时序违例、功能错误、verilator lint 警告等)
4. 用 edit 精准替换出问题的代码行(先 read 拿行号和 tag,再 edit swap);改动大时用 write 全量重写
5. 修复 verilator lint 警告(如 WIDTHEXPAND 位宽不匹配):修正信号位宽,或用 /* verilator lint_off */ 抑制"""

DRC_FIX_PROMPT = """DRC 检查失败了。请分析报告并修复。

1. 用 read 工具读取 pnr/drc.rpt(DRC 报告)
2. 用 read 工具读取 pnr/{top}.sdc(时序约束)
3. 用 read 工具读取 rtl/ 下的相关 RTL
4. 用 write/edit 写入修复(SDC 问题用 write 写 pnr/{top}.sdc,RTL 小改用 edit,大改用 write)"""


def load_requirement(design_name: str) -> str:
    """从 designs/<design_name>/requirement.md 读取设计需求文本。"""
    path = Path(f"designs/{design_name}/requirement.md")
    return path.read_text() if path.exists() else ""

def build_prompts(requirement: str, modules: list, top_module: str = "") -> dict:
    """构建各 LLM 步骤的 prompt。

    Args:
        requirement: 设计需求文本(requirement.md)
        modules: list[ModuleSpec],每个模块对应一个 rtl_<id> step
        top_module: 顶层模块名,用于 DRC_FIX_PROMPT 的 SDC 路径(如 pnr/uart.sdc)

    Returns:
        {step_id: prompt} dict,step_id 为 rtl_<id> / debug_fix / drc_fix
    """
    prompts = {}
    for m in modules:
        prompts[f"rtl_{m.id}"] = RTL_MODULE_PROMPT.format(
            requirement=requirement,
            module_name=m.module_name,
            step_name=m.name,
            prompt_hint=m.prompt_hint,
            file=m.file,
        )
    prompts["debug_fix"] = DEBUG_FIX_PROMPT
    prompts["drc_fix"] = DRC_FIX_PROMPT.format(top=top_module) if top_module else DRC_FIX_PROMPT
    return prompts
