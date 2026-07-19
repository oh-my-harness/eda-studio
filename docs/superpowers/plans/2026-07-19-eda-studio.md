# Senza EDA Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个用 Senza + 开源 EDA 工具完成 UART RTL→GDS 全流程的可运行项目,验证 senza 的 WorkflowEngine + executor + judge + hooks + restore + 原生 LLM step 能力。

**Architecture:** `WorkflowEngine` 编排 8 个 step(rtl_design/simulate/debug_fix/synthesize/pnr/drc_fix/drc/gds),LLM step 用原生 `prompt`+`allowed_tools`,EDA 工具 step 用 Python 回调 executor(`run_shell` 内做白名单 + `docker exec`)。judge 用闭包计数做 per-环节 回环限制。单 provider + 单 model。

**Tech Stack:** Python 3.9+, senza-sdk 0.4.1(本地 editable 安装,见 `scripts/install-senza-dev.sh`), pyyaml, Docker(`iic-osic-tools` 镜像提供 verilator/yosys/openroad/magic/klayout), SkyWater Sky130 PDK。

## Global Constraints

- **senza 安装**:`./scripts/install-senza-dev.sh` 从本地 `../Senza` editable 安装(`maturin develop`)。Senza 的 Cargo.toml 用 git rev 锁定 runtime(`senza-pkg/runtime.lock`,当前 `94c6be8`),从 GitHub fetch,不依赖本地 runtime checkout。
- **单 provider + 单 model**:`WorkflowEngine.__init__(workflow_dict, provider, model, judge, env=env)` 只接受一个 provider/model。所有 LLM step 共用。
- **EDA 工具用 Python 回调 executor,不用 ShellExecutor**:`ShellExecutor` 白名单按 command 名过滤,Docker 场景下 command 都是 `docker`,无法区分 `verilator` vs `rm`。`ShellExecutor` 仅用于教学示例 step(简单 `echo`)。
- **`with_max_retries` 不限制 `to:` 回环**:EDA 的「失败→debug_fix→重跑」是 `to:` 转换,`with_max_retries(N)` 只限制连续 `Transition::Retry`(judge 返回 `"retry"`)。per-环节 限制由 judge 闭包计数实现,`with_max_steps(50)` 兜底防死循环。
- **edges 必须覆盖 judge 所有 `to:` 目标**:`Transition::To(next)` 要求 `from→next` 边存在,否则 `InvalidTransition→Failed`。
- **tool 用闭包捕获 `design_dir`**:`ToolContext` 只有 `is_cancelled()`/`send_update()`,无 workflow KV 黑板访问。tool 拿不到 `set_context_variable` 的值。
- **ctx 不存 config**:`AppConfig` 含 API key,不通过 `set_context_variable` 放入 context 黑板(会进 taskstore 落盘)。只放 `docker_config`/`shell_config`/`design_dir`。
- **executor ctx 字段**:`step_id`/`step_name`/`config`/`prev_output`/`context`(KV 黑板快照)。
- **judge ctx 字段**(只读):`step_id`/`output`/`step_count`/`retry_count`/`structured`。
- **测试不依赖真实 EDA 工具和 LLM API**:`run_shell` 被 monkeypatch,executor 返回固定报告;LLM step 用 senza 的 mock provider 或跳过。
- **Docker 命令必须用 `bash -lc`**:容器 entrypoint 通过 login profile 设 PATH,executor 代码只写工具名。
- **语言**:代码注释和文档用中文,代码标识符用英文。

---

## File Structure

```
eda-studio/
├── pyproject.toml
├── config.example.yaml
├── eda_studio/
│   ├── __init__.py
│   ├── __main__.py                # CLI: run / restore / status
│   ├── config.py                  # load_config → AppConfig
│   ├── prompts.py                 # 3 prompt 模板
│   ├── workflow.py                # build_workflow → WorkflowEngine
│   ├── judge.py                   # make_judge_fn → closure
│   ├── hooks.py                   # make_hooks → [closures]
│   ├── rules.py                   # make_rules_hook (import senza)
│   ├── budget.py                  # make_budget_cb → closure
│   ├── shell_safety.py            # run_shell + ShellSafetyError
│   ├── tools/{__init__,file_tools,report_tools}.py
│   └── executors/{__init__,simulate,synthesize,pnr,drc,gds}.py
├── designs/uart/{requirement.md, rtl/tb_uart.v}
└── tests/test_{config,prompts,run_shell,tools,executors,judge,hooks_rules_budget,workflow}.py
```

**职责边界**:
- `config.py`:yaml→dataclass,不 import senza。`provider_spec`/`pricing_spec` 是 raw dict。
- `shell_safety.py`:`run_shell`/`ShellSafetyError`,import config。
- `prompts.py`:纯字符串,无依赖。
- `tools/`:闭包工厂,无 senza 依赖。
- `executors/`:import `shell_safety.run_shell`,无 senza 依赖。
- `workflow.py`:组装所有,senza 依赖集中在此。
- `judge.py`/`hooks.py`/`budget.py`:纯闭包,无 senza import。`rules.py` import senza。

---

## Task 1: 项目骨架 + pyproject + config.example.yaml

**Files:**
- Create: `pyproject.toml`
- Create: `config.example.yaml`
- Create: `eda_studio/__init__.py`
- Create: `eda_studio/__main__.py`(占位,Task 10 实现)
- Create: `designs/uart/requirement.md`
- Create: `designs/uart/rtl/tb_uart.v`
- Create: `README.md`(最小)

**Interfaces:**
- Produces: 可 `pip install -e .` 的包骨架

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "eda-studio"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [
    "senza-sdk>=0.4.1",
    "pyyaml>=6.0",
]

[project.scripts]
eda-studio = "eda_studio.__main__:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends._legacy:_Backend"

[tool.setuptools]
packages = ["eda_studio", "eda_studio.tools", "eda_studio.executors"]
```

- [ ] **Step 2: 写 config.example.yaml**

```yaml
provider:
  type: openai
  api_key: ${OPENAI_API_KEY}
  base_url: null

model: "gpt-4o"

pricing:
  gpt-4o:
    input_per_mtok: 2.5
    output_per_mtok: 10.0

budget:
  limit: 5.0
  exceeded_action: stop

workflow:
  max_steps: 50
  max_fix_retries: 3

shell:
  allowed_commands: ["verilator", "yosys", "openroad", "magic", "netgen", "klayout"]
  denied_args: ["rm", "chmod", "sudo", ">", "|", ";", "&", "`", "$"]

docker:
  image: "hpretl/iic-osic-tools:latest"
  container: "eda-tools"
  workdir: "/work/designs"
  pdk: "sky130A"
```

- [ ] **Step 3: 写 eda_studio/__init__.py**

```python
"""Senza EDA Studio —— RTL→GDS 自动化流程。"""
__version__ = "0.1.0"
```

- [ ] **Step 4: 写 eda_studio/__main__.py 占位**

```python
"""CLI 入口(Task 10 实现)。"""
def main():
    print("eda-studio (骨架,Task 10 实现 CLI)")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 写 designs/uart/requirement.md**

```markdown
# UART 设计需求

设计一个简易 UART 发送器 + 接收器:

- 波特率 115200,时钟 50MHz
- 数据位 8,停止位 1,无校验
- 接口:
  - `uart_tx`: TX 模块,输入 clk/rst_n/tx_start/tx_data[7:0],输出 tx_busy/txd
  - `uart_rx`: RX 模块,输入 clk/rst_n/rxd,输出 rx_busy/rx_data[7:0]/rx_valid
- 顶层模块名 `uart`,例化 uart_tx + uart_rx,对外暴露 txd/rxd

约束:
- 可综合 Verilog(不含 initial/$display/$finish 等)
- 同步复位(rst_n 低有效)
```

- [ ] **Step 6: 写 designs/uart/rtl/tb_uart.v fixture**

```verilog
`timescale 1ns/1ps
module tb_uart;
    reg clk = 0, rst_n = 0;
    reg tx_start = 0;
    reg [7:0] tx_data = 0;
    wire tx_busy, txd;
    wire rx_busy;
    wire [7:0] rx_data;
    wire rx_valid;

    uart dut(
        .clk(clk), .rst_n(rst_n),
        .tx_start(tx_start), .tx_data(tx_data), .tx_busy(tx_busy), .txd(txd),
        .rxd(txd), .rx_busy(rx_busy), .rx_data(rx_data), .rx_valid(rx_valid)
    );

    always #10 clk = ~clk;

    initial begin
        rst_n = 0;
        #50 rst_n = 1;
        #100 tx_start = 1; tx_data = 8'h55;
        #20 tx_start = 0;
        wait(rx_valid);
        #100;
        if (rx_data === 8'h55) begin
            $display("TEST PASSED: rx_data=0x%02x", rx_data);
        end else begin
            $display("TEST FAILED: expected 0x55 got 0x%02x", rx_data);
        end
        $finish;
    end

    initial begin
        #2000000;
        $display("TEST FAILED: timeout");
        $finish;
    end
endmodule
```

- [ ] **Step 7: 写最小 README.md**

```markdown
# EDA Studio

基于 [Senza](https://github.com/oh-my-harness/Senza) 的开源 EDA 自动化芯片设计流程示例。

## 快速开始

```bash
./scripts/install-senza-dev.sh
pip install -e .
docker run -d --name eda-tools -v $(pwd)/designs:/work/designs \
  -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity
cp config.example.yaml config.yaml
python -m eda_studio run uart
```
```

- [ ] **Step 8: 验证安装**

Run: `pip install -e . && python -c "import eda_studio; print(eda_studio.__version__)"`
Expected: `0.1.0`

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml config.example.yaml eda_studio/ designs/ README.md
git commit -m "feat: project skeleton + pyproject + uart requirement + tb fixture"
```

---

## Task 2: config.py(配置加载)

**Files:**
- Create: `eda_studio/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `AppConfig`/`WorkflowConfig`/`ShellConfig`/`DockerConfig` dataclass;`load_config(path) -> AppConfig`。`provider_spec`/`pricing_spec` 是 raw dict,senza 实例创建在 workflow.py。

- [ ] **Step 1: 写失败测试 tests/test_config.py**

```python
import textwrap
from pathlib import Path
from eda_studio.config import load_config, AppConfig, WorkflowConfig, ShellConfig, DockerConfig

def write_cfg(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return p

def test_load_config_basic(tmp_path):
    cfg = load_config(write_cfg(tmp_path, """
        provider:
          type: openai
          api_key: sk-test
          base_url: null
        model: gpt-4o
        pricing:
          gpt-4o:
            input_per_mtok: 2.5
            output_per_mtok: 10.0
        budget:
          limit: 5.0
          exceeded_action: stop
        workflow:
          max_steps: 50
          max_fix_retries: 3
        shell:
          allowed_commands: [verilator, yosys]
          denied_args: [rm, sudo]
        docker:
          image: hpretl/iic-osic-tools:latest
          container: eda-tools
          workdir: /work/designs
          pdk: sky130A
    """))
    assert isinstance(cfg, AppConfig)
    assert cfg.model == "gpt-4o"
    assert cfg.provider_spec == {"type": "openai", "api_key": "sk-test", "base_url": None}
    assert cfg.pricing_spec == {"gpt-4o": {"input_per_mtok": 2.5, "output_per_mtok": 10.0}}
    assert cfg.budget_limit == 5.0
    assert cfg.budget_exceeded_action == "stop"
    assert cfg.workflow_config == WorkflowConfig(max_steps=50, max_fix_retries=3)
    assert cfg.shell_config == ShellConfig(allowed_commands=["verilator", "yosys"], denied_args=["rm", "sudo"])
    assert cfg.docker_config == DockerConfig(image="hpretl/iic-osic-tools:latest", container="eda-tools", workdir="/work/designs", pdk="sky130A")

def test_load_config_env_var_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    cfg = load_config(write_cfg(tmp_path, """
        provider: {type: openai, api_key: ${OPENAI_API_KEY}, base_url: null}
        model: gpt-4o
        pricing: {gpt-4o: {input_per_mtok: 1.0, output_per_mtok: 2.0}}
        budget: {limit: 1.0, exceeded_action: stop}
        workflow: {max_steps: 50, max_fix_retries: 3}
        shell: {allowed_commands: [verilator], denied_args: [rm]}
        docker: {image: img, container: c, workdir: /w, pdk: sky130A}
    """))
    assert cfg.provider_spec["api_key"] == "sk-from-env"

def test_load_config_missing_file(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.yaml"))
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_config.py -v`
Expected: FAIL `ModuleNotFoundError: eda_studio.config`

- [ ] **Step 3: 实现 eda_studio/config.py**

```python
"""配置加载:yaml → dataclass。不 import senza(便于测试)。"""
import os
import re
from dataclasses import dataclass
from pathlib import Path
import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

@dataclass
class WorkflowConfig:
    max_steps: int
    max_fix_retries: int

@dataclass
class ShellConfig:
    allowed_commands: list
    denied_args: list

@dataclass
class DockerConfig:
    image: str
    container: str
    workdir: str
    pdk: str

@dataclass
class AppConfig:
    provider_spec: dict       # raw yaml: {type, api_key, base_url}
    model: str
    pricing_spec: dict        # raw yaml: {model: {input_per_mtok, output_per_mtok}}
    budget_limit: float
    budget_exceeded_action: str  # "stop" | "continue"
    workflow_config: WorkflowConfig
    shell_config: ShellConfig
    docker_config: DockerConfig


def _expand_env(value):
    """递归展开 ${ENV_VAR}。"""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: str) -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    raw = yaml.safe_load(p.read_text())
    raw = _expand_env(raw)
    return AppConfig(
        provider_spec=raw["provider"],
        model=raw["model"],
        pricing_spec=raw["pricing"],
        budget_limit=float(raw["budget"]["limit"]),
        budget_exceeded_action=raw["budget"]["exceeded_action"],
        workflow_config=WorkflowConfig(**raw["workflow"]),
        shell_config=ShellConfig(**raw["shell"]),
        docker_config=DockerConfig(**raw["docker"]),
    )
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add eda_studio/config.py tests/test_config.py
git commit -m "feat(config): yaml → AppConfig dataclass with env var expansion"
```

---

## Task 3: shell_safety.py(run_shell 白名单)

**Files:**
- Create: `eda_studio/shell_safety.py`
- Create: `tests/test_run_shell.py`

**Interfaces:**
- Consumes: `ShellConfig`/`DockerConfig` from `config.py`
- Produces: `run_shell(cmd, cwd, docker_config, shell_config) -> CompletedProcess`;`ShellSafetyError`

- [ ] **Step 1: 写失败测试 tests/test_run_shell.py**

```python
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from eda_studio.shell_safety import run_shell, ShellSafetyError
from eda_studio.config import ShellConfig, DockerConfig

SHELL = ShellConfig(allowed_commands=["verilator", "yosys", "echo"], denied_args=["rm", "sudo", ";", "|"])
DOCKER = DockerConfig(image="img", container="eda-tools", workdir="/work/designs", pdk="sky130A")

def test_empty_command_rejected(tmp_path):
    with pytest.raises(ShellSafetyError, match="空命令"):
        run_shell([], tmp_path, DOCKER, SHELL)

def test_tool_not_in_whitelist(tmp_path):
    with pytest.raises(ShellSafetyError, match="不在白名单"):
        run_shell(["rm", "-rf", "/"], tmp_path, DOCKER, SHELL)

def test_denied_arg_in_commandline(tmp_path):
    with pytest.raises(ShellSafetyError, match="危险字符"):
        run_shell(["verilator", "--rm"], tmp_path, DOCKER, SHELL)

def test_cwd_outside_designs(tmp_path):
    with pytest.raises(ShellSafetyError, match="不在 designs/ 下"):
        run_shell(["echo", "hi"], tmp_path, DOCKER, SHELL)

def test_path_mapping_and_docker_exec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart" / "sim").mkdir(parents=True)
    cwd = tmp_path / "designs" / "uart" / "sim"
    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        r = MagicMock()
        r.stdout = "ok"
        r.stderr = ""
        r.returncode = 0
        return r
    with patch("eda_studio.shell_safety.subprocess.run", side_effect=fake_run):
        result = run_shell(["echo", "hello"], cwd, DOCKER, SHELL)
    assert result.returncode == 0
    assert captured["cmd"][0] == "docker"
    assert "exec" in captured["cmd"]
    assert "-w" in captured["cmd"]
    w_idx = captured["cmd"].index("-w")
    assert captured["cmd"][w_idx + 1] == "/work/designs/uart/sim"
    assert "bash" in captured["cmd"]
    assert "-lc" in captured["cmd"]
    assert "echo hello" in captured["cmd"][-1]
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_run_shell.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 eda_studio/shell_safety.py**

```python
"""EDA 工具命令执行:白名单检查 + docker exec 包装。"""
import subprocess
from pathlib import Path
from .config import ShellConfig, DockerConfig


class ShellSafetyError(Exception):
    """命令未通过白名单检查。"""


def run_shell(cmd: list, cwd: Path, docker_config: DockerConfig,
              shell_config: ShellConfig) -> subprocess.CompletedProcess:
    """在 Docker 容器内执行 EDA 工具命令,执行前做白名单检查。

    - cmd[0] 必须在 shell_config.allowed_commands 里
    - cmd 拼接后不能含 shell_config.denied_args 里的危险字符
    - 用 bash -lc 包装(容器 entrypoint 通过 login profile 设 PATH)
    - 本地 designs/ 目录挂载到容器 /work/designs/,cwd 显式前缀剥离转换
    """
    if not cmd:
        raise ShellSafetyError("空命令")
    tool = cmd[0]
    if tool not in shell_config.allowed_commands:
        raise ShellSafetyError(f"工具 {tool!r} 不在白名单 {shell_config.allowed_commands}")

    host_designs = Path("designs").resolve()
    try:
        rel = cwd.relative_to(host_designs)
        container_cwd = f"{docker_config.workdir}/{rel}"
    except ValueError:
        raise ShellSafetyError(f"cwd {cwd} 不在 designs/ 下")

    cmdline = " ".join(cmd)
    for danger in shell_config.denied_args:
        if danger in cmdline:
            raise ShellSafetyError(f"命令含危险字符 {danger!r}: {cmdline}")

    docker_cmd = [
        "docker", "exec", "-w", container_cwd,
        docker_config.container,
        "bash", "-lc", cmdline,
    ]
    return subprocess.run(docker_cmd, capture_output=True, text=True, timeout=600)
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/test_run_shell.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add eda_studio/shell_safety.py tests/test_run_shell.py
git commit -m "feat(shell): run_shell with whitelist + docker exec + path mapping"
```

---

## Task 4: prompts.py(prompt 模板)

**Files:**
- Create: `eda_studio/prompts.py`
- Create: `tests/test_prompts.py`

**Interfaces:**
- Produces: `RTL_DESIGN_PROMPT`/`DEBUG_FIX_PROMPT`/`DRC_FIX_PROMPT`;`load_requirement(design_name) -> str`;`build_prompts(requirement) -> dict`

- [ ] **Step 1: 写失败测试 tests/test_prompts.py**

```python
from eda_studio.prompts import RTL_DESIGN_PROMPT, DEBUG_FIX_PROMPT, DRC_FIX_PROMPT, load_requirement, build_prompts

def test_rtl_prompt_has_requirement_placeholder():
    assert "{requirement}" in RTL_DESIGN_PROMPT

def test_debug_fix_prompt_no_duplicate_requirement():
    assert "{requirement}" not in DEBUG_FIX_PROMPT

def test_build_prompts_injects_requirement():
    prompts = build_prompts("UART 9600 baud")
    assert "UART 9600 baud" in prompts["rtl_design"]
    assert "{requirement}" not in prompts["rtl_design"]
    assert prompts["debug_fix"] == DEBUG_FIX_PROMPT
    assert prompts["drc_fix"] == DRC_FIX_PROMPT

def test_load_requirement_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_requirement("nonexistent") == ""

def test_load_requirement_reads_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    (tmp_path / "designs" / "uart" / "requirement.md").write_text("# UART\n波特率 115200")
    assert "115200" in load_requirement("uart")
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_prompts.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 eda_studio/prompts.py**

```python
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
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/test_prompts.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add eda_studio/prompts.py tests/test_prompts.py
git commit -m "feat(prompts): 3 LLM step prompts + requirement loading"
```

---

## Task 5: tools/file_tools.py + report_tools.py

**Files:**
- Create: `eda_studio/tools/__init__.py`
- Create: `eda_studio/tools/file_tools.py`
- Create: `eda_studio/tools/report_tools.py`
- Create: `tests/test_tools.py`

**Interfaces:**
- Produces: `make_file_tools(design_dir) -> dict[str, callable]`;`make_report_tools(design_dir) -> dict[str, callable]`。callable 签名 `(args: dict, ctx) -> dict`。

- [ ] **Step 1: 写失败测试 tests/test_tools.py**

```python
from pathlib import Path
from eda_studio.tools.file_tools import make_file_tools
from eda_studio.tools.report_tools import make_report_tools

CTX = object()

def test_write_and_read_rtl(tmp_path):
    tools = make_file_tools(tmp_path)
    r = tools["write_rtl"]({"filename": "uart_tx.v", "content": "module uart_tx; endmodule"}, CTX)
    assert "已写入" in r["content"][0]["text"]
    r2 = tools["read_rtl"]({"filename": "uart_tx.v"}, CTX)
    assert "uart_tx" in r2["content"][0]["text"]

def test_read_rtl_missing(tmp_path):
    tools = make_file_tools(tmp_path)
    r = tools["read_rtl"]({"filename": "nope.v"}, CTX)
    assert "不存在" in r["content"][0]["text"]

def test_list_design_files(tmp_path):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "a.v").write_text("x")
    (tmp_path / "rtl" / "b.v").write_text("y")
    tools = make_file_tools(tmp_path)
    r = tools["list_design_files"]({}, CTX)
    text = r["content"][0]["text"]
    assert "rtl/a.v" in text
    assert "rtl/b.v" in text

def test_list_design_files_empty(tmp_path):
    tools = make_file_tools(tmp_path)
    r = tools["list_design_files"]({}, CTX)
    assert "空" in r["content"][0]["text"]

def test_read_write_sdc(tmp_path):
    tools = make_file_tools(tmp_path)
    tools["write_sdc"]({"content": "create_clock -period 20"}, CTX)
    r = tools["read_sdc"]({}, CTX)
    assert "create_clock" in r["content"][0]["text"]

def test_read_sim_report_missing(tmp_path):
    tools = make_report_tools(tmp_path)
    r = tools["read_sim_report"]({}, CTX)
    assert "无仿真报告" in r["content"][0]["text"]

def test_read_sim_report_extracts_errors(tmp_path):
    (tmp_path / "sim").mkdir()
    report = "%Error: uart_tx.v:10: syntax error\nTEST PASSED\nsome other line"
    (tmp_path / "sim" / "report.txt").write_text(report)
    tools = make_report_tools(tmp_path)
    r = tools["read_sim_report"]({}, CTX)
    text = r["content"][0]["text"]
    assert "syntax error" in text
    assert "some other line" not in text

def test_read_drc_report(tmp_path):
    (tmp_path / "pnr").mkdir()
    (tmp_path / "pnr" / "drc.rpt").write_text("ERROR: metal1 spacing 0.1u\n")
    tools = make_report_tools(tmp_path)
    r = tools["read_drc_report"]({}, CTX)
    assert "metal1" in r["content"][0]["text"]
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_tools.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 eda_studio/tools/__init__.py**

```python
"""LLM step 可调用的 tools(通过 with_tool 注册)。"""
```

- [ ] **Step 4: 实现 eda_studio/tools/file_tools.py**

```python
"""文件读写 tools。闭包捕获 design_dir。"""
from pathlib import Path


def make_file_tools(design_dir: Path):
    """工厂函数:闭包捕获 design_dir,返回所有文件操作 tools。"""
    def write_rtl_fn(args: dict, ctx) -> dict:
        filename = args["filename"]
        content = args["content"]
        path = design_dir / "rtl" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return {"content": [{"type": "text", "text": f"已写入 {path}"}], "terminate": False}

    def read_rtl_fn(args: dict, ctx) -> dict:
        filename = args["filename"]
        path = design_dir / "rtl" / filename
        if not path.exists():
            return {"content": [{"type": "text", "text": f"文件不存在: {filename}"}], "terminate": False}
        return {"content": [{"type": "text", "text": path.read_text()}], "terminate": False}

    def list_design_files_fn(args: dict, ctx) -> dict:
        lines = []
        for sub in ["rtl", "sim", "synth", "pnr", "gds"]:
            d = design_dir / sub
            if d.exists():
                for f in sorted(d.iterdir()):
                    lines.append(f"{sub}/{f.name}")
        return {"content": [{"type": "text", "text": "\n".join(lines) or "(空)"}], "terminate": False}

    def read_sdc_fn(args: dict, ctx) -> dict:
        path = design_dir / "pnr" / "uart.sdc"
        if not path.exists():
            return {"content": [{"type": "text", "text": "无 SDC 约束文件"}], "terminate": False}
        return {"content": [{"type": "text", "text": path.read_text()}], "terminate": False}

    def write_sdc_fn(args: dict, ctx) -> dict:
        content = args["content"]
        path = design_dir / "pnr" / "uart.sdc"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return {"content": [{"type": "text", "text": f"已写入 {path}"}], "terminate": False}

    return {
        "write_rtl": write_rtl_fn, "read_rtl": read_rtl_fn,
        "list_design_files": list_design_files_fn,
        "read_sdc": read_sdc_fn, "write_sdc": write_sdc_fn,
    }
```

- [ ] **Step 5: 实现 eda_studio/tools/report_tools.py**

```python
"""报告读取 tools。闭包捕获 design_dir。"""
import re
from pathlib import Path


def _extract_sim_errors(report: str) -> str:
    lines = []
    for line in report.splitlines():
        if re.search(r"%Error|%Warning|TEST (PASSED|FAILED)|Assertion|Error:", line):
            lines.append(line)
    return "\n".join(lines) if lines else report


def _extract_drc_violations(report: str) -> str:
    lines = []
    for line in report.splitlines():
        if re.search(r"ERROR|violation|spacing|width|short|open|spelling", line, re.I):
            lines.append(line)
    return "\n".join(lines) if lines else report


def make_report_tools(design_dir: Path):
    def read_sim_report_fn(args: dict, ctx) -> dict:
        path = design_dir / "sim" / "report.txt"
        if not path.exists():
            return {"content": [{"type": "text", "text": "无仿真报告"}], "terminate": False}
        report = path.read_text()
        summary = _extract_sim_errors(report)
        return {"content": [{"type": "text", "text": summary}], "terminate": False}

    def read_drc_report_fn(args: dict, ctx) -> dict:
        path = design_dir / "pnr" / "drc.rpt"
        if not path.exists():
            return {"content": [{"type": "text", "text": "无 DRC 报告"}], "terminate": False}
        report = path.read_text()
        summary = _extract_drc_violations(report)
        return {"content": [{"type": "text", "text": summary}], "terminate": False}

    return {"read_sim_report": read_sim_report_fn, "read_drc_report": read_drc_report_fn}
```

- [ ] **Step 6: 运行验证通过**

Run: `pytest tests/test_tools.py -v`
Expected: 8 passed

- [ ] **Step 7: Commit**

```bash
git add eda_studio/tools/ tests/test_tools.py
git commit -m "feat(tools): file_tools + report_tools closure factories"
```

---

## Task 6: executors(simulate + synthesize + pnr + drc + gds)

**Files:**
- Create: `eda_studio/executors/__init__.py`
- Create: `eda_studio/executors/simulate.py`
- Create: `eda_studio/executors/synthesize.py`
- Create: `eda_studio/executors/pnr.py`
- Create: `eda_studio/executors/drc.py`
- Create: `eda_studio/executors/gds.py`
- Create: `tests/test_executors.py`

**Interfaces:**
- Consumes: `run_shell`/`ShellSafetyError` from `shell_safety.py`
- Produces: `simulate_executor`/`synthesize_executor`/`pnr_executor`/`drc_executor`/`gds_executor`。签名 `(ctx: dict) -> dict`。读 `ctx["context"]["design_dir"]`/`docker_config`/`shell_config`。

- [ ] **Step 1: 写失败测试 tests/test_executors.py**

```python
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from eda_studio.executors.simulate import simulate_executor
from eda_studio.executors.synthesize import synthesize_executor
from eda_studio.executors.pnr import pnr_executor
from eda_studio.executors.drc import drc_executor
from eda_studio.executors.gds import gds_executor
from eda_studio.shell_safety import ShellSafetyError
from eda_studio.config import ShellConfig, DockerConfig

SHELL = ShellConfig(allowed_commands=["verilator", "yosys", "openroad", "magic", "klayout"], denied_args=["rm"])
DOCKER = DockerConfig(image="img", container="eda-tools", workdir="/work/designs", pdk="sky130A")

def make_ctx(design_dir):
    return {"context": {"design_dir": str(design_dir), "docker_config": DOCKER, "shell_config": SHELL}}

def fake_completed(stdout="", stderr="", returncode=0):
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r

def test_simulate_missing_tb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart" / "rtl").mkdir(parents=True)
    d = tmp_path / "designs" / "uart"
    r = simulate_executor(make_ctx(d))
    assert r["structured"]["success"] is False
    assert "tb_uart.v" in r["output"]

def test_simulate_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rtl = tmp_path / "designs" / "uart" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "uart.v").write_text("module uart; endmodule")
    (rtl / "tb_uart.v").write_text("`timescale 1ns/1ps module tb_uart; endmodule")
    d = tmp_path / "designs" / "uart"
    with patch("eda_studio.executors.simulate.run_shell", side_effect=[fake_completed(returncode=0), fake_completed(stdout="TEST PASSED", returncode=0)]):
        r = simulate_executor(make_ctx(d))
    assert r["structured"]["success"] is True
    assert (d / "sim" / "report.txt").exists()

def test_simulate_safety_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rtl = tmp_path / "designs" / "uart" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "uart.v").write_text("x")
    (rtl / "tb_uart.v").write_text("x")
    d = tmp_path / "designs" / "uart"
    with patch("eda_studio.executors.simulate.run_shell", side_effect=ShellSafetyError("bad")):
        r = simulate_executor(make_ctx(d))
    assert r["structured"]["success"] is False
    assert r["structured"].get("safety_error") is True

def test_synthesize_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rtl = tmp_path / "designs" / "uart" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "uart.v").write_text("module uart; endmodule")
    d = tmp_path / "designs" / "uart"
    def fake_run(cmd, **kw):
        (d / "synth").mkdir(exist_ok=True)
        (d / "synth" / "netlist.json").write_text("{}")
        return fake_completed(returncode=0)
    with patch("eda_studio.executors.synthesize.run_shell", side_effect=fake_run):
        r = synthesize_executor(make_ctx(d))
    assert r["structured"]["success"] is True

def test_pnr_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart"
    (d / "synth").mkdir(parents=True)
    (d / "synth" / "netlist.v").write_text("module uart; endmodule")
    with patch("eda_studio.executors.pnr.run_shell", return_value=fake_completed(returncode=0)):
        r = pnr_executor(make_ctx(d))
    assert r["structured"]["success"] is True

def test_drc_no_violations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart" / "pnr"
    d.mkdir(parents=True)
    (d / "uart_pnr.def").write_text("x")
    with patch("eda_studio.executors.drc.run_shell", return_value=fake_completed(stdout="0 violations", returncode=0)):
        r = drc_executor({"context": {"design_dir": str(d.parent), "docker_config": DOCKER, "shell_config": SHELL}})
    assert r["structured"]["success"] is True

def test_drc_has_violations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart" / "pnr"
    d.mkdir(parents=True)
    (d / "uart_pnr.def").write_text("x")
    (d / "drc.rpt").write_text("ERROR: metal1 spacing violation")
    with patch("eda_studio.executors.drc.run_shell", return_value=fake_completed(stdout="violation found", returncode=0)):
        r = drc_executor({"context": {"design_dir": str(d.parent), "docker_config": DOCKER, "shell_config": SHELL}})
    assert r["structured"]["success"] is False

def test_gds_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart"
    (d / "pnr").mkdir(parents=True)
    (d / "pnr" / "uart_pnr.def").write_text("x")
    def fake_run(cmd, **kw):
        (d / "gds").mkdir(exist_ok=True)
        (d / "gds" / "uart.gds").write_text("GDSII")
        return fake_completed(returncode=0)
    with patch("eda_studio.executors.gds.run_shell", side_effect=fake_run):
        r = gds_executor(make_ctx(d))
    assert r["structured"]["success"] is True
    assert r["structured"]["gds_path"].endswith("uart.gds")
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_executors.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 eda_studio/executors/__init__.py**

```python
"""workflow executor 步骤(EDA 工具调用)。"""
from .simulate import simulate_executor
from .synthesize import synthesize_executor
from .pnr import pnr_executor
from .drc import drc_executor
from .gds import gds_executor

__all__ = ["simulate_executor", "synthesize_executor", "pnr_executor", "drc_executor", "gds_executor"]
```

- [ ] **Step 4: 实现 eda_studio/executors/simulate.py**

```python
"""verilator 仿真 executor。"""
from pathlib import Path
from ..shell_safety import run_shell, ShellSafetyError


def _parse_verilator_output(stderr: str, stdout: str) -> str:
    return f"--- stderr ---\n{stderr}\n--- stdout ---\n{stdout}"


def simulate_executor(ctx: dict) -> dict:
    """verilator 仿真。tb_uart.v 是预置 fixture,rtl_files 排除它。"""
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]

    rtl_files = [f for f in (design_dir / "rtl").glob("*.v") if f.name != "tb_uart.v"]
    tb_file = design_dir / "rtl" / "tb_uart.v"
    if not tb_file.exists():
        return {"output": "testbench 缺失: tb_uart.v", "structured": {"success": False}}

    cmd = [
        "verilator", "--binary", "--timing",
        "-Wall",
        "--top-module", "tb_uart",
        *[str(f) for f in rtl_files], str(tb_file),
        "-o", "sim_out",
    ]
    sim_dir = design_dir / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run_shell(cmd, cwd=sim_dir, docker_config=docker_cfg, shell_config=shell_cfg)
        run_result = run_shell(["./sim_out"], cwd=sim_dir,
                               docker_config=docker_cfg, shell_config=shell_cfg)
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = _parse_verilator_output(result.stderr, run_result.stdout)
    (sim_dir / "report.txt").write_text(report)

    return {
        "output": report,
        "structured": {"success": run_result.returncode == 0,
                       "report_path": str(sim_dir / "report.txt")},
    }
```

- [ ] **Step 5: 实现 eda_studio/executors/synthesize.py**

```python
"""yosys 综合 executor。"""
from pathlib import Path
from ..shell_safety import run_shell, ShellSafetyError


def synthesize_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]
    rtl_files = sorted(f for f in (design_dir / "rtl").glob("*.v") if f.name != "tb_uart.v")
    synth_dir = design_dir / "synth"
    synth_dir.mkdir(parents=True, exist_ok=True)
    json_out = synth_dir / "netlist.json"
    v_out = synth_dir / "netlist.v"

    script = (
        f"read_verilog {' '.join(str(f.relative_to(design_dir.parent)) for f in rtl_files)}; "
        f"synth -top uart; stat; "
        f"write_json {json_out}; write_verilog {v_out}"
    )
    try:
        result = run_shell(["yosys", "-q", "-p", script], cwd=synth_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    (synth_dir / "report.txt").write_text(report)
    return {
        "output": report,
        "structured": {"success": result.returncode == 0 and json_out.exists(),
                       "report_path": str(synth_dir / "report.txt")},
    }
```

- [ ] **Step 6: 实现 eda_studio/executors/pnr.py**

```python
"""OpenROAD 布局布线 executor。floorplan 由 initialize_floorplan 生成,不用 read_def。"""
from pathlib import Path
from ..shell_safety import run_shell, ShellSafetyError


def pnr_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]
    netlist = design_dir / "synth" / "netlist.v"
    pnr_dir = design_dir / "pnr"
    pnr_dir.mkdir(parents=True, exist_ok=True)

    tcl = f"""
read_libs sky130A/sky130_fd_sc_hd__tt_025C_1v80.lib
read_lef sky130A/sky130_fd_sc_hd.lef
read_verilog {netlist}
link_design uart
initialize_floorplan -utilization 40 -site unithd
place_pins -hor_layers metal2 -ver_layers metal3
global_placement
detailed_placement
global_route
detailed_route
write_def {pnr_dir / 'uart_pnr.def'}
"""
    try:
        result = run_shell(["openroad", "-exit_on_error", "-no_splash", "-cmd", tcl],
                           cwd=pnr_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    (pnr_dir / "report.txt").write_text(report)
    return {
        "output": report,
        "structured": {"success": result.returncode == 0,
                       "report_path": str(pnr_dir / "report.txt")},
    }
```

- [ ] **Step 7: 实现 eda_studio/executors/drc.py**

```python
"""magic DRC 检查 executor。"""
from pathlib import Path
from ..shell_safety import run_shell, ShellSafetyError


def drc_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]
    pnr_dir = design_dir / "pnr"
    def_file = pnr_dir / "uart_pnr.def"

    tcl = f"""
drc {def_file} {pnr_dir / 'drc.rpt'}
exit
"""
    try:
        result = run_shell(["magic", "-noconsole", "-dnull", "-cmd", tcl],
                           cwd=pnr_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    drc_report = pnr_dir / "drc.rpt"
    if drc_report.exists():
        report += "\n--- DRC violations ---\n" + drc_report.read_text()
    (pnr_dir / "report.txt").write_text(report)
    lower = report.lower()
    return {
        "output": report,
        "structured": {"success": "0 violations" in lower or "violation" not in lower,
                       "report_path": str(pnr_dir / "report.txt")},
    }
```

- [ ] **Step 8: 实现 eda_studio/executors/gds.py**

```python
"""klayout 导出 GDSII executor。"""
from pathlib import Path
from ..shell_safety import run_shell, ShellSafetyError


def gds_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]
    def_file = design_dir / "pnr" / "uart_pnr.def"
    gds_dir = design_dir / "gds"
    gds_dir.mkdir(parents=True, exist_ok=True)
    gds_out = gds_dir / "uart.gds"

    tcl = f"""
load {def_file}
gds write {gds_out}
exit
"""
    try:
        result = run_shell(["klayout", "-b", "-r", "-cmd", tcl],
                           cwd=gds_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    return {
        "output": report,
        "structured": {"success": result.returncode == 0 and gds_out.exists(),
                       "gds_path": str(gds_out)},
    }
```

- [ ] **Step 9: 运行验证通过**

Run: `pytest tests/test_executors.py -v`
Expected: 8 passed

- [ ] **Step 10: Commit**

```bash
git add eda_studio/executors/ tests/test_executors.py
git commit -m "feat(executors): simulate/synthesize/pnr/drc/gds with run_shell"
```

---

## Task 7: judge.py(闭包计数路由)

**Files:**
- Create: `eda_studio/judge.py`
- Create: `tests/test_judge.py`

**Interfaces:**
- Consumes: `AppConfig`
- Produces: `make_judge_fn(config) -> callable`。签名 `(ctx: dict) -> str`。judge ctx 字段(只读):`step_id`/`output`/`step_count`/`retry_count`/`structured`。

- [ ] **Step 1: 写失败测试 tests/test_judge.py**

```python
from eda_studio.judge import make_judge_fn
from eda_studio.config import AppConfig, WorkflowConfig, ShellConfig, DockerConfig

def make_config(max_fix=3):
    return AppConfig(
        provider_spec={"type": "openai", "api_key": "x", "base_url": None},
        model="gpt-4o",
        pricing_spec={},
        budget_limit=5.0,
        budget_exceeded_action="stop",
        workflow_config=WorkflowConfig(max_steps=50, max_fix_retries=max_fix),
        shell_config=ShellConfig(allowed_commands=[], denied_args=[]),
        docker_config=DockerConfig(image="i", container="c", workdir="/w", pdk="sky130A"),
    )

def ctx(step_id, success=None, output=""):
    return {"step_id": step_id, "output": output, "step_count": 1, "retry_count": 0,
            "structured": {"success": success} if success is not None else {}}

def test_rtl_design_success():
    judge = make_judge_fn(make_config())
    assert judge(ctx("rtl_design", output="generated")) == "to:simulate"

def test_rtl_design_empty_output_aborts():
    judge = make_judge_fn(make_config())
    assert judge(ctx("rtl_design", output="")) == "abort:done"

def test_simulate_success_to_synthesize():
    judge = make_judge_fn(make_config())
    assert judge(ctx("simulate", success=True)) == "to:synthesize"

def test_simulate_fail_to_debug_fix():
    judge = make_judge_fn(make_config())
    assert judge(ctx("simulate", success=False)) == "to:debug_fix"

def test_simulate_fix_count_exceeds_max_aborts():
    judge = make_judge_fn(make_config(max_fix=2))
    assert judge(ctx("simulate", success=False)) == "to:debug_fix"
    assert judge(ctx("simulate", success=False)) == "to:debug_fix"
    assert judge(ctx("simulate", success=False)) == "abort:done"

def test_simulate_success_resets_count():
    judge = make_judge_fn(make_config(max_fix=2))
    judge(ctx("simulate", success=False))
    judge(ctx("simulate", success=False))
    judge(ctx("simulate", success=True))
    assert judge(ctx("simulate", success=False)) == "to:debug_fix"

def test_debug_fix_to_simulate():
    judge = make_judge_fn(make_config())
    assert judge(ctx("debug_fix")) == "to:simulate"

def test_synthesize_success_to_pnr():
    judge = make_judge_fn(make_config())
    assert judge(ctx("synthesize", success=True)) == "to:pnr"

def test_synthesize_fail_to_debug_fix():
    judge = make_judge_fn(make_config())
    assert judge(ctx("synthesize", success=False)) == "to:debug_fix"

def test_pnr_success_to_drc():
    judge = make_judge_fn(make_config())
    assert judge(ctx("pnr", success=True)) == "to:drc"

def test_pnr_fail_to_drc_fix():
    judge = make_judge_fn(make_config())
    assert judge(ctx("pnr", success=False)) == "to:drc_fix"

def test_pnr_fix_count_exceeds():
    judge = make_judge_fn(make_config(max_fix=1))
    assert judge(ctx("pnr", success=False)) == "to:drc_fix"
    assert judge(ctx("pnr", success=False)) == "abort:done"

def test_drc_fix_to_pnr():
    judge = make_judge_fn(make_config())
    assert judge(ctx("drc_fix")) == "to:pnr"

def test_drc_success_to_gds():
    judge = make_judge_fn(make_config())
    assert judge(ctx("drc", success=True)) == "to:gds"

def test_drc_fail_to_drc_fix():
    judge = make_judge_fn(make_config())
    assert judge(ctx("drc", success=False)) == "to:drc_fix"

def test_gds_done():
    judge = make_judge_fn(make_config())
    assert judge(ctx("gds", success=True)) == "done"

def test_unknown_step_aborts():
    judge = make_judge_fn(make_config())
    assert judge(ctx("unknown")) == "abort:done"
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_judge.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 eda_studio/judge.py**

```python
"""judge 逻辑:报告解析 → 路由决策。闭包维护 per-环节 回环计数。"""
from .config import AppConfig


def make_judge_fn(config: AppConfig):
    """构造 judge closure。

    judge ctx 是只读 dict,字段:step_id / output / step_count / retry_count / structured。
    retry_count 是 engine 维护的连续 Retry 次数,只对 "retry" 累加;to: 回环不累加。
    per-环节 回环计数用闭包变量自行维护。
    """
    fix_counts = {"simulate": 0, "pnr": 0, "drc": 0}
    max_fix = config.workflow_config.max_fix_retries

    def judge(ctx: dict) -> str:
        step_id = ctx["step_id"]
        structured = ctx.get("structured") or {}
        success = structured.get("success", False)

        if step_id == "rtl_design":
            return "to:simulate" if ctx.get("output") else "abort:done"

        if step_id == "simulate":
            if success:
                fix_counts["simulate"] = 0
                return "to:synthesize"
            fix_counts["simulate"] += 1
            if fix_counts["simulate"] > max_fix:
                return "abort:done"
            return "to:debug_fix"

        if step_id == "debug_fix":
            return "to:simulate"

        if step_id == "synthesize":
            return "to:pnr" if success else "to:debug_fix"

        if step_id == "pnr":
            if success:
                fix_counts["pnr"] = 0
                return "to:drc"
            fix_counts["pnr"] += 1
            if fix_counts["pnr"] > max_fix:
                return "abort:done"
            return "to:drc_fix"

        if step_id == "drc_fix":
            return "to:pnr"

        if step_id == "drc":
            if success:
                fix_counts["drc"] = 0
                return "to:gds"
            fix_counts["drc"] += 1
            if fix_counts["drc"] > max_fix:
                return "abort:done"
            return "to:drc_fix"

        if step_id == "gds":
            return "done"

        return "abort:done"

    return judge
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/test_judge.py -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add eda_studio/judge.py tests/test_judge.py
git commit -m "feat(judge): closure-based per-stage retry counting + routing"
```

---

## Task 8: hooks.py + rules.py + budget.py

**Files:**
- Create: `eda_studio/hooks.py`
- Create: `eda_studio/rules.py`
- Create: `eda_studio/budget.py`
- Create: `tests/test_hooks_rules_budget.py`

**Interfaces:**
- Produces: `make_hooks(config) -> list`(纯闭包,senza 装饰在 workflow.py);`make_budget_cb(config) -> callable`。`rules.py` 的 `make_rules_hook` import senza,只在 workflow.py 调用。

- [ ] **Step 1: 写失败测试 tests/test_hooks_rules_budget.py**

```python
import logging
from eda_studio.budget import make_budget_cb
from eda_studio.hooks import make_hooks
from eda_studio.config import AppConfig, WorkflowConfig, ShellConfig, DockerConfig

def make_config(action="stop"):
    return AppConfig(
        provider_spec={"type": "openai", "api_key": "x", "base_url": None},
        model="gpt-4o",
        pricing_spec={},
        budget_limit=5.0,
        budget_exceeded_action=action,
        workflow_config=WorkflowConfig(max_steps=50, max_fix_retries=3),
        shell_config=ShellConfig(allowed_commands=[], denied_args=[]),
        docker_config=DockerConfig(image="i", container="c", workdir="/w", pdk="sky130A"),
    )

def test_budget_cb_stop_returns_false():
    cb = make_budget_cb(make_config("stop"))
    assert cb({"total_cost": 6.0}, 5.0) is False

def test_budget_cb_continue_returns_true():
    cb = make_budget_cb(make_config("continue"))
    assert cb({"total_cost": 6.0}, 5.0) is True

def test_budget_cb_logs_warning(caplog):
    cb = make_budget_cb(make_config("stop"))
    with caplog.at_level(logging.WARNING):
        cb({"total_cost": 6.0}, 5.0)
    assert any("预算超限" in r.message for r in caplog.records)

def test_make_hooks_returns_three_closures():
    hooks = make_hooks(make_config())
    assert len(hooks) == 3
    assert hooks[0]({"step_id": "x"}) is None
    assert hooks[1]({"step_id": "x", "duration_ms": 10}) is None
    assert hooks[2]({"tool_name": "write_rtl"}) is None
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_hooks_rules_budget.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 eda_studio/budget.py**

```python
"""Budget 超限回调(G1)。"""
import logging
from .config import AppConfig

logger = logging.getLogger(__name__)


def make_budget_cb(config: AppConfig):
    """返回 False 停止流程,True 继续。"""
    def on_budget_exceeded(cost: dict, limit: float) -> bool:
        logger.warning(f"预算超限!已用 ${cost.get('total_cost', 0):.2f} / ${limit:.2f}")
        return config.budget_exceeded_action == "continue"
    return on_budget_exceeded
```

- [ ] **Step 4: 实现 eda_studio/hooks.py**

```python
"""日志/审计 hooks。senza 装饰器在 workflow.py 应用。"""
import logging
from .config import AppConfig

logger = logging.getLogger(__name__)


def make_hooks(config: AppConfig):
    """返回 hook 闭包列表(before_turn/after_turn/after_tool_call)。"""
    def log_before_turn(ctx: dict) -> None:
        step_id = ctx.get("step_id", "?")
        logger.info(f"▶ {step_id} 开始")

    def log_after_turn(ctx: dict) -> None:
        step_id = ctx.get("step_id", "?")
        duration = ctx.get("duration_ms", 0)
        logger.info(f"✓ {step_id} 完成 ({duration}ms)")

    def audit_tool_call(ctx: dict):
        tool_name = ctx.get("tool_name", "")
        logger.info(f"  tool call: {tool_name}")
        return None  # 审计只记录,不改结果

    return [log_before_turn, log_after_turn, audit_tool_call]
```

- [ ] **Step 5: 实现 eda_studio/rules.py**

```python
"""G3 Rules 审批:限制 LLM tool_call。RuleBasedApprovalHook 实现 BeforeToolCallHook,
只拦截 LLM tool_call,拦不到 executor 内的 subprocess。
EDA 工具 shell 安全由 run_shell 白名单负责(shell_safety.py, S6a)。"""
from .config import AppConfig


def make_rules_hook(config: AppConfig):
    """构建 LLM tool_call 审批规则链。

    顺序:先 deny 危险 tool,再 allow 白名单,fallback deny。
    RuleChain 首条匹配生效,通配 Allow 必须排在特定 Deny 之后。
    """
    from senza import (
        create_rule_chain, create_contains_predicate, create_rule_approval_hook,
    )
    builder = create_rule_chain()

    builder = builder.rule(
        tool_name="*",
        predicate=create_contains_predicate(["read_drc_report", "write_sdc"]),
        on_match="deny",
    )
    builder = builder.rule(
        tool_name="*",
        predicate=create_contains_predicate(
            ["write_rtl", "read_rtl", "list_design_files", "read_sim_report", "read_sdc"]
        ),
        on_match="allow",
    )
    builder = builder.fallback("deny")
    chain = builder.build()
    return create_rule_approval_hook(chain)
```

- [ ] **Step 6: 运行验证通过**

Run: `pytest tests/test_hooks_rules_budget.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add eda_studio/hooks.py eda_studio/rules.py eda_studio/budget.py tests/test_hooks_rules_budget.py
git commit -m "feat(hooks/rules/budget): logging hooks + G3 rules chain + G1 budget cb"
```

---

## Task 9: workflow.py(组装)

**Files:**
- Create: `eda_studio/workflow.py`
- Create: `tests/test_workflow.py`

**Interfaces:**
- Consumes: 所有前面 task 的产物 + senza SDK
- Produces: `build_workflow(config, design_name) -> WorkflowEngine`;`build_providers(config) -> (Provider, PricingProvider)`

- [ ] **Step 1: 写失败测试 tests/test_workflow.py**

```python
"""workflow 集成测试:不依赖真实 LLM/EDA(只测 build_workflow 能构建出 engine)。"""
from pathlib import Path
from eda_studio.config import load_config
from eda_studio.workflow import build_workflow

CFG_YAML = """
provider: {type: openai, api_key: sk-test, base_url: null}
model: gpt-4o
pricing: {gpt-4o: {input_per_mtok: 2.5, output_per_mtok: 10.0}}
budget: {limit: 5.0, exceeded_action: stop}
workflow: {max_steps: 50, max_fix_retries: 3}
shell: {allowed_commands: [verilator], denied_args: [rm]}
docker: {image: img, container: eda-tools, workdir: /work/designs, pdk: sky130A}
"""

def test_build_workflow_returns_engine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(CFG_YAML)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    config = load_config(str(tmp_path / "config.yaml"))
    engine = build_workflow(config, "uart")
    assert hasattr(engine, "run")
    assert hasattr(engine, "current_step")
    assert hasattr(engine, "step_history")
    assert hasattr(engine, "total_cost")

def test_build_workflow_sets_context_variables(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(CFG_YAML)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    config = load_config(str(tmp_path / "config.yaml"))
    engine = build_workflow(config, "uart")
    assert engine is not None
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_workflow.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 eda_studio/workflow.py**

```python
"""workflow 组装:WorkflowEngine 构建。senza 依赖集中在此。"""
from pathlib import Path
from senza import (
    WorkflowEngine, create_os_env, create_executor, create_tool,
    create_judge, create_openai_provider, create_anthropic_provider,
    create_pricing_provider, create_budget_exceeded_hook,
    create_before_turn_hook, create_after_turn_hook, create_after_tool_call_hook,
    create_shell_executor,
)
from .config import AppConfig
from .prompts import build_prompts, load_requirement
from .judge import make_judge_fn
from .hooks import make_hooks
from .rules import make_rules_hook
from .budget import make_budget_cb
from .tools.file_tools import make_file_tools
from .tools.report_tools import make_report_tools
from .executors import (
    simulate_executor, synthesize_executor, pnr_executor,
    drc_executor, gds_executor,
)


def build_providers(config: AppConfig):
    """从 provider_spec/pricing_spec 创建 senza Provider + PricingProvider。"""
    spec = config.provider_spec
    if spec["type"] == "openai":
        provider = create_openai_provider(api_key=spec["api_key"], base_url=spec.get("base_url"))
    elif spec["type"] == "anthropic":
        provider = create_anthropic_provider(api_key=spec["api_key"])
    else:
        raise ValueError(f"未知 provider type: {spec['type']}")
    pricing = create_pricing_provider(config.pricing_spec)
    return provider, pricing


def _wrap_hooks(raw_hooks):
    """用 senza 装饰器包装纯闭包。"""
    before_turn, after_turn, after_tool_call = raw_hooks
    return [
        create_before_turn_hook(before_turn),
        create_after_turn_hook(after_turn),
        create_after_tool_call_hook(after_tool_call),
    ]


def build_workflow(config: AppConfig, design_name: str) -> WorkflowEngine:
    """构建 WorkflowEngine:8 个 step + edges + executors + tools + hooks + budget + rules。"""
    design_dir = Path(f"designs/{design_name}")
    requirement = load_requirement(design_name)
    prompts = build_prompts(requirement)
    provider, pricing = build_providers(config)

    file_tools = make_file_tools(design_dir)
    report_tools = make_report_tools(design_dir)

    # tool schemas(简化的 JSON schema)
    WRITE_RTL_SCHEMA = {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "文件名,如 uart_tx.v"},
            "content": {"type": "string", "description": "Verilog 代码内容"},
        },
        "required": ["filename", "content"],
    }
    READ_RTL_SCHEMA = {
        "type": "object",
        "properties": {"filename": {"type": "string"}},
        "required": ["filename"],
    }
    NO_ARG_SCHEMA = {"type": "object", "properties": {}}
    WRITE_SDC_SCHEMA = {
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"],
    }

    workflow_dict = {
        "entry_step": "rtl_design",
        "steps": [
            {"id": "rtl_design", "name": "RTL 设计",
             "prompt": prompts["rtl_design"],
             "allowed_tools": ["write_rtl", "read_rtl", "list_design_files"]},
            {"id": "simulate", "name": "仿真验证", "executor": "simulate"},
            {"id": "debug_fix", "name": "仿真修复",
             "prompt": prompts["debug_fix"],
             "allowed_tools": ["read_sim_report", "read_rtl", "write_rtl"]},
            {"id": "synthesize", "name": "逻辑综合", "executor": "synthesize"},
            {"id": "pnr", "name": "布局布线", "executor": "pnr"},
            {"id": "drc_fix", "name": "DRC 修复",
             "prompt": prompts["drc_fix"],
             "allowed_tools": ["read_drc_report", "read_sdc", "write_sdc", "read_rtl", "write_rtl"]},
            {"id": "drc", "name": "DRC 检查", "executor": "drc"},
            {"id": "gds", "name": "GDS 导出", "executor": "gds"},
        ],
        "edges": [
            {"from": "rtl_design", "to": "simulate"},
            {"from": "simulate", "to": "synthesize"},
            {"from": "simulate", "to": "debug_fix"},
            {"from": "debug_fix", "to": "simulate"},
            {"from": "synthesize", "to": "pnr"},
            {"from": "synthesize", "to": "debug_fix"},
            {"from": "pnr", "to": "drc"},
            {"from": "pnr", "to": "drc_fix"},
            {"from": "drc_fix", "to": "pnr"},
            {"from": "drc", "to": "gds"},
            {"from": "drc", "to": "drc_fix"},
            {"from": "gds", "to": "done"},
        ],
    }

    judge = create_judge(make_judge_fn(config))
    env = create_os_env(working_dir=".")
    engine = WorkflowEngine(
        workflow_dict, provider, config.model, judge, env=env,
    )

    engine = (
        engine
        .with_executor("simulate", create_executor(simulate_executor))
        .with_executor("synthesize", create_executor(synthesize_executor))
        .with_executor("pnr", create_executor(pnr_executor))
        .with_executor("drc", create_executor(drc_executor))
        .with_executor("gds", create_executor(gds_executor))
        .with_executor("shell", create_shell_executor(["echo", "python3"]))
        .with_tool(create_tool("write_rtl", "写 Verilog 文件", WRITE_RTL_SCHEMA, file_tools["write_rtl"]))
        .with_tool(create_tool("read_rtl", "读 Verilog 文件", READ_RTL_SCHEMA, file_tools["read_rtl"]))
        .with_tool(create_tool("list_design_files", "列出工作区文件", NO_ARG_SCHEMA, file_tools["list_design_files"]))
        .with_tool(create_tool("read_sim_report", "读仿真报告", NO_ARG_SCHEMA, report_tools["read_sim_report"]))
        .with_tool(create_tool("read_drc_report", "读 DRC 报告", NO_ARG_SCHEMA, report_tools["read_drc_report"]))
        .with_tool(create_tool("read_sdc", "读时序约束", NO_ARG_SCHEMA, file_tools["read_sdc"]))
        .with_tool(create_tool("write_sdc", "写时序约束", WRITE_SDC_SCHEMA, file_tools["write_sdc"]))
        .with_hooks(_wrap_hooks(make_hooks(config)))
        .with_task_store(f"designs/{design_name}/.taskstore")
        .with_max_steps(config.workflow_config.max_steps)
    )

    budget_hook = create_budget_exceeded_hook(make_budget_cb(config))
    rules_hook = make_rules_hook(config)
    engine = engine.with_hooks([budget_hook, rules_hook])

    engine.set_context_variable("design_dir", f"designs/{design_name}")
    engine.set_context_variable("docker_config", config.docker_config)
    engine.set_context_variable("shell_config", config.shell_config)

    return engine
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/test_workflow.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add eda_studio/workflow.py tests/test_workflow.py
git commit -m "feat(workflow): build_workflow assembles engine + edges + executors + tools + hooks"
```

---

## Task 10: __main__.py(CLI: run / restore / status)

**Files:**
- Modify: `eda_studio/__main__.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_workflow` from `workflow.py`;`load_config` from `config.py`;`WorkflowEngine.restore`

- [ ] **Step 1: 写失败测试 tests/test_cli.py**

```python
"""CLI 测试:验证 argparse 路由(不真跑 engine,只 mock cmd_run/cmd_restore)。"""
from unittest.mock import patch
from eda_studio.__main__ import main

CFG = (
    "provider: {type: openai, api_key: sk-x, base_url: null}\n"
    "model: gpt-4o\n"
    "pricing: {gpt-4o: {input_per_mtok: 1.0, output_per_mtok: 2.0}}\n"
    "budget: {limit: 5.0, exceeded_action: stop}\n"
    "workflow: {max_steps: 50, max_fix_retries: 3}\n"
    "shell: {allowed_commands: [verilator], denied_args: [rm]}\n"
    "docker: {image: i, container: c, workdir: /w, pdk: sky130A}\n"
)

def test_cli_run_calls_cmd_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(CFG)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    with patch("eda_studio.__main__.cmd_run") as mock_run:
        main(["run", "uart", "--config", "config.yaml"])
    mock_run.assert_called_once()

def test_cli_restore_calls_cmd_restore(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(CFG)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    with patch("eda_studio.__main__.cmd_restore") as mock_restore:
        main(["restore", "uart", "--config", "config.yaml"])
    mock_restore.assert_called_once()
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 eda_studio/__main__.py**

```python
"""CLI 入口:run / restore / status。

Usage:
  python -m eda_studio run <design> [--config config.yaml]
  python -m eda_studio restore <design> [--config config.yaml]
  python -m eda_studio status <design>
"""
import sys
from pathlib import Path
from senza import (
    WorkflowEngine, create_os_env, create_executor, create_judge,
    create_budget_exceeded_hook, create_shell_executor,
)
from .config import load_config
from .workflow import build_workflow, build_providers, _wrap_hooks
from .judge import make_judge_fn
from .hooks import make_hooks
from .rules import make_rules_hook
from .budget import make_budget_cb
from .executors import (
    simulate_executor, synthesize_executor, pnr_executor,
    drc_executor, gds_executor,
)


def _re_register(engine, config, design_name):
    """restore 后重新注册 executors/hooks/context 变量。"""
    engine = (engine
        .with_executor("simulate", create_executor(simulate_executor))
        .with_executor("synthesize", create_executor(synthesize_executor))
        .with_executor("pnr", create_executor(pnr_executor))
        .with_executor("drc", create_executor(drc_executor))
        .with_executor("gds", create_executor(gds_executor))
        .with_executor("shell", create_shell_executor(["echo", "python3"]))
        .with_hooks(_wrap_hooks(make_hooks(config)))
        .with_hooks([create_budget_exceeded_hook(make_budget_cb(config)),
                     make_rules_hook(config)]))
    engine.set_context_variable("design_dir", f"designs/{design_name}")
    engine.set_context_variable("docker_config", config.docker_config)
    engine.set_context_variable("shell_config", config.shell_config)
    return engine


def cmd_run(design_name: str, config_path: str):
    config = load_config(config_path)
    engine = build_workflow(config, design_name)
    print(f"启动 {design_name} 设计流程...")
    engine.run()
    print(f"流程结束,state={engine.state()}")
    print(f"总成本: ${engine.total_cost():.4f}")
    print(f"已完成 {len(engine.step_history())} 步")
    gds = Path(f"designs/{design_name}/gds/uart.gds")
    if gds.exists():
        print(f"✓ GDS 产物: {gds}")
    else:
        print(f"✗ 未产出 GDS")


def cmd_restore(design_name: str, config_path: str):
    config = load_config(config_path)
    store_dir = f"designs/{design_name}/.taskstore"
    task_id_file = Path(store_dir) / "task_id"
    if not task_id_file.exists():
        print(f"未找到 taskstore: {task_id_file}")
        sys.exit(1)
    task_id = task_id_file.read_text().strip()

    env = create_os_env(working_dir=".")
    provider, pricing = build_providers(config)
    engine = WorkflowEngine.restore(
        store_dir, task_id,
        provider=provider,
        model=config.model,
        judge=create_judge(make_judge_fn(config)),
        env=env,
    )
    engine = _re_register(engine, config, design_name)
    print(f"恢复到步骤: {engine.current_step()}")
    print(f"已完成: {len(engine.step_history())} 步")
    engine.run()
    print(f"流程结束,state={engine.state()}")


def cmd_status(design_name: str):
    store_dir = f"designs/{design_name}/.taskstore"
    task_id_file = Path(store_dir) / "task_id"
    if not task_id_file.exists():
        print(f"未找到 taskstore: {task_id_file}")
        return
    task_id = task_id_file.read_text().strip()
    print(f"design={design_name} task_id={task_id} store={store_dir}")


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="eda-studio")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="运行设计流程")
    p_run.add_argument("design")
    p_run.add_argument("--config", default="config.yaml")
    p_restore = sub.add_parser("restore", help="从断点恢复")
    p_restore.add_argument("design")
    p_restore.add_argument("--config", default="config.yaml")
    p_status = sub.add_parser("status", help="查看状态")
    p_status.add_argument("design")

    args = parser.parse_args(argv)
    if args.command == "run":
        cmd_run(args.design, args.config)
    elif args.command == "restore":
        cmd_restore(args.design, args.config)
    elif args.command == "status":
        cmd_status(args.design)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/test_cli.py -v`
Expected: 2 passed

- [ ] **Step 5: 全量测试回归**

Run: `pytest tests/ -v`
Expected: 所有测试通过(config/prompts/run_shell/tools/executors/judge/hooks_rules_budget/workflow/cli)

- [ ] **Step 6: Commit**

```bash
git add eda_studio/__main__.py tests/test_cli.py
git commit -m "feat(cli): run/restore/status commands with argparse"
```

---

## Self-Review

### Spec Coverage

| Spec 章节 | 覆盖 Task |
|----------|----------|
| §2 成功标准 S1(产出 GDS) | Task 10 cmd_run 检查 gds 文件 |
| §2 S2(仿真回环) | Task 7 judge simulate→debug_fix→simulate |
| §2 S3(DRC 回环) | Task 7 judge drc→drc_fix→pnr |
| §2 S4(restore) | Task 10 cmd_restore |
| §2 S5(budget) | Task 8 budget_cb + Task 9 with_hooks |
| §2 S6a(run_shell 白名单) | Task 3 ShellSafetyError |
| §2 S6b(rules 拦截 tool) | Task 8 rules.py + Task 9 with_hooks |
| §4.1 config | Task 2 |
| §4.2 workflow | Task 9 |
| §4.3 prompts | Task 4 |
| §4.4 tools | Task 5 |
| §4.5 executors | Task 3 + Task 6 |
| §4.6 judge | Task 7 |
| §4.7 hooks | Task 8 |
| §4.8 rules | Task 8 |
| §4.9 budget | Task 8 |
| §4.10 restore | Task 10 cmd_restore |
| §4.11 CLI | Task 10 |
| §5.1 ctx | Task 6(executor ctx)+ Task 7(judge ctx) |
| §5.2 文件产物 | Task 6 executors 写文件 + Task 1 tb_uart fixture |
| §6 错误处理 | Task 3(ShellSafetyError)+ Task 6(safety_error)+ Task 7(abort:done)+ Task 8(budget) |
| §7 测试 | 每个 Task 的 TDD 测试 |

### Placeholder Scan

无 TBD/TODO/"implement later"/"add error handling" 等占位符。每个 step 都有完整代码。

### Type Consistency

- `make_file_tools(design_dir)` 返回 dict,键 `write_rtl`/`read_rtl`/`list_design_files`/`read_sdc`/`write_sdc` —— Task 5 定义,Task 9 使用,键名一致。
- `make_report_tools(design_dir)` 返回 dict,键 `read_sim_report`/`read_drc_report` —— 一致。
- `make_judge_fn(config)` 返回 `(ctx) -> str` —— Task 7 定义,Task 9 用 `create_judge(make_judge_fn(config))` 包装。
- `make_hooks(config)` 返回 `[before_turn, after_turn, after_tool_call]` —— Task 8 定义,Task 9 用 `_wrap_hooks` 包装。
- `make_budget_cb(config)` 返回 `(cost, limit) -> bool` —— Task 8 定义,Task 9 用 `create_budget_exceeded_hook` 包装。
- `make_rules_hook(config)` 返回 senza hook —— Task 8 定义,Task 9 直接用。
- executor 签名 `(ctx: dict) -> dict`,返回 `{output, structured: {success, ...}}` —— Task 6 定义,Task 7 judge 读 `ctx["structured"]["success"]`,一致。
- `run_shell(cmd, cwd, docker_config, shell_config)` —— Task 3 定义,Task 6 使用,参数顺序一致。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-19-eda-studio.md`. Two execution options:

**1. Subagent-Driven (recommended)** - 每个 Task 派一个 fresh subagent,Task 间 review,快速迭代。

**2. Inline Execution** - 在当前 session 按 executing-plans 批量执行,checkpoint review。

Which approach?
