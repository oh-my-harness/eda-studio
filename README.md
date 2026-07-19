# EDA Studio

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

基于 [Senza](https://github.com/oh-my-harness/Senza) SDK 的开源 EDA 自动化芯片设计流程示例,用 LLM + 开源 EDA 工具完成 UART RTL→GDS 全流程。

## 快速开始

```bash
# 1. 安装
pip install -e .

# 2. 初始化示例 design
eda-studio init uart

# 3. 启动 EDA 工具容器(Verilator/Yosys/OpenROAD/Magic/KLayout)
docker run -d --name eda-tools -v $(pwd)/designs:/work/designs \
  -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity

# 4. 预检环境
eda-studio check

# 5. 运行
python -m eda_studio run uart
# 或启动 Web UI
python -m eda_studio serve --port 3000
```

## 模型要求

需要能写可综合 Verilog 的强模型。已验证:

- **glm-5.2** — 开发主用模型,稳定通过全流程
- **gpt-4o** — 可用

弱模型(如小参数模型)可能在 RTL 设计阶段失败(语法错误/不可综合),表现为主程报错。

配置:复制 `config.example.yaml` 为 `config.yaml`,填入 API key/端点/模型名。支持 `${ENV_VAR}` 展开。

## 命令

| 命令 | 说明 |
|------|------|
| `init <design>` | 从模板复制 design 输入文件 |
| `check` | 预检环境(config/API/docker/PDK) |
| `run <design>` | 运行设计流程,终端实时输出 |
| `serve` | 启动 Web UI |
| `restore <design>` | 从断点恢复 |
| `status <design>` | 查看状态 |

## Web UI

`python -m eda_studio serve` 启动后,浏览器访问 `http://localhost:3000`:

- 左栏:11 步 workflow 流程图(rtl_tx → ... → gds → render),实时高亮当前 step,LLM/EXEC 类型标签
- 中栏:当前 step 的工具调用和输出,点击任意已完成 step 可回看
- 右栏:事件时间线

render step 完成后显示 GDS 渲染预览 PNG。

## Workflow

11 步流程:

```
rtl_tx → rtl_rx → rtl_top → simulate → synthesize → pnr → drc → gds → render
                      ↑↓              ↑↓        ↑↓
                  debug_fix       debug_fix   drc_fix
```

- **LLM 步骤**(绿色标签):rtl_tx/rtl_rx/rtl_top/debug_fix/drc_fix — LLM 写 Verilog/修复
- **EXEC 步骤**(蓝色标签):simulate/synthesize/pnr/drc/gds/render — 调用容器内 EDA 工具

## 配置

`config.yaml`(从 `config.example.yaml` 复制):

- `provider`/`model`:OpenAI 兼容端点,支持 `${ENV_VAR}` 展开
- `budget.limit`:预算上限(默认 $5)
- `docker`:EDA 工具容器配置
- `shell`:命令白名单和禁止参数

## 架构

- `eda_studio/workflow.py` — 组装 WorkflowEngine(steps/edges/executors/tools/hooks)
- `eda_studio/executors/` — EDA 工具回调(simulate/synthesize/pnr/drc/gds/render)
- `eda_studio/judge.py` — step 路由决策
- `eda_studio/hooks.py` — 日志/空响应纠正
- `eda_studio/cli_commands.py` — init/check 命令

详见 [CLAUDE.md](CLAUDE.md) 和 [docs/](docs/)。

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

[MIT](LICENSE)
