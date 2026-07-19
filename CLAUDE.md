# EDA Studio — Agent Context

## 项目概述

EDA Studio 是基于 [Senza](https://github.com/oh-my-harness/Senza) SDK 的开源 EDA 自动化芯片设计项目，完成 RTL→GDS 全流程。独立仓库，通过 `pip install senza-sdk` 引入依赖。

设计文档：[`docs/eda-studio-design.md`](docs/eda-studio-design.md)

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

### run_shell() 实现要点

senza 的 `executors/` 中 `run_shell()` 函数封装 docker exec 调用，要点：

1. 用 `bash -lc` 包装命令
2. 宿主机 `designs/` 路径映射到容器 `/work/designs/`，cwd 需转换
3. 设置超时（EDA 工具可能长时间运行）
4. 捕获 stdout/stderr 生成报告

```python
def run_shell(cmd: list[str], cwd: Path, docker_config: DockerConfig) -> subprocess.CompletedProcess:
    container_cwd = str(cwd).replace(str(Path("designs").resolve()), docker_config.workdir)
    docker_cmd = [
        "docker", "exec", "-w", container_cwd,
        docker_config.container,
        "bash", "-lc", " ".join(cmd),
    ]
    return subprocess.run(docker_cmd, capture_output=True, text=True, timeout=600)
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

- **senza-sdk 0.4.0**（PyPI 已发布，`pip install senza-sdk`）
- 包含 G1 Budget、G2 Pricing、G3 Rules 全部新 API（`feat/senza-api-exposure` 分支已合并到 Senza main）
- import 名：`senza`（包名 `senza-sdk`）
- abi3 wheel，支持 Python 3.9–3.14+

### G1/G2/G3 API 清单（已验证可用）

```python
import senza

# G1: Budget 控制
senza.create_budget_exceeded_hook(callback)  # cb(cost: dict, limit: float) -> bool
# builder.budget(limit, exceeded_hook)  # AgentHarness 级
# workflow 级通过 with_hooks([budget_hook]) 注入（budget_hook impl ShouldStopHook）

# G2: Pricing
senza.create_pricing_provider(table: dict)           # 静态定价表
senza.create_pricing_provider_callback(cb)           # 动态定价 cb(model, provider) -> dict|None
# builder.pricing(provider)  # 设置后 usage()["total_cost"] 才有值

# G3: Rules 审批
senza.create_rule_chain() -> RuleChainBuilder
senza.create_contains_predicate(allowed: list[str])
senza.create_regex_field_predicate(arg_path: str, pattern: str)
senza.create_number_range_predicate(arg_path: str, min: float, max: float)
senza.create_rate_limit_predicate(max: int, window_seconds: float)
senza.create_rule_approval_hook(chain: RuleChain)   # impl BeforeToolCallHook
# RuleChainBuilder.rule(tool_name, predicate, on_match).fallback(decision).build()
# on_match/decision: "allow" / "deny"
```

### Senza 仓库关系

- Senza 源码：`../Senza/`（同级目录 `oh-my-harness/Senza`）
- 本项目是 Senza 的**消费者**，不修改 Senza 源码
- 设计文档存放在本仓库：`docs/eda-studio-design.md`
- 如需调试 Senza 本身，在 Senza 仓库的 `.venv` 中 `pip install -e .`

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

| 节点 | 类型 | 职责 |
|------|------|------|
| `rtl_design` | LLM step（prompt + allowed_tools） | LLM 根据需求生成 Verilog RTL |
| `simulate` | executor | verilator 编译+仿真 |
| `debug_fix` | LLM step（prompt + allowed_tools） | LLM 读仿真报告/波形，修复 RTL |
| `synthesize` | executor | yosys 综合，输出 netlist |
| `pnr` | executor | OpenROAD floorplan→routing |
| `drc_fix` | LLM step（prompt + allowed_tools） | LLM 读 DRC 报告，修复约束/RTL |
| `drc` | executor | DRC/LVS 检查（magic/netgen） |
| `gds` | executor | 导出 GDSII（klayout） |

### Judge 路由

- 仿真失败 → `debug_fix` → 重跑 `simulate`（max_retries=3）
- DRC 失败 → `drc_fix` → 重跑 `pnr`（max_retries=3）
- 超过重试次数 → `abort:done`

### EDA 工具调用安全

EDA 工具**不作为 LLM tool**（太危险），而是作为 executor 步骤由 workflow 编排固定调用。LLM 只能通过 file_tools（读写文件）和 report_tools（读报告摘要）操作。G3 Rules 审批链作为额外防护层。

---

## 实现顺序

按设计文档 §12，分阶段实现：

| 阶段 | 内容 | 依赖 |
|------|------|------|
| P1 | 项目骨架 + `config.py` + CLI `__main__.py` | 无 |
| P2 | `tools/` + `agents/`（AgentHarness 工厂） | P1 |
| P3 | `executors/`（5 个 EDA executor + 3 个 LLM executor） | P2 |
| P4 | `workflow.py` + `judge.py`（路由逻辑） | P3 |
| P5 | `hooks.py` + `rules.py` + budget | P4 |
| P6 | 崩溃恢复 + CLI restore 命令 | P4 |
| P7 | UART 设计需求 + testbench | P5 |
| P8 | 端到端运行 + 验收 S1-S7 | P7 |
| P9 | 测试套件 | P8 |

---

## 成功标准（验收用）

| # | 标准 | 验证方式 |
|---|------|---------|
| S1 | `python -m eda_studio run uart` 从零产出 GDSII | `designs/uart/gds/*.gds` 存在 |
| S2 | 仿真失败时 LLM 修复 RTL，回环到 simulate | step_history 有 debug_fix → simulate |
| S3 | DRC 失败时 LLM 修复，回环到 pnr | step_history 有 drc_fix → pnr |
| S4 | 中断后 restore 能从断点继续 | 模拟 Ctrl+C 后 restore，current_step 正确 |
| S5 | 成本超限时流程停止 | 设 budget=0.01，state="failed" + usage 有值 |
| S6 | 危险 shell 命令被 rules 拦截 | 构造恶意 tool call，被 deny |
| S7 | 多 provider 配置生效 | usage()["by_model"] 有多个模型 |

---

## 开发环境

- **Python**: 3.9+（宿主机 3.9.6，容器内 3.12）
- **宿主机**: macOS arm64（Apple Silicon）
- **Docker**: Docker Desktop 29.5.2
- **venv**: 在项目根目录创建 `.venv`
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -e .
  ```
- **测试**: `pytest`，不依赖真实 EDA 工具和 LLM API（用 mock executor + mock agent）

---

## 不做的事

- 不修改 Senza 源码（本项目是纯消费者）
- **不去查看 runtime Rust 库的实现**（`../llm-harness-runtime/` 等）。只通过 `senza` Python 包的公开 API 和 `.pyi` type stubs 了解可用能力。如果遇到 runtime 功能不足以支撑开发，给 Senza 仓库提 issue：https://github.com/oh-my-harness/Senza/issues
- 不做 EDA 工具安装脚本（用 Docker 镜像）
- 不追求工业级 PPA 优化（教学项目）
- 不做 Web UI（纯 CLI + 文件产物）
- 不做 CI（依赖 Docker 容器和 LLM API）
- 不支持模拟电路设计
- 不做多工艺库切换（只用 Sky130）
