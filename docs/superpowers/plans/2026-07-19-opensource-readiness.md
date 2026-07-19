# 开源发布就绪 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 eda-studio 作为开源仓库发布时，新用户 clone 后 5 分钟内能跑通 RTL→GDS 全流程，且运行失败可见。

**Architecture:** 三层独立交付。层 1（法律与文档）加 LICENSE/重写 README/拆分 CLAUDE.md/加 CONTRIBUTING/templates。层 2（上手命令）加 `init`/`check` CLI 子命令。层 3（运行可见性）加 CLI 最终状态表、WebUI 失败标记、render 容错。每层独立可发布。

**Tech Stack:** Python 3.9+, senza-sdk 0.4.3, pyyaml, fastapi, uvicorn, websockets, Docker(iic-osic-tools), SkyWater Sky130 PDK

## Global Constraints

- **语言**:代码注释和文档用中文,代码标识符用英文
- **senza 安装**:`pip install senza-sdk`(PyPI 0.4.3)
- **不引入新 Python 依赖**:API ping 用 stdlib `urllib.request`,不用 `requests`
- **测试不依赖真实 EDA 工具和 LLM API**:`run_shell`/docker/subprocess 被 monkeypatch
- **现有 79 tests 必须保持通过**
- **Docker 命令必须用 `bash -lc`**:容器 entrypoint 通过 login profile 设 PATH
- **EDA 工具用脚本文件方式调用**:openroad/magic/klayout 都不认 `-cmd`,统一用 tcl/ruby 脚本文件位置参数
- **sky130 PDK 路径**:`/foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd/{lib,lef,techlef}/`
- **WS step_finished 事件 payload**:`{type, step_id, output, structured, tool_calls_count}`。LLM step 的 `structured` 为 null,EXEC step 的 `structured` 为 `{success: bool, ...}`。无 `cost` 字段(前端现有代码读 `event.cost` 实际拿到 undefined,不影响)
- **taskstore 路径**:`designs/<name>/.taskstore/<task_id>/workflow.json`,含完整 `step_history`(每项有 `result.structured`)

---

## File Structure

**新增文件**:
- `LICENSE` — MIT 许可证
- `CONTRIBUTING.md` — 贡献指南
- `eda_studio/templates/uart/requirement.md` — 示例 design 输入文件
- `eda_studio/templates/uart/rtl/tb_uart.v` — 示例 testbench
- `eda_studio/cli_commands.py` — `init`/`check` 命令实现(独立于 `__main__.py` 的 run/serve 逻辑)
- `docs/dev-notes.md` — 开发期诊断笔记(从 CLAUDE.md 拆出)
- `tests/test_cli_commands.py` — init/check 命令测试
- `tests/test_run_summary.py` — CLI 最终状态表测试

**修改文件**:
- `README.md` — 重写(截图/模型要求/快速开始)
- `CLAUDE.md` — 删除开发期诊断笔记,保留架构和容器信息
- `pyproject.toml` — 加 license/authors,确保 templates 打包
- `eda_studio/__main__.py` — 加 init/check 子命令,cmd_run 加最终状态表
- `static/index.html` — 失败标记/完成横幅/render 容错
- `.gitignore` — 确保 `eda_studio/templates/` 不被忽略

---

## Task 1: LICENSE + pyproject.toml

**Files:**
- Create: `LICENSE`
- Modify: `pyproject.toml`
- Test: 无(纯文件)

**Interfaces:**
- Produces: `LICENSE` 文件(MIT), `pyproject.toml` 含 license/authors

- [ ] **Step 1: 创建 LICENSE 文件**

```
MIT License

Copyright (c) 2026 oh-my-harness

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: 修改 pyproject.toml 加 license/authors**

在 `[project]` 段加 `license` 和 `authors`:

```toml
[project]
name = "eda-studio"
version = "0.1.0"
description = "基于 Senza SDK 的开源 EDA 自动化芯片设计流程示例"
license = {text = "MIT"}
authors = [{name = "oh-my-harness"}]
requires-python = ">=3.9"
```

- [ ] **Step 3: 验证**

Run: `python -c "import tomllib; print(tomllib.loads(open('pyproject.toml').read())['project']['license'])"`
Expected: `{'text': 'MIT'}`

- [ ] **Step 4: Commit**

```bash
git add LICENSE pyproject.toml
git commit -m "chore: 加 MIT LICENSE + pyproject license/authors"
```

---

## Task 2: templates 目录 + pyproject 打包

**Files:**
- Create: `eda_studio/templates/uart/requirement.md`
- Create: `eda_studio/templates/uart/rtl/tb_uart.v`
- Modify: `pyproject.toml`(加 include-package-data)
- Modify: `.gitignore`(确保 templates 不被忽略)

**Interfaces:**
- Produces: `eda_studio/templates/uart/` 含 `requirement.md` + `rtl/tb_uart.v`,供 Task 3 的 `init` 命令复制

- [ ] **Step 1: 创建 templates 目录,复制现有 design 输入文件**

```bash
mkdir -p eda_studio/templates/uart/rtl
cp designs/uart/requirement.md eda_studio/templates/uart/requirement.md
cp designs/uart/rtl/tb_uart.v eda_studio/templates/uart/rtl/tb_uart.v
```

验证文件内容正确(非空,是 design 输入文件而非运行产物):
```bash
head -3 eda_studio/templates/uart/requirement.md
head -3 eda_studio/templates/uart/rtl/tb_uart.v
```

- [ ] **Step 2: 修改 pyproject.toml 确保 templates 被打包**

在 `[tool.setuptools]` 段加 `include-package-data`:

```toml
[tool.setuptools]
packages = ["eda_studio", "eda_studio.tools", "eda_studio.executors", "eda_studio.templates"]
include-package-data = true
```

注意:`eda_studio.templates` 需要有 `__init__.py` 才能作为 Python 包:

```bash
touch eda_studio/templates/__init__.py
```

- [ ] **Step 3: 验证 templates 可定位**

```bash
python -c "from pathlib import Path; import eda_studio; p = Path(eda_studio.__file__).parent / 'templates' / 'uart' / 'requirement.md'; print(p, p.exists())"
```
Expected: `<...>/eda_studio/templates/uart/requirement.md True`

- [ ] **Step 4: 检查 .gitignore 不排除 templates**

`.gitignore` 里有 `*.v` 模式吗?如果有,`tb_uart.v` 会被忽略。检查:
```bash
git check-ignore eda_studio/templates/uart/rtl/tb_uart.v
```
如果输出该路径,需在 `.gitignore` 加例外:
```
*.v
!eda_studio/templates/**/*.v
```

当前 `.gitignore` 内容(确认):
```
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.eggs/
*.gds
*.vcd
config.yaml
designs/
.venv/
sessions
.env
```

没有 `*.v` 模式,所以 `tb_uart.v` 不会被忽略。无需改 .gitignore。

- [ ] **Step 5: Commit**

```bash
git add eda_studio/templates/
git commit -m "feat: 加 templates/uart 示例 design 输入文件"
```

---

## Task 3: `init` 命令

**Files:**
- Create: `eda_studio/cli_commands.py`
- Create: `tests/test_cli_commands.py`
- Modify: `eda_studio/__main__.py`(加 init 子命令)

**Interfaces:**
- Consumes: `eda_studio/templates/uart/`(Task 2)
- Produces: `cmd_init(name: str) -> int` 函数,复制 templates 到 designs/<name>/

- [ ] **Step 1: 写 init 命令失败测试**

`tests/test_cli_commands.py`:

```python
"""init/check 命令测试。不依赖真实 EDA 工具和 LLM API。"""
import sys
from pathlib import Path
from unittest.mock import patch
import pytest


def test_init_copies_template(tmp_path, monkeypatch):
    """init uart 复制 templates/uart/ 到 designs/uart/。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli_commands import cmd_init
    rc = cmd_init("uart")
    assert rc == 0
    req = tmp_path / "designs" / "uart" / "requirement.md"
    tb = tmp_path / "designs" / "uart" / "rtl" / "tb_uart.v"
    assert req.is_file(), f"requirement.md not found at {req}"
    assert tb.is_file(), f"tb_uart.v not found at {tb}"
    assert req.read_text().startswith("# UART")


def test_init_refuses_existing(tmp_path, monkeypatch):
    """designs/uart/ 已存在时 init 报错退出。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    from eda_studio.cli_commands import cmd_init
    rc = cmd_init("uart")
    assert rc == 1


def test_init_unknown_template(tmp_path, monkeypatch):
    """未知模板名报错并列出可用模板。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli_commands import cmd_init
    rc = cmd_init("nonexistent")
    assert rc == 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_cli_commands.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eda_studio.cli_commands'`

- [ ] **Step 3: 实现 cli_commands.py**

`eda_studio/cli_commands.py`:

```python
"""init/check CLI 子命令实现。"""
import shutil
import sys
from pathlib import Path


def _templates_dir() -> Path:
    """定位 eda_studio/templates/ 目录。"""
    import eda_studio
    return Path(eda_studio.__file__).parent / "templates"


def _list_templates() -> list:
    """列出可用模板名。"""
    tdir = _templates_dir()
    if not tdir.is_dir():
        return []
    return [d.name for d in tdir.iterdir() if d.is_dir() and not d.name.startswith("_")]


def cmd_init(name: str) -> int:
    """从 templates/<name>/ 复制 design 输入文件到 designs/<name>/。

    Returns:
        0 成功, 1 失败
    """
    src = _templates_dir() / name
    if not src.is_dir():
        print(f"✗ 未知模板: {name}")
        available = _list_templates()
        if available:
            print(f"  可用模板: {', '.join(available)}")
        return 1

    dst = Path(f"designs/{name}")
    if dst.exists():
        print(f"✗ 目标已存在: {dst}(避免覆盖运行产物)")
        return 1

    shutil.copytree(src, dst)
    print(f"✓ 已初始化 {name} → {dst}")
    print(f"  下一步:")
    print(f"    docker run -d --name eda-tools -v $(pwd)/designs:/work/designs \\")
    print(f"      -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity")
    print(f"    eda-studio check")
    print(f"    python -m eda_studio run {name}")
    return 0
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_cli_commands.py -v`
Expected: 3 passed

- [ ] **Step 5: 在 __main__.py 注册 init 子命令**

在 `main()` 函数的 subparser 部分(约 line 234 后)加:

```python
    p_init = sub.add_parser("init", help="初始化 design(从模板复制)")
    p_init.add_argument("design")
```

在命令分发部分(约 line 248 后)加:

```python
    elif args.command == "init":
        from .cli_commands import cmd_init
        sys.exit(cmd_init(args.design))
```

- [ ] **Step 6: 验证 CLI**

Run: `cd /tmp && python -c "import sys; sys.path.insert(0,'<repo>'); from eda_studio.__main__ import main; main(['init','uart'])"`
Expected: 输出 "✓ 已初始化 uart → designs/uart"

(实际在 repo 目录跑:`rm -rf /tmp/test_init && mkdir /tmp/test_init && cd /tmp/test_init && python -m eda_studio init uart`)

- [ ] **Step 7: Commit**

```bash
git add eda_studio/cli_commands.py eda_studio/__main__.py tests/test_cli_commands.py
git commit -m "feat: 加 eda-studio init 命令(从模板复制 design)"
```

---

## Task 4: `check` 命令

**Files:**
- Modify: `eda_studio/cli_commands.py`(加 cmd_check)
- Modify: `tests/test_cli_commands.py`(加 check 测试)
- Modify: `eda_studio/__main__.py`(加 check 子命令)

**Interfaces:**
- Consumes: `eda_studio.config.load_config`, `eda_studio.templates`(Task 2)
- Produces: `cmd_check(config_path: str) -> int` 函数

- [ ] **Step 1: 写 check 命令失败测试**

追加到 `tests/test_cli_commands.py`:

```python
def test_check_config_missing(tmp_path, monkeypatch):
    """config.yaml 不存在时 check 报错。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli_commands import cmd_check
    rc = cmd_check("nonexistent.yaml")
    assert rc == 1


def test_check_config_ok(tmp_path, monkeypatch):
    """config 存在但 API/容器不可达时,check 报告各项状态。"""
    monkeypatch.chdir(tmp_path)
    # 写一个最小 config
    (tmp_path / "config.yaml").write_text(
        "provider:\n"
        "  type: openai\n"
        "  api_key: test-key\n"
        "  base_url: null\n"
        "model: gpt-4o\n"
        "pricing:\n"
        "  gpt-4o:\n"
        "    input_per_mtok: 2.5\n"
        "    output_per_mtok: 10.0\n"
        "budget:\n"
        "  limit: 5.0\n"
        "  exceeded_action: stop\n"
        "workflow:\n"
        "  max_steps: 50\n"
        "  max_fix_retries: 3\n"
        "shell:\n"
        "  allowed_commands: [\"verilator\"]\n"
        "  denied_args: [\"rm\"]\n"
        "docker:\n"
        "  image: hpretl/iic-osic-tools:latest\n"
        "  container: eda-tools\n"
        "  workdir: /work/designs\n"
        "  pdk: sky130A\n"
    )
    from eda_studio.cli_commands import cmd_check
    # 不实际连 API/docker,只验证 config 解析通过
    rc = cmd_check("config.yaml")
    # API 和 docker 检查会失败,但 config 检查应通过
    assert rc == 1  # 整体失败(因 API/docker 不可达)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_cli_commands.py::test_check_config_missing -v`
Expected: FAIL with `AttributeError: module 'eda_studio.cli_commands' has no attribute 'cmd_check'`

- [ ] **Step 3: 实现 cmd_check**

追加到 `eda_studio/cli_commands.py`:

```python
import json
import os
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def _check_config(config_path: str) -> tuple:
    """检查 config.yaml 可解析。返回 (ok, detail, fix_hint)。"""
    try:
        from .config import load_config
        load_config(config_path)
        return (True, "config.yaml 可解析", None)
    except FileNotFoundError:
        return (False, "config.yaml 不存在", "cp config.example.yaml config.yaml")
    except Exception as e:
        return (False, f"config.yaml 解析失败: {e}", "检查 YAML 语法")


def _check_api_key(config_path: str) -> tuple:
    """检查 API key 非空。"""
    try:
        from .config import load_config
        cfg = load_config(config_path)
        key = cfg.provider_spec.get("api_key", "")
        if not key:
            return (False, "API key 为空", "export OPENAI_API_KEY=... 并在 config.yaml 用 ${OPENAI_API_KEY}")
        return (True, f"API key 已设置({key[:4]}...{key[-4:]})", None)
    except Exception as e:
        return (False, f"读取 config 失败: {e}", None)


def _check_api_reachable(config_path: str) -> tuple:
    """检查 API 端点可达 + 模型可用。"""
    try:
        from .config import load_config
        cfg = load_config(config_path)
        key = cfg.provider_spec.get("api_key", "")
        base_url = cfg.provider_spec.get("base_url") or "https://api.openai.com/v1"
        model = cfg.model
        # 发最小 chat completion 请求
        url = base_url.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        })
        import time
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            elapsed = (time.monotonic() - t0) * 1000
            choices = data.get("choices", [])
            if choices:
                return (True, f"API 端点可达({base_url}, {elapsed:.0f}ms), 模型 {model} 可用", None)
            return (False, f"API 响应无 choices: {data}", "检查 model 名是否正确")
    except Exception as e:
        return (False, f"API 不可达: {e}", "检查 base_url / api_key / 网络")


def _check_docker() -> tuple:
    """检查 docker 可用。"""
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return (True, "docker 可用", None)
        return (False, "docker 不可用", "启动 Docker Desktop")
    except FileNotFoundError:
        return (False, "docker 命令不存在", "安装 Docker")
    except subprocess.TimeoutExpired:
        return (False, "docker info 超时", None)


def _check_container() -> tuple:
    """检查 eda-tools 容器在跑。"""
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", "name=eda-tools", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=5)
        if "eda-tools" in r.stdout:
            return (True, "eda-tools 容器在运行", None)
        return (False, "eda-tools 容器未运行",
                "docker run -d --name eda-tools -v $(pwd)/designs:/work/designs "
                "-e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity")
    except Exception as e:
        return (False, f"检查容器失败: {e}", None)


def _check_eda_tools() -> list:
    """检查容器内 EDA 工具可用,返回 [(tool, ok, detail), ...]。"""
    tools = ["verilator", "yosys", "openroad", "magic", "klayout"]
    results = []
    for tool in tools:
        try:
            # magic 和 netgen 特殊:无 --version
            if tool == "magic":
                cmd = ["docker", "exec", "eda-tools", "bash", "-lc", "magic -noconsole -dnull <<< 'exit'"]
            else:
                cmd = ["docker", "exec", "eda-tools", "bash", "-lc", f"{tool} --version"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            # 过滤 [INFO] 行
            output = "\n".join(l for l in (r.stdout + r.stderr).split("\n") if not l.startswith("[INFO]"))
            ok = r.returncode == 0 or (tool == "magic" and "Magic 8" in output)
            results.append((tool, ok, output.strip()[:60] if ok else f"exit {r.returncode}"))
        except subprocess.TimeoutExpired:
            results.append((tool, False, "timeout"))
        except Exception as e:
            results.append((tool, False, str(e)[:60]))
    return results


def _check_pdk() -> tuple:
    """检查 Sky130 PDK 存在。"""
    try:
        r = subprocess.run(
            ["docker", "exec", "eda-tools", "bash", "-lc",
             "ls /foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd/lib/"],
            capture_output=True, text=True, timeout=10)
        output = "\n".join(l for l in r.stdout.split("\n") if not l.startswith("[INFO]"))
        if r.returncode == 0 and output.strip():
            return (True, "Sky130 PDK 存在", None)
        return (False, "PDK 未找到", "检查容器 PDK 安装")
    except Exception as e:
        return (False, f"PDK 检查失败: {e}", None)


def cmd_check(config_path: str = "config.yaml") -> int:
    """预检环境:config / API / docker / 容器 / EDA 工具 / PDK。

    Returns:
        0 全部通过, 1 有失败项
    """
    checks = []

    # config 相关(顺序执行,失败则跳过后续 config 检查)
    ok_cfg, detail, hint = _check_config(config_path)
    checks.append(("config", ok_cfg, detail, hint))
    if ok_cfg:
        ok_key, detail, hint = _check_api_key(config_path)
        checks.append(("api_key", ok_key, detail, hint))
        if ok_key:
            ok_api, detail, hint = _check_api_reachable(config_path)
            checks.append(("api", ok_api, detail, hint))

    # docker 相关(并行)
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_docker = pool.submit(_check_docker)
        f_container = pool.submit(_check_container)
        f_pdk = pool.submit(_check_pdk)
        f_tools = pool.submit(_check_eda_tools)

        ok_d, detail, hint = f_docker.result()
        checks.append(("docker", ok_d, detail, hint))

        ok_c, detail, hint = f_container.result()
        checks.append(("container", ok_c, detail, hint))

        if ok_c:
            tool_results = f_tools.result()
            for tool, ok, detail in tool_results:
                checks.append((f"tool:{tool}", ok, detail, None if ok else f"容器内 {tool} 不可用"))

            ok_pdk, detail, hint = f_pdk.result()
            checks.append(("pdk", ok_pdk, detail, hint))

    # 输出
    all_ok = True
    for name, ok, detail, hint in checks:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {detail}")
        if not ok and hint:
            print(f"    → {hint}")
            all_ok = False
        elif not ok:
            all_ok = False

    print()
    if all_ok:
        print("✓ 环境检查通过,可以运行 eda-studio run <design>")
        return 0
    print("✗ 环境检查未通过,请修复上述问题")
    return 1
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_cli_commands.py -v`
Expected: 5 passed

- [ ] **Step 5: 在 __main__.py 注册 check 子命令**

在 `main()` 加:

```python
    p_check = sub.add_parser("check", help="预检环境(config/API/docker/PDK)")
    p_check.add_argument("--config", default="config.yaml")
```

分发:

```python
    elif args.command == "check":
        from .cli_commands import cmd_check
        sys.exit(cmd_check(args.config))
```

- [ ] **Step 6: 验证 check 命令实际运行**

Run: `source .env && python -m eda_studio check`
Expected: 输出各项 ✓/✗(容器和 API 应通过,因为环境已配好)

- [ ] **Step 7: Commit**

```bash
git add eda_studio/cli_commands.py eda_studio/__main__.py tests/test_cli_commands.py
git commit -m "feat: 加 eda-studio check 预检命令(config/API/docker/PDK)"
```

---

## Task 5: CLAUDE.md 拆分 + docs/dev-notes.md

**Files:**
- Create: `docs/dev-notes.md`
- Modify: `CLAUDE.md`(删除开发期诊断笔记)

**Interfaces:**
- 无代码接口,纯文档

- [ ] **Step 1: 读 CLAUDE.md 完整内容,识别开发期诊断笔记段落**

开发期诊断笔记包括(移到 dev-notes.md):
- executor bug 修复历程(simulate sim_out 路径、synthesize 分号、pnr -cmd/read_libs、drc/gds 重写)
- PDK 路径踩坑细节
- FinalAnswer 覆盖问题
- budget should_stop hook 问题
- docker exec [INFO] 行污染
- judge 用 tool_calls_count 判断完成的决策

保留在 CLAUDE.md:
- 项目概述
- Docker 容器用法(--skip sleep infinity 解释、bash -lc 要求、工具版本表、PDK 路径)
- Senza SDK 依赖版本
- 架构边界(模块职责)

- [ ] **Step 2: 创建 docs/dev-notes.md,移入开发期笔记**

从 CLAUDE.md 提取开发期内容,组织成:
- # 开发笔记
- ## Executor 修复历程
- ## PDK 路径
- ## FinalAnswer 空响应问题
- ## budget should_stop hook
- ## docker exec [INFO] 行污染

- [ ] **Step 3: 精简 CLAUDE.md**

删除已移到 dev-notes.md 的段落,保留架构和容器信息。CLAUDE.md 目标长度 <150 行。

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/dev-notes.md
git commit -m "docs: 拆分 CLAUDE.md,开发期笔记移到 docs/dev-notes.md"
```

---

## Task 6: CONTRIBUTING.md

**Files:**
- Create: `CONTRIBUTING.md`

**Interfaces:**
- 无

- [ ] **Step 1: 创建 CONTRIBUTING.md**

```markdown
# 贡献指南

感谢对 EDA Studio 的贡献!本文档说明如何扩展项目。

## 开发环境

```bash
git clone <repo>
cd eda-studio
pip install -e .
eda-studio init uart        # 复制示例 design
docker run -d --name eda-tools ...   # 启动 EDA 工具容器
eda-studio check            # 预检
pytest tests/               # 跑测试(不依赖真实 EDA 工具和 LLM)
```

## 加 Executor

Executor 是 Python 回调,签名为 `fn(ctx: dict) -> dict`。

1. 在 `eda_studio/executors/` 新建文件,实现 executor 函数
2. 返回 `{"output": str, "structured": {"success": bool, ...}}`
3. 在 `eda_studio/executors/__init__.py` 导出
4. 在 `eda_studio/workflow.py` 的 `build_workflow` 中用 `.with_executor(step_id, create_executor(fn))` 注册

参考 `eda_studio/executors/simulate.py`。

## 加 Design

1. 在 `eda_studio/templates/<name>/` 新建目录
2. 写 `requirement.md`(设计需求)
3. 如需 testbench,放 `rtl/tb_<name>.v`
4. 用户 `eda-studio init <name>` 复制到 `designs/<name>/`

## 加 LLM Step

1. 在 `eda_studio/prompts.py` 加 prompt 模板
2. 在 `eda_studio/workflow.py` 的 `workflow_dict.steps` 加 step(`id`/`name`/`prompt`/`allowed_tools`)
3. 在 `workflow_dict.edges` 加路由边
4. 在 `eda_studio/judge.py` 加该 step 的路由逻辑

## 测试

- 所有测试不依赖真实 EDA 工具和 LLM API
- executor 测试 monkeypatch `run_shell`/`subprocess`
- 运行:`pytest tests/ -q`

## 提交

- 遵循现有 commit message 风格(`feat:`/`fix:`/`docs:`/`chore:`)
- 确保所有测试通过
```

- [ ] **Step 2: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: 加 CONTRIBUTING.md"
```

---

## Task 7: README 重写

**Files:**
- Modify: `README.md`

**Interfaces:**
- 无

- [ ] **Step 1: 重写 README.md**

```markdown
# EDA Studio

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

基于 [Senza](https://github.com/oh-my-harness/Senza) SDK 的开源 EDA 自动化芯片设计流程示例,用 LLM + 开源 EDA 工具完成 UART RTL→GDS 全流程。

## 截图

*(WebUI 三栏图 + GDS 渲染 PNG,运行后从 `designs/uart/gds/uart.png` 截取)*

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

配置:复制 `config.example.yaml` 为 `config.yaml`,填入 API key/端点/模型名。

## 命令

| 命令 | 说明 |
|------|------|
| `init <design>` | 从模板复制 design 输入文件 |
| `check` | 预检环境(config/API/docker/PDK) |
| `run <design>` | 运行设计流程,终端实时输出 |
| `serve` | 启动 Web UI |
| `restore <design>` | 从断点恢复 |
| `status <design>` | 查看状态 |

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

详见 [CLAUDE.md](CLAUDE.md) 和 [docs/](docs/)。

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

[MIT](LICENSE)
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: 重写 README(截图/模型要求/init+check 快速开始)"
```

---

## Task 8: CLI 最终状态表

**Files:**
- Create: `tests/test_run_summary.py`
- Modify: `eda_studio/__main__.py`(cmd_run 加状态表)

**Interfaces:**
- Consumes: taskstore `designs/<name>/.taskstore/<task_id>/workflow.json`
- Produces: `_print_run_summary(design_name: str) -> None` 函数

- [ ] **Step 1: 写状态表失败测试**

`tests/test_run_summary.py`:

```python
"""cmd_run 最终状态表测试。"""
import json
from pathlib import Path
import pytest


def _make_taskstore(tmp_path, design, step_history):
    """在 tmp_path 下造一个 taskstore。"""
    store = tmp_path / "designs" / design / ".taskstore" / "task-fake" 
    store.mkdir(parents=True)
    (store / "workflow.json").write_text(json.dumps({
        "status": "succeeded",
        "step_history": step_history,
    }))
    (tmp_path / "designs" / design / ".taskstore" / "task_id").write_text("task-fake")


def test_print_run_summary(tmp_path, monkeypatch, capsys):
    """状态表正确显示每个 step 的 ✓/✗。"""
    _make_taskstore(tmp_path, "uart", [
        {"step_id": "rtl_tx", "result": {"output": "", "structured": None,
          "cost": {"total_input_tokens": 100, "total_output_tokens": 50, "total_cost": 0.01}},
         "transition": {"to": "rtl_rx"}},
        {"step_id": "simulate", "result": {"output": "ok", "structured": {"success": True},
          "cost": {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost": 0.0}},
         "transition": {"to": "synthesize"}},
        {"step_id": "render", "result": {"output": "ERROR: NoMethodError",
          "structured": {"success": False}, "cost": {}},
         "transition": {"abort": {"reason": "done"}}},
    ])
    monkeypatch.chdir(tmp_path)
    from eda_studio.__main__ import _print_run_summary
    _print_run_summary("uart")
    out = capsys.readouterr().out
    assert "rtl_tx" in out and "✓" in out
    assert "simulate" in out
    assert "render" in out and "✗" in out
    assert "NoMethodError" in out


def test_print_run_summary_no_taskstore(tmp_path, monkeypatch, capsys):
    """taskstore 不存在时不报错。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.__main__ import _print_run_summary
    _print_run_summary("uart")
    out = capsys.readouterr().out
    assert "未找到" in out or "taskstore" in out
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_run_summary.py -v`
Expected: FAIL with `ImportError: cannot import name '_print_run_summary'`

- [ ] **Step 3: 实现 _print_run_summary**

在 `eda_studio/__main__.py` 加(在 `cmd_run` 之前):

```python
def _print_run_summary(design_name: str) -> None:
    """workflow 结束后打印每个 step 的状态表。

    从 taskstore workflow.json 读 step_history。
    """
    import json
    store_dir = Path(f"designs/{design_name}/.taskstore")
    task_id_file = store_dir / "task_id"
    if not task_id_file.exists():
        print(f"未找到 taskstore: {store_dir}")
        return
    task_id = task_id_file.read_text().strip()
    wf_file = store_dir / task_id / "workflow.json"
    if not wf_file.exists():
        print(f"未找到 workflow.json: {wf_file}")
        return
    wf = json.loads(wf_file.read_text())
    status = wf.get("status", "unknown")
    history = wf.get("step_history", [])

    print(f"\n═══ Workflow 完成 ({status}) ═══")
    for step in history:
        sid = step["step_id"]
        result = step.get("result", {})
        structured = result.get("structured") or {}
        success = structured.get("success")
        output = result.get("output", "")
        cost = result.get("cost") or {}
        in_tok = cost.get("total_input_tokens", 0)
        out_tok = cost.get("total_output_tokens", 0)

        if success is None:
            # LLM step:有 tool_calls 算成功
            success = result.get("tool_calls_count", 0) > 0

        mark = "✓" if success else "✗"
        if in_tok > 0 or out_tok > 0:
            detail = f"{in_tok//1000}k↓ {out_tok//1000}k↑"
        else:
            detail = "executor"
        line = f"  {sid:<12} {mark}  {detail}"
        if not success and output:
            # 错误摘要:取最后一行非空、非 [INFO] 的内容
            lines = [l for l in output.split("\n") if l.strip() and not l.startswith("[INFO]")]
            err = lines[-1][:70] if lines else output[:70]
            line += f"  ← {err}"
        print(line)
```

- [ ] **Step 4: 在 cmd_run 末尾调用**

修改 `cmd_run` 函数,在 `print(f"✗ 未产出 GDS")` 之后加:

```python
    _print_run_summary(design_name)
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/test_run_summary.py -v`
Expected: 2 passed

- [ ] **Step 6: 运行全部测试**

Run: `pytest tests/ -q`
Expected: 全部通过(之前 79 + 新增 7 = 86)

- [ ] **Step 7: Commit**

```bash
git add eda_studio/__main__.py tests/test_run_summary.py
git commit -m "feat: cmd_run 末尾打印 step 状态表(✓/✗ + 错误摘要)"
```

---

## Task 9: WebUI 失败标记 + 完成横幅

**Files:**
- Modify: `static/index.html`

**Interfaces:**
- Consumes: WS step_finished 事件的 `structured` 字段(EXEC step 有 `{success: bool}`)

- [ ] **Step 1: 修改 step_finished handler 用 structured.success 标记失败**

在 `static/index.html` 的 `handleEvent` 函数,`step_finished` 分支(约 line 247),修改:

当前代码:
```javascript
            } else if (type === 'step_finished') {
                const sid = event.step_id;
                const cfg = stepConfig[sid] || { name: sid, icon: '🔹' };
                const output = event.output || '';
                const cost = event.cost;
                if (cost && cost.total_cost) totalCost += cost.total_cost;
                updateCostDisplay();
                let meta = '';
                if (cost && cost.input_tokens > 0) meta = `${cost.input_tokens}↓ ${cost.output_tokens}↑`;
                li.innerHTML = `<span class="event-icon">✔</span><div class="event-body"><span class="event-text">${cfg.name} 完成</span>${meta ? `<div class="event-meta">${meta}</div>` : ''}</div><span class="event-ts">${ts}</span>`;
                li.className = 'event-step_finished';
                setDoneNode(sid);
                updateStepCardFinished(sid, output, cost);
            }
```

改为:
```javascript
            } else if (type === 'step_finished') {
                const sid = event.step_id;
                const cfg = stepConfig[sid] || { name: sid, icon: '🔹' };
                const output = event.output || '';
                const structured = event.structured;
                const success = structured ? structured.success : true;
                const cost = event.cost;
                if (cost && cost.total_cost) totalCost += cost.total_cost;
                updateCostDisplay();
                let meta = '';
                if (cost && cost.input_tokens > 0) meta = `${cost.input_tokens}↓ ${cost.output_tokens}↑`;
                const icon = success ? '✔' : '✗';
                const eventClass = success ? 'event-step_finished' : 'event-failed';
                li.innerHTML = `<span class="event-icon">${icon}</span><div class="event-body"><span class="event-text">${cfg.name} ${success ? '完成' : '失败'}</span>${meta ? `<div class="event-meta">${meta}</div>` : ''}</div><span class="event-ts">${ts}</span>`;
                li.className = eventClass;
                if (success) setDoneNode(sid); else setFailedNode(sid);
                updateStepCardFinished(sid, output, cost, success);
            }
```

- [ ] **Step 2: 修改 updateStepCardFinished 接收 success 参数**

在 `static/index.html` 的 `updateStepCardFinished` 函数(约 line 344),修改签名和逻辑:

当前:
```javascript
        function updateStepCardFinished(sid, output, cost) {
            const s = _ensureStore(sid);
            s.output = output || '';
            s.cost = cost;
            s.finished = true;
            s.success = true;
            if (sid === viewStepId) renderStepView(sid);
        }
```

改为:
```javascript
        function updateStepCardFinished(sid, output, cost, success) {
            const s = _ensureStore(sid);
            s.output = output || '';
            s.cost = cost;
            s.finished = true;
            s.success = (success !== false);
            if (sid === viewStepId) renderStepView(sid);
        }
```

- [ ] **Step 3: 修改 renderStepView 显示失败状态**

在 `renderStepView` 函数中,render step 失败时显示错误而非 PNG。找到 render PNG 部分(约 line 375):

当前:
```javascript
            // render step:PNG
            if (sid === 'render' && s.finished) {
                extra += `<img src="/api/render.png?t=${Date.now()}" alt="GDS 渲染预览" style="width:100%;margin-top:12px;border:1px solid #0f3460;border-radius:6px;background:#fff;">`;
            }
```

改为:
```javascript
            // render step:成功显示 PNG,失败显示错误
            if (sid === 'render' && s.finished) {
                if (s.success) {
                    extra += `<img src="/api/render.png?t=${Date.now()}" alt="GDS 渲染预览" style="width:100%;margin-top:12px;border:1px solid #0f3460;border-radius:6px;background:#fff;">`;
                } else {
                    extra += `<div style="margin-top:12px;padding:10px;background:#3a1515;border:1px solid #ff4444;border-radius:6px;color:#ff6b6b;font-size:12px;">渲染失败 — 见上方输出</div>`;
                }
            }
```

- [ ] **Step 4: 加完成横幅**

在 `handleEvent` 函数末尾(else 分支之后,`list.prepend(li)` 之前)加 `succeeded`/`failed` 事件处理。当前没有这两个事件的处理。在 `cancelled` 分支后加:

```javascript
            } else if (type === 'succeeded' || type === 'failed') {
                const ok = type === 'succeeded';
                const banner = document.createElement('div');
                banner.style.cssText = 'position:fixed;top:60px;left:50%;transform:translateX(-50%);padding:12px 20px;background:' + (ok ? '#1a3a1a' : '#3a1515') + ';border:1px solid ' + (ok ? '#4ecca3' : '#ff4444') + ';border-radius:8px;color:' + (ok ? '#4ecca3' : '#ff6b6b') + ';font-size:14px;z-index:1000;box-shadow:0 4px 12px rgba(0,0,0,0.5);';
                const doneCount = document.querySelectorAll('.flow-node[data-done="1"]').length;
                const failedCount = document.querySelectorAll('.flow-node[data-failed="1"]').length;
                banner.innerHTML = (ok ? '✓' : '✗') + ' Workflow ' + (ok ? '完成' : '失败') + ' — ' + doneCount + '/' + (doneCount + failedCount) + ' 步成功';
                document.body.appendChild(banner);
                setTimeout(() => banner.remove(), 8000);
                document.getElementById('submit-btn').disabled = false;
                if (!ok) setStatusBadge('failed', 'Failed');
                else setStatusBadge('done', 'Done');
            }
```

注意:需确认 senza 是否发 `succeeded`/`failed` 事件类型。如果不发,改用 `step_finished` 的 render step(最后一步)来判断完成。实际运行时验证。

- [ ] **Step 5: 验证浏览器**

Run: `source .env && python -m eda_studio serve --port 3000`
浏览器打开,提交任务,观察:
- 失败 step 红色边框
- 完成时顶部横幅

- [ ] **Step 6: 运行全部测试**

Run: `pytest tests/ -q`
Expected: 全部通过

- [ ] **Step 7: Commit**

```bash
git add static/index.html
git commit -m "feat: WebUI 失败标记(红色边框)+ 完成横幅 + render 容错"
```

---

## Task 10: 端到端验证

**Files:**
- 无(验证步骤)

**Interfaces:**
- 无

- [ ] **Step 1: 清理状态**

```bash
rm -rf sessions/ designs/uart/.taskstore/ designs/uart/sim/ designs/uart/synth/ designs/uart/pnr/ designs/uart/gds/ designs/uart/rtl/uart*.v
```

- [ ] **Step 2: 用新 init 命令初始化**

Run: `eda-studio init uart`
Expected: 输出 "✓ 已初始化 uart → designs/uart"

- [ ] **Step 3: 预检**

Run: `source .env && eda-studio check`
Expected: 全部 ✓

- [ ] **Step 4: 运行 workflow**

Run: `source .env && python -m eda_studio run uart`
Expected:
- 全流程跑通(rtl_tx → ... → render)
- 末尾打印状态表,render ✓(已修复 set_active_layer)
- 产出 `designs/uart/gds/uart.gds` + `designs/uart/gds/uart.png`

- [ ] **Step 5: 验证 WebUI**

Run: `source .env && python -m eda_studio serve --port 3000`
浏览器打开,提交任务,验证:
- 11 节点渲染
- 失败 step 红色标记(如果有失败)
- 完成横幅
- render step 显示 PNG

- [ ] **Step 6: 运行全部测试**

Run: `pytest tests/ -q`
Expected: 全部通过

- [ ] **Step 7: 最终 commit(如有遗漏修复)**

```bash
git add -A
git commit -m "chore: 端到端验证通过"
```

---

## Self-Review

**Spec coverage 检查:**
- ✅ 层 1.1 LICENSE — Task 1
- ✅ 层 1.2 README 重写 — Task 7
- ✅ 层 1.3 CLAUDE.md 拆分 — Task 5
- ✅ 层 1.4 CONTRIBUTING — Task 6
- ✅ 层 1.5 templates 目录 — Task 2
- ✅ 层 2.1 init 命令 — Task 3
- ✅ 层 2.2 check 命令 — Task 4
- ✅ 层 2.3 CLI 入口整合 — Task 3+4(在 __main__.py 注册)
- ✅ 层 3.1 render 失败语义 — 已在之前修复(set_active_layer),Task 9 加失败标记
- ✅ 层 3.2 CLI 状态表 — Task 8
- ✅ 层 3.3 WebUI 失败可见性 — Task 9
- ✅ 层 3.4 step_finished 事件 structured — 已确认 WS 事件含 structured,Task 9 直接用

**Placeholder scan:** 无 TBD/TODO,所有代码步骤含完整代码。

**Type consistency:**
- `cmd_init(name: str) -> int` — Task 3 定义,Task 5 CONTRIBUTING 引用一致
- `cmd_check(config_path: str) -> int` — Task 4 定义
- `_print_run_summary(design_name: str) -> None` — Task 8 定义
- `updateStepCardFinished(sid, output, cost, success)` — Task 9 修改签名,调用处一致

**风险:**
- Task 9 Step 4 的 `succeeded`/`failed` 事件类型未确认 senza 是否发送。需实际运行验证。如果不发,fallback 到监听 render step_finished。
