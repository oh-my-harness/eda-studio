# EDA Studio — Agent Context

## 项目概述

EDA Studio 是基于 [Senza](https://github.com/oh-my-harness/Senza) SDK 的开源 EDA 自动化芯片设计项目，完成 RTL→GDS 全流程。独立仓库，通过 `pip install senza-sdk` 引入依赖。提供 CLI(`init`/`check`/`run`/`restore`/`status`/`serve`)和 Web UI 两种使用方式。

设计文档：[`docs/eda-studio-design.md`](docs/eda-studio-design.md)
开发期笔记：[`docs/dev-notes.md`](docs/dev-notes.md)

## Docker 容器使用方法

### 镜像

`hpretl/iic-osic-tools:latest` — 包含全部 EDA 工具 + Sky130 PDK，ARM64 原生支持。

### 启动容器

```bash
docker run -d --name eda-tools \
  -v $(pwd)/designs:/work/designs \
  -e PDK=sky130A \
  hpretl/iic-osic-tools:latest \
  --skip sleep infinity
```

**注意**：必须用 `--skip sleep infinity`。镜像的 entrypoint 脚本默认启动 VNC/X11 桌面环境，`--skip` 跳过 UI 启动并执行后续命令。直接传 `tail -f /dev/null` 会被 entrypoint 拒绝（报 "Unexpected option"）。

### 调用容器内工具

**必须用 `bash -lc`**（login shell）。entrypoint 脚本通过 login profile 设置 PATH 和环境变量，直接 `docker exec eda-tools verilator` 会报 "executable file not found"。

```bash
# 正确 ✓
docker exec eda-tools bash -lc 'verilator --version'
docker exec eda-tools bash -lc 'yosys -V'
docker exec eda-tools bash -lc 'openroad -version'

# 错误 ✗
docker exec eda-tools verilator --version
```

### 已验证的工具版本

| 工具 | 版本 | 路径 |
|------|------|------|
| verilator | 5.048 | `/foss/tools/bin/verilator` |
| yosys | 0.66 | `/foss/tools/bin/yosys` |
| openroad | 26Q2-2270 | `/foss/tools/bin/openroad` |
| magic | 8.3 rev 664 | `/foss/tools/bin/magic` |
| netgen | 1.5.321 | `/foss/tools/bin/netgen` |
| klayout | 0.30.9 | `/foss/tools/klayout/klayout` |

### Sky130 PDK

- `PDK=sky130A`，`PDKPATH=/foss/pdks/sky130A`
- 标准单元库：`sky130_fd_sc_hd`（在 `/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/`）
- 其他可用库：`sky130_fd_io`、`sky130_fd_pr`、`sky130_fd_sc_hvl`、`sky130_ml_xx_hd`
- **注意**：容器默认 `STD_CELL_LIBRARY` 可能是 `sg13g2_stdcell`（IHP PDK），使用前需在 config 或命令中显式指定 `sky130_fd_sc_hd`

### magic / netgen 特殊参数

这两个工具是 Tcl 解释器，版本检查方式与常规不同：

```bash
# magic — 无 -version 参数，用 -noconsole -dnull 启动后看输出
docker exec eda-tools bash -lc 'magic -noconsole -dnull <<< "exit"' | head -5

# netgen — 需 -noconsole 避免 display 错误
docker exec eda-tools bash -lc 'netgen -noconsole <<< "exit"' | head -5
```

### 容器管理

```bash
# 停止
docker stop eda-tools

# 启动（已创建）
docker start eda-tools

# 删除重建
docker rm -f eda-tools
docker run -d --name eda-tools -v $(pwd)/designs:/work/designs -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity
```

---

## Senza SDK 依赖

### 版本

- **senza-sdk**(版本见 `pyproject.toml`,当前 0.4.5;从 PyPI 安装 `pip install senza-sdk`)
- import 名：`senza`（包名 `senza-sdk`）
- abi3 wheel，支持 Python 3.9–3.14+

### 仓库关系

本项目是上游 SDK 的**消费者**，不修改任何上游源码。两个上游仓库：

| 仓库 | GitHub | 本地路径 | 职责 | 可否查看源码 |
|------|--------|---------|------|------------|
| Senza | `oh-my-harness/Senza` | `../Senza/` | Python SDK（PyO3 封装） | 可以查看，不可修改 |
| Runtime | `oh-my-harness/llm-harness-runtime` | `../llm-harness-runtime/` | Rust 运行时核心（PyO3 后端） | 可以查看，不可修改 |

- 如需本地开发 Senza，在 Senza 仓库的 `.venv` 中 `pip install -e .`，或用 `scripts/install-senza-dev.sh`
- 设计文档存放在本仓库：`docs/eda-studio-design.md`

### Issue 路由

遇到上游问题时，按以下规则提 issue（**先提 issue，不要自行绕过**）：

| 问题类型 | 提 issue 到 | 示例 |
|---------|-----------|------|
| Senza Python 接口功能不足/不完善/文档不清 | `https://github.com/oh-my-harness/Senza/issues` | API 签名歧义、stub 缺 docstring、Python 层 bug |
| Runtime 核心功能不足/bug（Rust 层） | `https://github.com/oh-my-harness/llm-harness-runtime/issues` | workflow 引擎行为不符预期、hook 触发时机错误、崩溃恢复数据丢失 |

判断依据：问题出在 Python 可见的行为（API 签名、返回值、文档）→ Senza；问题出在引擎内部逻辑（需要读 Rust 源码才能定位）→ Runtime。不确定时先提 Senza，由维护者判断是否转 Runtime。

---

## 架构关键约定

### 集成模式

`WorkflowEngine` 编排流程，LLM 步骤（`prompt` + `allowed_tools`）和 executor 步骤混用。工具通过 `.with_tool()` 注册到 engine 级别，LLM 步骤通过 `allowed_tools` 声明可用子集。

**关键设计决策**：LLM 步骤用 workflow 原生 LLM step（`prompt` + `allowed_tools`），不用 executor 包装 AgentHarness。原因：

1. WorkflowEngine 原生支持 LLM step 和 executor step 混用，这是 senza 的设计意图
2. hooks、compaction、context 管理、usage 统计等引擎原生能力自动生效
3. 工具通过 `.with_tool()` 注册到 engine 级别，通过 `allowed_tools` 控制每步可用子集
4. judge 逻辑统一（LLM step 和 executor step 的 result 都有 `output` 字段）

### Workflow 节点

| step_id | 类型 | 说明 |
|---------|------|------|
| `rtl_tx` | LLM step | LLM 设计 uart_tx.v 发送器模块 |
| `rtl_rx` | LLM step | LLM 设计 uart_rx.v 接收器模块 |
| `rtl_top` | LLM step | LLM 设计 uart.v 顶层模块(例化 tx+rx) |
| `simulate` | executor | verilator 编译+仿真 |
| `debug_fix` | LLM step | LLM 读仿真报告/波形，修复 RTL |
| `synthesize` | executor | yosys 综合，输出 netlist |
| `pnr` | executor | OpenROAD floorplan→routing |
| `drc_fix` | LLM step | LLM 读 DRC 报告，修复约束/RTL |
| `drc` | executor | DRC/LVS 检查（magic/netgen） |
| `gds` | executor | 导出 GDSII（klayout） |
| `render` | executor | GDS → PNG 渲染预览（klayout） |

### Judge 路由

- 仿真失败 → `debug_fix` → 重跑 `simulate`（max_retries=3）
- DRC 失败 → `drc_fix` → 重跑 `pnr`（max_retries=3）
- RTL step:模型必须调了工具(write_rtl)才算完成;没调工具 → retry,耗尽 → abort:done
- gds 成功 → render;render 后 → abort:done(宽容:GDS 已产出即算 succeeded)
- 超过重试次数 → `abort:done`

### EDA 工具调用安全
EDA 工具**不作为 LLM tool**(太危险),而是作为 executor 步骤由 workflow 编排固定调用。LLM 只能通过内置 FsToolsPlugin(read/write/edit/bash)操作设计文件和报告。shell_safety 白名单 + denied_args 作为额外防护层。

### max_tokens 配置(关键)

`build_workflow` 调用 `.with_max_tokens(16384)`。glm-5.2 等 reasoning 模型的 thinking 链约 8K token,8192 会导致 thinking 没结束就触发 MaxTokens 截断,content 和 tool_call 无法输出——表现为流程"卡住"无输出。同时 `.with_thinking_level("high")` 与 omp 对齐(reasoning_effort=high)。

### 可见性与 Web UI

**CLI 可见性**：`cmd_run` 用后台线程跑 `engine.run()`，主线程迭代 `engine.subscribe()` 实时打印 WorkflowEvent（step_started/step_finished/step_progress）。关键点：

1. `subscribe()` 必须在 `run()` 之前调用，否则早期事件被 broadcast channel 丢弃
2. senza 的 `WorkflowEventIterator` 超时也抛 `StopIteration`，不能据此退出循环——只能靠 `done.is_set()`（run 线程结束）退出
3. `WorkflowEvent` 不暴露 token 流（reasoning/text delta 被故意裁剪），可见性上限是 step 级 + tool 调用级

**Web UI**：`serve` 子命令启动 FastAPI + WebSocket + 单页前端：

- `eda_studio/server.py` — 路由：`POST /api/task`、`GET /api/status`、`GET /api/report/{step}`、`GET /api/render.png`、`WS /ws`
- `eda_studio/state.py` — AppState（engine/event_iterator/task_running）
- `eda_studio/main.py` — serve 入口 + workflow_runner（后台线程）
- `static/index.html` — 三栏：左 workflow 流程图、中 step 输出、右事件时间线

`workflow_runner` 中 `subscribe()` 也必须在 `engine.run()` 之前调用，存到 `state.event_iterator` 供 WS 转发。

---

## 开发环境

- **Python**: 3.9+（宿主机 3.12，容器内 3.12）
- **宿主机**: macOS arm64（Apple Silicon）
- **Docker**: Docker Desktop

### venv 与依赖

```bash
# 1. 创建 venv
python3 -m venv .venv
source .venv/bin/activate

# 2. 安装本项目(含 senza-sdk from PyPI)
pip install -e .
```

如需本地开发 Senza(改 Rust/Python 源码):

```bash
./scripts/install-senza-dev.sh   # maturin develop,增量编译
```

前提：`../Senza` 是同级 checkout。Senza 的 Cargo.toml 用 git 依赖锁定 runtime 到 `runtime.lock` 里的 commit，从 GitHub fetch——**不是本地 path 依赖**。`../llm-harness-runtime` 仅用于读源码理解行为，不参与构建。

- **测试**: `pytest`，不依赖真实 EDA 工具和 LLM API（用 mock executor + mock agent）

---

## 不做的事

- 不修改 Senza / Runtime 源码（本项目是纯消费者，但**可以查看**上游源码用于理解行为和定位问题）
- 遇到上游功能不足或 bug，按「Issue 路由」章节提 issue，不自行绕过
- 不做 EDA 工具安装脚本（用 Docker 镜像）
- 不追求工业级 PPA 优化（教学项目）
- 不做多工艺库切换（只用 Sky130）
