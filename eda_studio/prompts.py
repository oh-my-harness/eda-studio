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

要求:
1. 用 read_rtl 读取已写的模块了解接口风格(第一个模块跳过)
2. 用 write_rtl 工具(filename 参数传 "{file}")写入模块代码
3. 如果模块较大,用 append_rtl 分多次追加(先写端口和骨架,再追加状态机/逻辑)
4. 用 list_design_files 确认文件已写入
5. 不要写 testbench,不要写其他模块

重要:每次 write_rtl/append_rtl 的 content 不要太长(建议 <100 行)。
如果一次写不完,先 write_rtl 写骨架,再用 append_rtl 逐步追加。"""

DEBUG_FIX_PROMPT = """仿真失败了。请分析报告并修复 RTL。

1. 用 read_sim_report 读取仿真报告(含错误行和失败断言)
2. 用 read_rtl 读取当前 RTL 代码
3. 分析失败原因(语法错误、时序违例、功能错误等)
4. 用 edit_rtl 精准替换出问题的代码片段(old_code=原代码,new_code=修复后代码);改动大时用 write_rtl 全量重写"""

DRC_FIX_PROMPT = """DRC 检查失败了。请分析报告并修复。

1. 用 read_drc_report 读取 DRC 报告
2. 用 read_sdc 读取时序约束
3. 用 read_rtl 读取相关 RTL
4. 用 write_sdc/edit_rtl/write_rtl 写入修复(SDC 问题用 write_sdc,RTL 小改用 edit_rtl,大改用 write_rtl)"""


def load_requirement(design_name: str) -> str:
    """从 designs/<design_name>/requirement.md 读取设计需求文本。"""
    path = Path(f"designs/{design_name}/requirement.md")
    return path.read_text() if path.exists() else ""


def build_prompts(requirement: str, modules: list) -> dict:
    """构建各 LLM 步骤的 prompt。

    Args:
        requirement: 设计需求文本(requirement.md)
        modules: list[ModuleSpec],每个模块对应一个 rtl_<id> step

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
    prompts["drc_fix"] = DRC_FIX_PROMPT
    return prompts
