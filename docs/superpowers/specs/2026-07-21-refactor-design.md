# EDA Studio 代码重构设计

> 日期：2026-07-21
> 主题：仓库重构——结构整理 + 代码质量，让外部观众理解 eda-studio 做了什么以及和 Senza 的关系
> 范围：目录结构、死代码清理、executor 公共逻辑提取、workflow/restore 去重、README 重写、文档清理
> 不涉及：system_prompt 匹配逻辑（等 Senza #10 暴露 with_step_builder 后再改）、核心 workflow/judge 逻辑

---

## 1. 背景与目标

EDA Studio 一直由 AI 开发，缺少人工审核。仓库存在死代码、重复逻辑、过时文档、空目录等问题。同时作为 Senza SDK 的教学项目，需要让观众（SDK 用户 + EDA 关注者）清晰理解 eda-studio 做了什么、和 Senza 的关系。

### 目标

1. **结构整理**：删死代码、合并分散文件、清理 AI 过程产物
2. **代码质量**：提取 executor 公共逻辑、消除 workflow/restore 重复
3. **可读性**：README 重写讲清 Senza 关系、文档更新、代码自解释

### 不在范围内

- system_prompt 的 prompt_text 关键词匹配——等 Senza [issue #10](https://github.com/oh-my-harness/Senza/issues/10) 暴露 `with_step_builder` 后再改
- 核心 workflow/judge/executors 的领域逻辑——刚跑通 uart+i2c，不动
- 目录大重组（如 cli/core/executors/web 分层）——回归风险大

### 验证标准

- 75 个测试全绿
- 重构后重跑 uart 和 i2c 端到端流程，RTL→GDS 通过

---

## 2. 目录结构与死代码清理

### 删除

| 路径 | 原因 |
|------|------|
| `eda_studio/agents/` | 空目录（只有空 `__init__.py`），从未使用 |
| `eda_studio/budget.py` | 只被 test 引用，workflow 没挂 budget hook（Config 保留 budget 字段兼容 config.yaml） |
| `.superpowers/` | 37 个 AI 开发过程文件，对外部观众是噪音（加到 .gitignore） |
| `eda_studio.egg-info/` | 构建产物（加到 .gitignore） |

### 合并 CLI 三文件 → `cli.py`

当前 CLI 逻辑分散在三个文件：

| 文件 | 行数 | 职责 |
|------|------|------|
| `__main__.py` | 315 | cmd_run/restore/status/serve + main 入口 + _re_register + _print_event |
| `cli_commands.py` | 236 | cmd_init/check + 预检逻辑 |
| `main.py` | 84 | run_server（server 的薄封装） |

合并为 `eda_studio/cli.py`，`__main__.py` 只剩 `from .cli import main; main()`。

### 最终目录结构

```
eda_studio/
  __init__.py
  __main__.py          # 一行:from .cli import main; main()
  cli.py               # 所有 CLI 命令(原 __main__ + cli_commands + main)
  config.py
  design_config.py
  workflow.py
  judge.py
  hooks.py
  plugin.py
  prompts.py
  shell_safety.py
  state.py
  server.py
  executors/
    __init__.py
    base.py            # 新增:公共逻辑
    simulate.py
    synthesize.py
    pnr.py
    drc.py
    gds.py
    render.py
  templates/
tests/
static/
docs/
```

### .gitignore 追加

```
.superpowers/
eda_studio.egg-info/
```

---

## 3. Executor 公共逻辑提取

### 现状

6 个 executor（simulate/synthesize/pnr/drc/gds/render）都有相似样板：
- 从 `ctx["context"]` 取 design_dir/docker_config/shell_config
- `load_design_config(design_dir)`
- `run_shell(...)` + try/except TimeoutExpired/ShellSafetyError
- 返回 `{"output": ..., "structured": {"success": ...}}`

### 新增 `executors/base.py`

```python
from dataclasses import dataclass
from pathlib import Path
from ..shell_safety import run_shell, ShellSafetyError
from ..design_config import DesignConfig, load_design_config
from ..config import DockerConfig, ShellConfig
import subprocess

@dataclass
class ExecutorContext:
    """executor 公共上下文,从 workflow ctx 提取。"""
    design_dir: Path
    docker_config: DockerConfig
    shell_config: ShellConfig
    design_config: DesignConfig

def make_executor_context(ctx: dict) -> ExecutorContext:
    """从 workflow ctx 提取公共字段。"""
    ...

@dataclass
class EdaToolResult:
    """EDA 工具执行结果。"""
    success: bool
    output: str
    report_path: str | None = None

    def to_dict(self) -> dict:
        """转为 executor 返回格式。"""
        ...

def run_eda_tool(cmd: list, cwd: Path, ec: ExecutorContext,
                 timeout: int = 600) -> EdaToolResult:
    """执行 EDA 命令,统一处理 timeout/safety error。"""
    try:
        result = run_shell(cmd, cwd=cwd, docker_config=ec.docker_config,
                           shell_config=ec.shell_config)
        return EdaToolResult(success=True, output=...)
    except subprocess.TimeoutExpired:
        return EdaToolResult(success=False, output="timeout")
    except ShellSafetyError as e:
        return EdaToolResult(success=False, output=str(e))

注意：`run_eda_tool` 只覆盖单步命令执行。多步 executor（如 simulate 的
编译+运行两步）自行调用 `run_eda_tool` 多次组合。
```

### executor 简化后示例（simulate）

```python
def simulate_executor(ctx: dict) -> dict:
    ec = make_executor_context(ctx)
    rtl_files = [f for f in (ec.design_dir / "rtl").glob("*.v")
                 if f.name != f"{ec.design_config.tb_module}.v"]
    cmd = ["verilator", "--binary", "--timing", ...]
    result = run_eda_tool(cmd, ec.design_dir / "sim", ec)
    if not result.success:
        return result.to_dict()
    # 运行 sim_out + 解析 TEST PASSED/FAILED(领域逻辑)
    ...
```

### 不动的

每个 executor 的命令构造和结果解析逻辑（领域差异，不抽象）。

---

## 4. workflow 构建 vs restore 逻辑去重

### 现状

`workflow.py` 的 `build_workflow` 和 `__main__.py` 的 `_re_register` 有约 40 行重复——都注册 6 个 executor + FsToolsPlugin + hooks + context 变量。

### 提取公共注册逻辑

`workflow.py` 新增 `_register_engine`：

```python
def _register_engine(engine, config, design_name, rtl_ids):
    """注册 executor/plugin/hooks/context 变量(build_workflow 和 restore 共用)。"""
    fs_plugin = create_fs_tools_plugin()
    engine = (
        engine

        .with_executor("simulate", create_executor(simulate_executor))
        .with_executor("synthesize", create_executor(synthesize_executor))
        .with_executor("pnr", create_executor(pnr_executor))
        .with_executor("drc", create_executor(drc_executor))
        .with_executor("gds", create_executor(gds_executor))
        .with_executor("render", create_executor(render_executor))
        .with_executor("shell", create_shell_executor(["echo", "python3"]))
        .with_hooks(_wrap_hooks(make_hooks(config)))
        .with_task_store(f"designs/{design_name}/.taskstore")
        .with_max_tokens(16384)
        .with_thinking_level("high")
        .with_max_retries(config.workflow_config.max_fix_retries)
    )
    for sid in rtl_ids + ["debug_fix", "drc_fix"]:
        engine = engine.with_step_plugin(sid, fs_plugin)
    # MaxTokens auto-continue + provider 日志 + system_prompt
    engine = engine.with_hooks([
        create_should_stop_hook(make_max_tokens_continue_hook()),
        create_after_provider_response_hook(make_provider_response_logger()),
        create_before_run_hook(_make_system_prompt_cb()),
    ])
    # system_prompt 的 before_run hook 保持现有 prompt_text 匹配逻辑(等 Senza #10)
    from dataclasses import asdict
    engine.set_context_variable("design_dir", f"designs/{design_name}")
    engine.set_context_variable("docker_config", asdict(config.docker_config))
    engine.set_context_variable("shell_config", asdict(config.shell_config))
    return engine
```

`build_workflow` 和 `_re_register` 都调 `_register_engine`：

```python
def build_workflow(config, design_name) -> WorkflowEngine:
    # 构造 workflow_dict + provider + judge + env
    engine = WorkflowEngine(workflow_dict, provider, model, judge, env=env)
    return _register_engine(engine, config, design_name, rtl_ids)

# cli.py
def _re_register(engine, config, design_name, rtl_ids):
    return _register_engine(engine, config, design_name, rtl_ids)
```

---

## 5. README 重写与 Senza 关系

### 定位

README 同时服务两类观众：
- **Senza SDK 用户**：看"这个 SDK 能做什么、怎么用"
- **EDA 关注者**：看"LLM 能不能自动化芯片设计"

重点讲清 eda-studio 和 Senza 的关系。**不提 runtime**（runtime 不开源）。

### 结构

1. **一句话定位**：EDA Studio 是基于 Senza SDK 的开源 EDA 自动化设计示例——用 LLM 驱动开源 EDA 工具完成 RTL→GDS 全流程，同时作为 Senza SDK 的教学项目。

2. **什么是 Senza**（2-3 句）：Senza 是 LLM agent + workflow 编排的 Python SDK，提供 Agent 层（单轮对话+工具调用）和 Workflow 层（多步工作流+条件路由+崩溃恢复）。EDA Studio 展示如何用 Workflow 层构建真实的复杂流程。

3. **EDA Studio 做了什么**（给 EDA 关注者）：流程图 + GDS PNG 截图。两个示例 design（uart/i2c），LLM 自动生成 RTL → 仿真失败自动修复 → 最终产出 GDSII。

4. **Senza 能力对照表**：eda-studio 用了 Senza 的哪些 API，验证了什么能力。

5. **快速开始**（保留现有，更新过时部分）

6. **架构**（精简，指向代码和 docs/）

### Senza 能力对照表

| Senza API | eda-studio 中的用途 | 验证的能力 |
|-----------|-------------------|-----------|
| `WorkflowEngine` | 编排 11 步 EDA 流程 | 多步工作流 |
| `with_executor` | 调用 verilator/yosys/OpenROAD | executor step |
| `create_judge` | 仿真失败→debug_fix 回环 | 条件路由 |
| `with_step_plugin` + `create_fs_tools_plugin` | LLM 读写 RTL/报告 | 内置工具 |
| `with_hooks` + `create_should_stop_hook` | MaxTokens auto-continue | hooks |
| `with_task_store` + `restore` | 断点恢复 | 崩溃恢复 |
| `with_max_tokens` / `with_thinking_level` | glm-5.2 thinking 配置 | LLM 参数 |

---

## 6. 文档清理与代码自解释

### 文档清理

| 文件 | 处理 |
|------|------|
| `docs/eda-studio-design.md`（1236 行） | 更新过时部分（删"空响应纠正"、更新 max_tokens/thinking_level、工具改为 FsToolsPlugin） |
| `docs/superpowers/plans/` 和 `specs/` | AI 开发过程产物，移到 `.superpowers/` 或删除 |
| `CLAUDE.md` | 更新版本号、删 nudge/rules 引用、更新架构描述 |
| `CONTRIBUTING.md` | 不动 |

### 代码自解释

每个模块顶部一行 docstring 说明职责：

- `workflow.py` — "组装 WorkflowEngine：steps/edges/executors/tools/hooks"
- `judge.py` — "step 路由决策：仿真失败→debug_fix，DRC 失败→drc_fix"
- `hooks.py` — "日志审计 + MaxTokens auto-continue"
- `executors/base.py` — "executor 公共逻辑：ctx 提取 + EDA 命令执行"
- 每个 executor — "verilator 仿真"/"yosys 综合" 等

---

## 7. 未覆盖项（等上游）

### system_prompt 显式传递

当前用 `before_run` hook 的 `prompt_text` 关键词匹配判断 step 类型。等 Senza [issue #10](https://github.com/oh-my-harness/Senza/issues/10) 暴露 `with_step_builder` 后，改为：

```python
engine.with_step_builder("rtl_tx", lambda b: b.system_prompt(RTL_SYSTEM))
```

本次重构不碰这部分。

### senza-sdk 升级到 v0.4.7

v0.4.7（session viewer + markdown/raw toggle）尚未发布到 PyPI。发布后升级 `pyproject.toml` 版本约束。
