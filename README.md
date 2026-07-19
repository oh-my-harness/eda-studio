# EDA Studio

> 基于 [Senza](https://github.com/oh-my-harness/Senza) SDK 和开源 EDA 工具的 RTL→GDS 自动化芯片设计流程。

EDA Studio 使用 LLM 生成 Verilog RTL，并通过开源 EDA 工具链（verilator + yosys + OpenROAD）完成仿真、综合、布局布线、DRC 检查和 GDSII 导出。失败时 LLM 介入分析报告并修复，整个流程由 Senza 的 WorkflowEngine 编排。

## 快速开始

### 1. 环境准备

```bash
# 安装 Python 依赖
pip install -e .

# 启动 EDA 工具容器（包含 verilator/yosys/OpenROAD/magic/netgen/klayout + Sky130 PDK）
docker run -d --name eda-tools \
  -v $(pwd)/designs:/work/designs \
  -e PDK=sky130A \
  hpretl/iic-osic-tools:latest \
  tail -f /dev/null
```

### 2. 配置

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入 LLM provider API key
```

### 3. 运行

```bash
# 运行完整 RTL→GDS 流程
python -m eda_studio run uart

# 从中断处恢复
python -m eda_studio restore uart

# 查看状态
python -m eda_studio status uart
```

## 架构

```
WorkflowEngine（外层编排）
├── rtl_design   (AgentHarness: LLM 生成 Verilog)
├── simulate     (executor: verilator 仿真)
├── debug_fix    (AgentHarness: LLM 分析报告+修复 RTL)
├── synthesize   (executor: yosys 综合)
├── pnr          (executor: OpenROAD 布局布线)
├── drc_fix      (AgentHarness: LLM 分析 DRC+修复)
├── drc          (executor: DRC/LVS 检查)
└── gds          (executor: GDSII 导出)
```

Judge 根据每步报告决定路由：仿真失败→debug_fix→重跑仿真；DRC 失败→drc_fix→重跑 PnR。

## 展示的 Senza 能力

- **WorkflowEngine**：声明式 workflow、judge 条件路由、executor 步骤
- **AgentHarness**：内嵌于 executor 中，多轮 LLM 对话、工具调用、streaming
- **多 Provider**：glob 模式路由不同模型（gpt-4o / deepseek / claude）
- **Hooks**：日志、成本审计、文件变更追踪
- **崩溃恢复**：`with_task_store` + `WorkflowEngine.restore()`
- **Budget 控制**：成本超限自动停止
- **Rules 审批**：shell 命令白名单防护
- **Pricing**：多 provider 成本统计

## 设计文档

见 [design spec](../Senza/docs/superpowers/specs/2026-07-18-eda-studio-design.md)。

## License

MIT
