# Session 隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** eda-studio 侧把 `session_base_dir` 传给 `WorkflowEngine`(run + restore 两处),值由环境变量 `EDA_STUDIO_SESSION_DIR` 决定(默认 `sessions`),配合上游 runtime issue [#73](https://github.com/oh-my-harness/llm-harness-runtime/issues/73) 实现 session 按 `task_id / step_id-attempt` 隔离。

**Architecture:** 新增 `_session_base_dir()` helper 读环境变量;`build_workflow` 和 `cmd_restore` 两处 `WorkflowEngine` 构造点传 `session_base_dir=` 参数。serve 路径经 `build_workflow` 自动继承,无需改。测试用 mock provider,不跑真实 LLM。

**Tech Stack:** Python 3.12, senza-sdk 0.4.8+, pytest

## Global Constraints

- 不修改 Senza / Runtime 源码(上游 issue #73 / #19 由维护者推进)
- eda-studio 侧改动必须等上游 runtime #73 合入并发布新 senza-sdk 后才能真实生效(当前 senza-sdk 仍硬编码 `sub-agents/`);但 eda-studio 代码改动本身可先做,不影响现有行为(传参只是覆盖默认值 `"sessions"`,与现状等价)
- 环境变量名:`EDA_STUDIO_SESSION_DIR`,默认值 `"sessions"`
- helper 放在 `eda_studio/workflow.py`(与 `build_workflow` 同文件,就近原则)
- 不引入 `<design>/` 子目录
- 不迁移历史 session
- 不改 `.taskstore` 路径

---

### Task 1: 新增 `_session_base_dir()` helper

**Files:**
- Modify: `eda_studio/workflow.py:12`(在 `from dataclasses import asdict` 之后加 `import os`)
- Modify: `eda_studio/workflow.py:31-32`(在 imports 块结尾 `)` 和 `def build_providers` 之间插入 helper)
- Test: `tests/test_workflow.py`(文件末尾追加 3 个测试)

**Interfaces:**
- Produces: `_session_base_dir() -> str` — 读 `EDA_STUDIO_SESSION_DIR` 环境变量,缺省或空字符串返回 `"sessions"`。纯函数,无副作用。

- [ ] **Step 1: Write the failing test**

在 `tests/test_workflow.py` 末尾追加:

```python
def test_session_base_dir_default(monkeypatch):
    """未设环境变量时返回默认 'sessions'。"""
    monkeypatch.delenv("EDA_STUDIO_SESSION_DIR", raising=False)
    from eda_studio.workflow import _session_base_dir
    assert _session_base_dir() == "sessions"


def test_session_base_dir_env_override(monkeypatch):
    """环境变量覆盖生效。"""
    monkeypatch.setenv("EDA_STUDIO_SESSION_DIR", "/tmp/foo")
    from eda_studio.workflow import _session_base_dir
    assert _session_base_dir() == "/tmp/foo"


def test_session_base_dir_empty_env_falls_back(monkeypatch):
    """环境变量设为空字符串时回退到默认值(空字符串视为未设)。"""
    monkeypatch.setenv("EDA_STUDIO_SESSION_DIR", "")
    from eda_studio.workflow import _session_base_dir
    assert _session_base_dir() == "sessions"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow.py::test_session_base_dir_default tests/test_workflow.py::test_session_base_dir_env_override tests/test_workflow.py::test_session_base_dir_empty_env_falls_back -v`
Expected: FAIL with `ImportError: cannot import name '_session_base_dir' from 'eda_studio.workflow'`

- [ ] **Step 3: Write minimal implementation**

在 `eda_studio/workflow.py` 第 12 行(`from dataclasses import asdict`)之后新起一行插入:

```python
import os
```

在 imports 块之后(第 31 行 `)` 之后,空一行,在 `def build_providers` 之前)插入:

```python


def _session_base_dir() -> str:
    """session 根目录。默认 'sessions'(仓库根),可通过环境变量覆盖。

    空字符串视为未设,回退到默认值。
    """
    val = os.environ.get("EDA_STUDIO_SESSION_DIR")
    return val if val else "sessions"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow.py::test_session_base_dir_default tests/test_workflow.py::test_session_base_dir_env_override tests/test_workflow.py::test_session_base_dir_empty_env_falls_back -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add eda_studio/workflow.py tests/test_workflow.py
git commit -m "feat: add _session_base_dir() helper for issue #4"
```

---

### Task 2: `build_workflow` 传 `session_base_dir`

**Files:**
- Modify: `eda_studio/workflow.py:177-179`(`WorkflowEngine(...)` 构造调用)
- Test: `tests/test_workflow.py`(新增 1 个回归保险测试)

**Interfaces:**
- Consumes: `_session_base_dir()` from Task 1
- Produces: `build_workflow` 构造的 `WorkflowEngine` 实例在内部记录了 `session_base_dir`(runtime 字段,Python 侧不暴露,无法直接断言传入值;只能通过"构造不抛异常"回归保险)

**注:** 本任务新增的是回归保险测试,不是红绿 TDD——因为 runtime 不暴露内部 `session_base_dir` 字段,无法直接断言。测试目的是确保加参数后构造仍正常。

- [ ] **Step 1: Write the test**

在 `tests/test_workflow.py` 末尾追加:

```python
def test_build_workflow_with_custom_session_dir(tmp_path, monkeypatch):
    """环境变量设自定义 session 根目录时,build_workflow 仍能正常构造。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EDA_STUDIO_SESSION_DIR", str(tmp_path / "custom_sessions"))
    (tmp_path / "config.yaml").write_text(CFG_YAML)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    config = load_config(str(tmp_path / "config.yaml"))
    engine = build_workflow(config, "uart")
    assert engine is not None
    assert hasattr(engine, "run")
```

- [ ] **Step 2: Run test to verify baseline**

Run: `pytest tests/test_workflow.py::test_build_workflow_with_custom_session_dir -v`
Expected: PASS(当前 `build_workflow` 不传 `session_base_dir`,runtime 用默认 `"sessions"`,engine 仍能构造)。此步只是确认基线绿,改动后仍应绿。

- [ ] **Step 3: Write minimal implementation**

在 `eda_studio/workflow.py:177-179` 把:

```python
    engine = WorkflowEngine(
        workflow_dict, provider, config.model, judge, env=env,
    )
```

改为:

```python
    engine = WorkflowEngine(
        workflow_dict, provider, config.model, judge, env=env,
        session_base_dir=_session_base_dir(),
    )
```

- [ ] **Step 4: Run all workflow tests to verify still pass**

Run: `pytest tests/test_workflow.py -v`
Expected: PASS (所有 test_workflow.py 测试:原有 2 个 + Task 1 的 3 个 + 本任务 1 个 = 6 个)

- [ ] **Step 5: Commit**

```bash
git add eda_studio/workflow.py tests/test_workflow.py
git commit -m "feat: build_workflow 传 session_base_dir (issue #4)"
```

---

### Task 3: `cmd_restore` 传 `session_base_dir`

**Files:**
- Modify: `eda_studio/cli.py:43`(扩展 import)
- Modify: `eda_studio/cli.py:224-230`(`WorkflowEngine.restore(...)` 构造调用)
- Test: `tests/test_cli_commands.py`(末尾追加 1 个测试)

**Interfaces:**
- Consumes: `_session_base_dir()` from Task 1 (需在 `cli.py` import)
- Produces: `cmd_restore` 在 restore 时传与 `build_workflow` 相同的 `session_base_dir`,保证 restore 路径一致性

- [ ] **Step 1: Write the failing test**

在 `tests/test_cli_commands.py` 末尾追加:

```python
def test_cmd_restore_passes_session_base_dir(tmp_path, monkeypatch):
    """cmd_restore 构造 engine 时传了 session_base_dir(通过环境变量覆盖验证)。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EDA_STUDIO_SESSION_DIR", str(tmp_path / "rsessions"))
    (tmp_path / "config.yaml").write_text(
        "provider:\n"
        "  type: openai\n"
        "  api_key: sk-test\n"
        "  base_url: http://127.0.0.1:1\n"
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
        "  image: img\n"
        "  container: eda-tools\n"
        "  workdir: /work/designs\n"
        "  pdk: sky130A\n"
    )
    # 造一个 uart design 目录 + taskstore task_id
    uart_dir = tmp_path / "designs" / "uart"
    uart_dir.mkdir(parents=True)
    store_dir = uart_dir / ".taskstore"
    store_dir.mkdir()
    (store_dir / "task_id").write_text("task-test-id-1234")
    # mock WorkflowEngine.restore,验证 session_base_dir 传入
    from unittest.mock import patch, MagicMock
    with patch("eda_studio.cli.WorkflowEngine") as MockEngine:
        mock_engine = MagicMock()
        mock_engine.current_step.return_value = "rtl_tx"
        mock_engine.step_history.return_value = []
        mock_engine.state.return_value = "paused"
        MockEngine.restore.return_value = mock_engine
        with patch("eda_studio.cli._re_register", side_effect=lambda eng, *a, **k: eng):
            try:
                from eda_studio.cli import cmd_restore
                cmd_restore("uart", str(tmp_path / "config.yaml"))
            except SystemExit:
                pass
            except Exception:
                pass
            assert MockEngine.restore.called, "WorkflowEngine.restore 未被调用"
            _, kwargs = MockEngine.restore.call_args
            assert "session_base_dir" in kwargs, "session_base_dir 未传"
            assert kwargs["session_base_dir"] == str(tmp_path / "rsessions"), \
                f"期望 {tmp_path / 'rsessions'},实际 {kwargs.get('session_base_dir')}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_commands.py::test_cmd_restore_passes_session_base_dir -v`
Expected: FAIL with `AssertionError: session_base_dir 未传`(因为当前 `cmd_restore` 不传 `session_base_dir`)

- [ ] **Step 3: Write minimal implementation**

**3a. 扩展 import**

在 `eda_studio/cli.py:43` 把:

```python
from .workflow import build_workflow, build_providers
```

改为:

```python
from .workflow import build_workflow, build_providers, _session_base_dir
```

**3b. `WorkflowEngine.restore` 调用加参数**

在 `eda_studio/cli.py:224-230` 把:

```python
    engine = WorkflowEngine.restore(
        store_dir, task_id,
        provider=provider,
        model=config.model,
        judge=create_judge(make_judge_fn(config, rtl_ids=dcfg.rtl_step_ids)),
        env=env,
    )
```

改为:

```python
    engine = WorkflowEngine.restore(
        store_dir, task_id,
        provider=provider,
        model=config.model,
        judge=create_judge(make_judge_fn(config, rtl_ids=dcfg.rtl_step_ids)),
        env=env,
        session_base_dir=_session_base_dir(),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_commands.py::test_cmd_restore_passes_session_base_dir -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regression**

Run: `pytest tests/ -v`
Expected: PASS (所有测试通过)

- [ ] **Step 6: Commit**

```bash
git add eda_studio/cli.py tests/test_cli_commands.py
git commit -m "feat: cmd_restore 传 session_base_dir (issue #4)"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ 环境变量 `EDA_STUDIO_SESSION_DIR` 默认 `sessions` → Task 1 helper
- ✅ `build_workflow` 传 `session_base_dir` → Task 2
- ✅ `cmd_restore` 传 `session_base_dir` → Task 3
- ✅ serve 路径(`_workflow_runner`)经 `build_workflow` 自动继承 → spec 已说明无需改,无需任务
- ✅ restore 一致性(两处同读一环境变量) → Task 2 + Task 3 共同保证
- ✅ 历史 session 不迁移 → Global Constraints 声明
- ✅ 不引入 `<design>/` 子目录 → Global Constraints 声明
- ✅ runtime / Senza 改动由上游 issue 推进 → Global Constraints 声明

**2. Placeholder scan:** 无 TODO / TBD / "add appropriate..."。所有代码块完整。

**3. Type consistency:**
- `_session_base_dir() -> str` 在 Task 1 定义,Task 2 / Task 3 调用,签名一致。
- `session_base_dir=_session_base_dir()` 在两处 `WorkflowEngine` 构造点用法一致。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-21-session-isolation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
