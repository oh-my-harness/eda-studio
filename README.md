# EDA Studio

基于 [Senza](https://github.com/oh-my-harness/Senza) 的开源 EDA 自动化芯片设计流程示例。

## 快速开始

```bash
# 1. 安装依赖(含 Senza 本地源码 editable 安装)
./scripts/install-senza-dev.sh
pip install -e .

# 2. 启动 EDA 工具容器(Verilator/Yosys/OpenROAD/Magic/KLayout)
docker run -d --name eda-tools -v $(pwd)/designs:/work/designs \
  -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity

# 3. 配置 LLM(从 .env 加载,或编辑 config.yaml)
cp config.example.yaml config.yaml

# 4a. CLI 运行(实时输出 step/tool 事件)
python -m eda_studio run uart

# 4b. 或启动 Web UI(浏览器访问 http://localhost:3000)
python -m eda_studio serve --port 3000
```

## 命令

| 命令 | 说明 |
|------|------|
| `run <design>` | 运行设计流程,终端实时打印 step/tool 事件 |
| `serve` | 启动 Web UI(FastAPI + WebSocket),浏览器查看 workflow 进度 |
| `restore <design>` | 从断点恢复 |
| `status <design>` | 查看状态 |

## Web UI

`python -m eda_studio serve` 启动后,浏览器访问 `http://localhost:3000`:

- 左栏:10 步 workflow 流程图(rtl_tx → rtl_rx → rtl_top → simulate → ... → gds),实时高亮当前 step
- 中栏:当前 step 的工具调用和输出
- 右栏:事件时间线

## Workflow

UART 设计流程 10 步:

``+rtl_tx → rtl_rx → rtl_top → simulate → synthesize → pnr → drc → gds
                                ↑↓              ↑↓        ↑↓
                            debug_fix       debug_fix   drc_fix
``+

LLM 步骤(rtl_tx/rtl_rx/rtl_top/debug_fix/drc_fix)按模块拆分,避免单步 prompt 过复杂导致 reasoning 过长。Executor 步骤(simulate/synthesize/pnr/drc/gds)调用容器内 EDA 工具。

## 配置

`config.yaml`(从 `config.example.yaml` 复制):

- `provider` / `model`:OpenAI 兼容端点(支持 `${ENV_VAR}` 展开)
- `budget.limit`:预算上限(默认 $5)
- `docker`:EDA 工具容器配置
- `shell`:允许的命令白名单和禁止的参数

`max_tokens` 在代码中固定为 32768(glm-5.2 thinking ~8K token,默认 8192 会截断)。

## 设计参考

Web UI 架构参考同仓库的 [blender-scene-generator](../blender-scene-generator)。
