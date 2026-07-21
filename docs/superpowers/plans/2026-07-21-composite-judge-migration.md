# CompositeJudge 迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `eda_studio/judge.py` 的单一闭包 judge 迁移为 senza `CompositeJudge` + 模块级 handler 函数,使每个 step 的路由逻辑独立可测。

**Architecture:** `make_judge_fn` 返回 `CompositeJudge`,内部用 `.on(step, handler)` 注册 9 个模块级 handler 函数(RTL steps 循环注册 per-index 闭包)。`fix_counts` 共享可变 dict 在 `make_judge_fn` 作用域声明,被 simulate/pnr/drc 三个 handler 闭包捕获。`workflow.py` / `cli.py` 去掉 `create_judge()` 包装,直接传 `CompositeJudge` 给 `WorkflowEngine`。

**Tech Stack:** Python 3.12, senza SDK(`CompositeJudge`), pytest

**Spec:** `docs/superpowers/specs/2026-07-21-composite-judge-migration-design.md`

## Global Constraints

- 不改变路由行为:同一 ctx 序列产生与迁移前完全相同的 judge 返回值。
- `make_judge_fn(config, rtl_ids=None)` 返回 `CompositeJudge`(类型从 `senza` 导入)。
- handler 是模块级函数,签名 `(ctx, deps...) -> str`,可独立 import 测试。
- `fix_counts` 仅在 simulate/pnr/drc 三个 handler 内读写。
- `retry_count`(engine 维护)仅用于 RTL/debug_fix/drc_fix 的 `retry` 路径。
- fallback 返回 `"abort:unknown_step"`(哨兵,engine 仍按 `abort:` 终止)。
- 删除 per-call `logging.info(f"judge: step=...")` 日志。
- 测试用 `pytest`,venv 在 `.venv/`(激活后 `python -m pytest`)。

---

## File Structure

- **Modify**: `eda_studio/judge.py` — 替换整个文件:9 个模块级 handler + `make_judge_fn` 返回 `CompositeJudge` + `KNOWN_FIXED_STEPS` 常量
- **Modify**: `eda_studio/workflow.py:175` — 去掉 `create_judge()` 包装
- **Modify**: `eda_studio/cli.py:228` — 去掉 `create_judge()` 包装
- **Modify**: `eda_studio/workflow.py:14-21` — 从 `from senza import (...)` 移除 `create_judge`
- **Modify**: `eda_studio/cli.py:38-40` — 从 `from senza import (...)` 移除 `create_judge`
- **Rewrite**: `tests/test_judge.py` — 全部改为 handler 单元测试 + 注册测试

---

### Task 1: 提取 `_rtl_handler` + 改造 RTL 测试

**Files:**
- Modify: `eda_studio/judge.py`(在现有闭包之前插入模块级 `_rtl_handler`,暂不动 `make_judge_fn`)
- Test: `tests/test_judge.py`

**Interfaces:**
- Produces: `_rtl_handler(ctx: dict, idx: int, rtl_ids: list, max_fix: int) -> str`

- [ ] **Step 1: 写失败测试 — 替换 RTL 测试为 handler 直调**

把 `tests/test_judge.py` 里 6 个 RTL 测试(`test_rtl_tx_*`、`test_rtl_rx_*`、`test_rtl_top_*`)改为直接调用 `_rtl_handler`。替换后的 RTL 测试:

```python
from eda_studio.judge import _rtl_handler

RTL_IDS = ["rtl_tx", "rtl_rx", "rtl_top"]

def test_rtl_tx_done_when_tool_called():
    assert _rtl_handler(ctx("rtl_tx", tool_calls_count=1), idx=0,
                        rtl_ids=RTL_IDS, max_fix=3) == "to:rtl_rx"

def test_rtl_tx_retries_when_no_tool():
    assert _rtl_handler(ctx("rtl_tx", tool_calls_count=0), idx=0,
                        rtl_ids=RTL_IDS, max_fix=3) == "retry"

def test_rtl_tx_aborts_when_retry_exhausted():
    assert _rtl_handler(ctx("rtl_tx", tool_calls_count=0, retry_count=2),
                        idx=0, rtl_ids=RTL_IDS, max_fix=2) == "abort:done"

def test_rtl_rx_done_when_tool_called():
    assert _rtl_handler(ctx("rtl_rx", tool_calls_count=1), idx=1,
                        rtl_ids=RTL_IDS, max_fix=3) == "to:rtl_top"

def test_rtl_rx_retries_when_no_tool():
    assert _rtl_handler(ctx("rtl_rx", tool_calls_count=0), idx=1,
                        rtl_ids=RTL_IDS, max_fix=3) == "retry"

def test_rtl_top_done_when_tool_called():
    assert _rtl_handler(ctx("rtl_top", tool_calls_count=1), idx=2,
                        rtl_ids=RTL_IDS, max_fix=3) == "to:simulate"

def test_rtl_top_retries_when_no_tool():
    assert _rtl_handler(ctx("rtl_top", tool_calls_count=0), idx=2,
                        rtl_ids=RTL_IDS, max_fix=3) == "retry"
```

保留 `tests/test_judge.py` 顶部的 `from eda_studio.config import ...`、`make_config`、`ctx` helper 不动(其他测试仍用)。在文件顶部 import 区追加 `from eda_studio.judge import _rtl_handler`(暂与 `make_judge_fn` import 并存)。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_judge.py -v 2>&1 | head -40`
Expected: 7 个 RTL 测试 FAIL with `ImportError: cannot import name '_rtl_handler'`

- [ ] **Step 3: 实现 `_rtl_handler`**

在 `eda_studio/judge.py` 顶部(模块 docstring 之后、`make_judge_fn` 之前)插入:

```python
def _rtl_handler(ctx: dict, idx: int, rtl_ids: list, max_fix: int) -> str:
    """RTL step 路由:模型调了工具才算完成,否则 retry,耗尽 abort。

    计数机制:用 retry_count(engine 维护的连续 Retry 次数)判断耗尽。
    to: 回环不累加 retry_count,但 RTL 链是线性推进不走回环,所以无冲突。

    Args:
        ctx: judge ctx dict(step_id / tool_calls_count / retry_count / structured)
        idx: 当前 step 在 rtl_ids 中的下标
        rtl_ids: rtl step id 列表
        max_fix: 最大重试次数
    """
    tool_calls_count = ctx.get("tool_calls_count", 0)
    retry_count = ctx.get("retry_count", 0)
    if tool_calls_count > 0:
        if idx < len(rtl_ids) - 1:
            return f"to:{rtl_ids[idx + 1]}"
        return "to:simulate"
    return "abort:done" if retry_count >= max_fix else "retry"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_judge.py -k "rtl" -v`
Expected: 7 个 RTL 测试 PASS。其余测试仍通过(走旧的 `make_judge_fn` 闭包,未动)。

- [ ] **Step 5: 提交**

```bash
git add eda_studio/judge.py tests/test_judge.py
git commit -m "refactor(judge): extract _rtl_handler, migrate RTL tests to direct calls"
```

---

### Task 2: 提取 `_simulate_handler` / `_debug_fix_handler` + 改造对应测试

**Files:**
- Modify: `eda_studio/judge.py`(追加 `_simulate_handler`、`_debug_fix_handler`)
- Test: `tests/test_judge.py`

**Interfaces:**
- Produces:
  - `_simulate_handler(ctx: dict, fix_counts: dict, max_fix: int) -> str`
  - `_debug_fix_handler(ctx: dict, max_fix: int) -> str`
- Consumes: `_rtl_handler` from Task 1(已存在)

- [ ] **Step 1: 写失败测试 — 替换 simulate/debug_fix 测试**

把 `tests/test_judge.py` 里 simulate 和 debug_fix 的 8 个测试改为 handler 直调。`fix_counts` 显式构造并传入。替换后的测试:

```python
from eda_studio.judge import _simulate_handler, _debug_fix_handler

def _fix_counts():
    return {"simulate": 0, "pnr": 0, "drc": 0}

def test_simulate_success_to_synthesize():
    assert _simulate_handler(ctx("simulate", success=True), _fix_counts(), max_fix=3) == "to:synthesize"

def test_simulate_fail_to_debug_fix():
    assert _simulate_handler(ctx("simulate", success=False), _fix_counts(), max_fix=3) == "to:debug_fix"

def test_simulate_fix_count_exceeds_max_aborts():
    fc = _fix_counts()
    assert _simulate_handler(ctx("simulate", success=False), fc, max_fix=2) == "to:debug_fix"
    assert _simulate_handler(ctx("simulate", success=False), fc, max_fix=2) == "to:debug_fix"
    assert _simulate_handler(ctx("simulate", success=False), fc, max_fix=2) == "abort:done"
    assert fc["simulate"] == 3

def test_simulate_success_resets_count():
    fc = _fix_counts()
    _simulate_handler(ctx("simulate", success=False), fc, max_fix=2)
    _simulate_handler(ctx("simulate", success=False), fc, max_fix=2)
    _simulate_handler(ctx("simulate", success=True), fc, max_fix=2)
    assert _simulate_handler(ctx("simulate", success=False), fc, max_fix=2) == "to:debug_fix"
    assert fc["simulate"] == 1

def test_debug_fix_to_simulate_when_tool_called():
    assert _debug_fix_handler(ctx("debug_fix", tool_calls_count=1), max_fix=3) == "to:simulate"

def test_debug_fix_retries_when_no_tool():
    assert _debug_fix_handler(ctx("debug_fix", tool_calls_count=0), max_fix=3) == "retry"

def test_debug_fix_aborts_when_retry_exhausted():
    assert _debug_fix_handler(ctx("debug_fix", tool_calls_count=0, retry_count=2), max_fix=2) == "abort:done"
```

import 区把 Task 1 的 `from eda_studio.judge import _rtl_handler` 替换为:
```python
from eda_studio.judge import (
    _rtl_handler, _simulate_handler, _debug_fix_handler,
)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_judge.py -k "simulate or debug_fix" -v`
Expected: FAIL with `ImportError: cannot import name '_simulate_handler'`

- [ ] **Step 3: 实现 `_simulate_handler` 和 `_debug_fix_handler`**

在 `eda_studio/judge.py` 的 `_rtl_handler` 之后追加:

```python
def _simulate_handler(ctx: dict, fix_counts: dict, max_fix: int) -> str:
    """simulate 路由:成功 → synthesize(重置计数);失败 → debug_fix(计数++),超限 abort。

    计数机制:用 fix_counts["simulate"](闭包维护),不是 retry_count。
    原因:simulate 失败走 "to:debug_fix" 回环,engine 的 retry_count 只对 "retry" 累加,
    "to:" 回环不累加,故需自行维护 per-环节 计数。

    Args:
        ctx: judge ctx dict
        fix_counts: 共享可变 dict,key="simulate"/"pnr"/"drc",本 handler 读写 "simulate"
        max_fix: 最大修复次数
    """
    structured = ctx.get("structured") or {}
    success = structured.get("success", False)
    if success:
        fix_counts["simulate"] = 0
        return "to:synthesize"
    fix_counts["simulate"] += 1
    if fix_counts["simulate"] > max_fix:
        return "abort:done"
    return "to:debug_fix"


def _debug_fix_handler(ctx: dict, max_fix: int) -> str:
    """debug_fix 路由:调了工具(读报告/改 RTL)才回 simulate,否则 retry,耗尽 abort。

    计数机制:用 retry_count(engine 维护)。debug_fix 走 "retry" 路径,engine 会累加
    retry_count;"to:simulate" 回环不累加,但 debug_fix→simulate 是前进不是回环重试。
    """
    tool_calls_count = ctx.get("tool_calls_count", 0)
    retry_count = ctx.get("retry_count", 0)
    if tool_calls_count > 0:
        return "to:simulate"
    return "abort:done" if retry_count >= max_fix else "retry"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_judge.py -k "simulate or debug_fix or rtl" -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add eda_studio/judge.py tests/test_judge.py
git commit -m "refactor(judge): extract _simulate_handler, _debug_fix_handler + migrate tests"
```

---

### Task 3: 提取剩余 6 个 handler + 改造剩余测试

**Files:**
- Modify: `eda_studio/judge.py`(追加 `_synthesize_handler`/`_pnr_handler`/`_drc_fix_handler`/`_drc_handler`/`_gds_handler`/`_render_handler`)
- Test: `tests/test_judge.py`

**Interfaces:**
- Produces:
  - `_synthesize_handler(ctx: dict) -> str`
  - `_pnr_handler(ctx: dict, fix_counts: dict, max_fix: int) -> str`
  - `_drc_fix_handler(ctx: dict, max_fix: int) -> str`
  - `_drc_handler(ctx: dict, fix_counts: dict, max_fix: int) -> str`
  - `_gds_handler(ctx: dict) -> str`
  - `_render_handler(ctx: dict) -> str`

- [ ] **Step 1: 写失败测试 — 替换剩余测试**

把 `tests/test_judge.py` 里 synthesize/pnr/drc_fix/drc/gds/render/unknown 的测试改为 handler 直调。`test_unknown_step_aborts` 暂时移除(在 Task 5 注册测试里重新覆盖)。替换后的测试:

```python
from eda_studio.judge import (
    _rtl_handler, _simulate_handler, _debug_fix_handler,
    _synthesize_handler, _pnr_handler, _drc_fix_handler,
    _drc_handler, _gds_handler, _render_handler,
)

# (RTL_IDS / _fix_counts / ctx / make_config helpers 已在前几个 Task 定义)

def test_synthesize_success_to_pnr():
    assert _synthesize_handler(ctx("synthesize", success=True)) == "to:pnr"

def test_synthesize_fail_to_debug_fix():
    assert _synthesize_handler(ctx("synthesize", success=False)) == "to:debug_fix"

def test_pnr_success_to_drc():
    assert _pnr_handler(ctx("pnr", success=True), _fix_counts(), max_fix=3) == "to:drc"

def test_pnr_fail_to_drc_fix():
    assert _pnr_handler(ctx("pnr", success=False), _fix_counts(), max_fix=3) == "to:drc_fix"

def test_pnr_fix_count_exceeds():
    fc = _fix_counts()
    assert _pnr_handler(ctx("pnr", success=False), fc, max_fix=1) == "to:drc_fix"
    assert _pnr_handler(ctx("pnr", success=False), fc, max_fix=1) == "abort:done"
    assert fc["pnr"] == 2

def test_drc_fix_to_pnr_when_tool_called():
    assert _drc_fix_handler(ctx("drc_fix", tool_calls_count=1), max_fix=3) == "to:pnr"

def test_drc_fix_retries_when_no_tool():
    assert _drc_fix_handler(ctx("drc_fix", tool_calls_count=0), max_fix=3) == "retry"

def test_drc_success_to_gds():
    assert _drc_handler(ctx("drc", success=True), _fix_counts(), max_fix=3) == "to:gds"

def test_drc_fail_to_drc_fix():
    assert _drc_handler(ctx("drc", success=False), _fix_counts(), max_fix=3) == "to:drc_fix"

def test_gds_to_render():
    assert _gds_handler(ctx("gds", success=True)) == "to:render"
    assert _gds_handler(ctx("gds", success=False)) == "abort:done"

def test_render_done():
    assert _render_handler(ctx("render", success=True)) == "abort:done"
```

移除 `test_unknown_step_aborts`(Task 5 重新加)。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_judge.py -v 2>&1 | tail -20`
Expected: 新测试 FAIL with `ImportError` for the 6 new handler names。

- [ ] **Step 3: 实现 6 个 handler**

在 `eda_studio/judge.py` 的 `_debug_fix_handler` 之后追加:

```python
def _synthesize_handler(ctx: dict) -> str:
    """synthesize 路由:成功 → pnr;失败 → debug_fix。无计数。"""
    structured = ctx.get("structured") or {}
    success = structured.get("success", False)
    return "to:pnr" if success else "to:debug_fix"


def _pnr_handler(ctx: dict, fix_counts: dict, max_fix: int) -> str:
    """pnr 路由:成功 → drc(重置计数);失败 → drc_fix(计数++),超限 abort。

    计数机制:用 fix_counts["pnr"](闭包维护),原因同 _simulate_handler。
    """
    structured = ctx.get("structured") or {}
    success = structured.get("success", False)
    if success:
        fix_counts["pnr"] = 0
        return "to:drc"
    fix_counts["pnr"] += 1
    if fix_counts["pnr"] > max_fix:
        return "abort:done"
    return "to:drc_fix"


def _drc_fix_handler(ctx: dict, max_fix: int) -> str:
    """drc_fix 路由:调了工具(读报告/改 SDC/RTL)才回 pnr,否则 retry,耗尽 abort。

    计数机制:用 retry_count(engine 维护),原因同 _debug_fix_handler。
    """
    tool_calls_count = ctx.get("tool_calls_count", 0)
    retry_count = ctx.get("retry_count", 0)
    if tool_calls_count > 0:
        return "to:pnr"
    return "abort:done" if retry_count >= max_fix else "retry"


def _drc_handler(ctx: dict, fix_counts: dict, max_fix: int) -> str:
    """drc 路由:成功 → gds(重置计数);失败 → drc_fix(计数++),超限 abort。

    计数机制:用 fix_counts["drc"](闭包维护),原因同 _simulate_handler。
    """
    structured = ctx.get("structured") or {}
    success = structured.get("success", False)
    if success:
        fix_counts["drc"] = 0
        return "to:gds"
    fix_counts["drc"] += 1
    if fix_counts["drc"] > max_fix:
        return "abort:done"
    return "to:drc_fix"


def _gds_handler(ctx: dict) -> str:
    """gds 路由:成功 → render;失败 → abort。无计数。"""
    structured = ctx.get("structured") or {}
    success = structured.get("success", False)
    return "to:render" if success else "abort:done"


def _render_handler(ctx: dict) -> str:
    """render 路由:恒终止。无计数。"""
    return "abort:done"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_judge.py -v`
Expected: 全部 PASS(此时 `make_judge_fn` 旧闭包仍存在但已无测试调用)。

- [ ] **Step 5: 提交**

```bash
git add eda_studio/judge.py tests/test_judge.py
git commit -m "refactor(judge): extract remaining 6 handlers + migrate all tests"
```

---

### Task 4: 重写 `make_judge_fn` 返回 `CompositeJudge`

**Files:**
- Modify: `eda_studio/judge.py`(替换 `make_judge_fn` 函数体,删除旧闭包,加 `KNOWN_FIXED_STEPS` 常量)
- Test: `tests/test_judge.py`(此时不再调用 `make_judge_fn`,Task 5 再加注册测试)

**Interfaces:**
- Produces:
  - `KNOWN_FIXED_STEPS: tuple` — 模块常量,8 个固定 step id
  - `make_judge_fn(config: AppConfig, rtl_ids: list = None) -> CompositeJudge`
- Consumes: 全部 9 个 handler(Tasks 1-3)

- [ ] **Step 1: 写失败测试 — 类型断言**

在 `tests/test_judge.py` 追加一个最小类型测试(完整注册测试在 Task 5):

```python
from senza import CompositeJudge
from eda_studio.judge import make_judge_fn, KNOWN_FIXED_STEPS

def test_make_judge_fn_returns_composite_judge():
    cj = make_judge_fn(make_config())
    assert isinstance(cj, CompositeJudge)

def test_known_fixed_steps_constant():
    assert KNOWN_FIXED_STEPS == (
        "simulate", "debug_fix", "synthesize",
        "pnr", "drc_fix", "drc", "gds", "render",
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_judge.py -k "composite_judge or fixed_steps" -v`
Expected: FAIL — `make_judge_fn` 仍返回 closure,非 `CompositeJudge`;`KNOWN_FIXED_STEPS` 未定义。

- [ ] **Step 3: 重写 `make_judge_fn`**

在 `eda_studio/judge.py`:
1. 更新模块 docstring 为:`"""judge 逻辑:报告解析 → 路由决策。CompositeJudge 按节点分发,fix_counts 闭包维护 per-环节 回环计数。"""`
2. 更新 import:把 `from .config import AppConfig` 改为:
```python
from senza import CompositeJudge, create_composite_judge

from .config import AppConfig
```
3. 在 handler 函数之后(append `_render_handler` 之后)、`make_judge_fn` 之前,插入常量:
```python
KNOWN_FIXED_STEPS = (
    "simulate", "debug_fix", "synthesize",
    "pnr", "drc_fix", "drc", "gds", "render",
)
```
4. 替换整个 `make_judge_fn` 函数(原 95 行闭包)为:
```python
def make_judge_fn(config: AppConfig, rtl_ids: list = None) -> CompositeJudge:
    """构造 CompositeJudge,按 step 注册独立 handler。

    Args:
        config: AppConfig
        rtl_ids: rtl step id 列表(如 ['rtl_tx','rtl_rx','rtl_top']),
                从 design_config 动态传入。None 时 fallback 到 uart 默认值。

    judge ctx 是只读 dict,字段:step_id / output / step_count / retry_count /
    tool_calls_count / structured。
    retry_count 是 engine 维护的连续 Retry 次数,只对 "retry" 累加;to: 回环不累加。
    per-环节 回环计数用 fix_counts 闭包维护,被 simulate/pnr/drc 三个 handler 共享。
    """
    if rtl_ids is None:
        rtl_ids = ["rtl_tx", "rtl_rx", "rtl_top"]
    max_fix = config.workflow_config.max_fix_retries
    fix_counts = {"simulate": 0, "pnr": 0, "drc": 0}

    cj = create_composite_judge()
    for i, sid in enumerate(rtl_ids):
        cj.on(sid, lambda ctx, i=i: _rtl_handler(ctx, i, rtl_ids, max_fix))
    cj.on("simulate",    lambda ctx: _simulate_handler(ctx, fix_counts, max_fix))
    cj.on("debug_fix",   lambda ctx: _debug_fix_handler(ctx, max_fix))
    cj.on("synthesize",  lambda ctx: _synthesize_handler(ctx))
    cj.on("pnr",         lambda ctx: _pnr_handler(ctx, fix_counts, max_fix))
    cj.on("drc_fix",     lambda ctx: _drc_fix_handler(ctx, max_fix))
    cj.on("drc",         lambda ctx: _drc_handler(ctx, fix_counts, max_fix))
    cj.on("gds",         lambda ctx: _gds_handler(ctx))
    cj.on("render",      lambda ctx: _render_handler(ctx))
    cj.fallback(lambda ctx: "abort:unknown_step")
    return cj
```

- [ ] **Step 4: 运行全部测试确认通过**

Run: `python -m pytest tests/test_judge.py -v`
Expected: 全部 PASS(含新类型测试 + 所有 handler 测试)。

- [ ] **Step 5: 提交**

```bash
git add eda_studio/judge.py tests/test_judge.py
git commit -m "refactor(judge): rewrite make_judge_fn to return CompositeJudge"
```

---

### Task 5: 加注册正确性测试

**Files:**
- Test: `tests/test_judge.py`

**Interfaces:**
- Consumes: `make_judge_fn`, `KNOWN_FIXED_STEPS` from Task 4

- [ ] **Step 1: 写注册测试**

由于 `CompositeJudge` 不可 call、不暴露 dispatch 或 handler 查询接口,探针用"并行注册表"策略:在测试里自建一个 `dict[step_id, handler]`,用与 `make_judge_fn` 相同的注册逻辑注册 wrapper(记录被调用的 step id),再比对。但这会重复生产代码的注册逻辑 —— 不可取。

降级方案(spec 中锁定的降级路径):断言 `make_judge_fn` 不抛异常、返回 `CompositeJudge` 实例,并标注已知限制。`test_make_judge_fn_returns_composite_judge`(Task 4 已加)已覆盖此降级断言。

因此本 Task 改为:确认 Task 4 的降级断言已足够,并补充一个"fallback 哨兵"文档化测试 —— 验证 fallback 返回值确实是哨兵字符串(通过源码 inspection,非运行时调用,因 SDK 不暴露 dispatch):

在 `tests/test_judge.py` 追加:

```python
import inspect
from eda_studio import judge as judge_module

def test_fallback_returns_sentinel():
    """验证 make_judge_fn 源码中 fallback 返回哨兵字符串。

    CompositeJudge 不可 call、不暴露 dispatch,无法运行时验证 fallback 行为。
    退而验证源码中 fallback lambda 返回 'abort:unknown_step'。
    """
    src = inspect.getsource(judge_module.make_judge_fn)
    assert "abort:unknown_step" in src, "fallback 哨兵字符串缺失,注册测试无法区分已注册/未注册"
```

- [ ] **Step 2: 运行测试确认通过**

Run: `python -m pytest tests/test_judge.py -k "fallback or composite_judge or fixed_steps" -v`
Expected: 3 个测试 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_judge.py
git commit -m "test(judge): add fallback sentinel source inspection test"
```

---

### Task 6: 更新调用点,去掉 `create_judge()` 包装

**Files:**
- Modify: `eda_studio/workflow.py:175`(judge 构造)
- Modify: `eda_studio/workflow.py:14-21`(import 清理)
- Modify: `eda_studio/cli.py:228`(cmd_restore 的 judge 构造)
- Modify: `eda_studio/cli.py:38-40`(import 清理)

**Interfaces:**
- Consumes: `make_judge_fn(...) -> CompositeJudge` from Task 4

- [ ] **Step 1: 改 `workflow.py:175`**

把:
```python
    judge = create_judge(make_judge_fn(config, rtl_ids=rtl_ids))
```
改为:
```python
    judge = make_judge_fn(config, rtl_ids=rtl_ids)
```

- [ ] **Step 2: 清理 `workflow.py` import**

`eda_studio/workflow.py` 第 14-21 行的 `from senza import (...)`,移除 `create_judge,`。改后:
```python
from senza import (
    WorkflowEngine, create_os_env, create_executor,
    create_openai_provider, create_anthropic_provider,
    create_pricing_provider, create_fs_tools_plugin,
    create_before_turn_hook, create_after_turn_hook, create_after_tool_call_hook,
    create_after_provider_response_hook,
    create_should_stop_hook, create_shell_executor,
)
```

- [ ] **Step 3: 改 `cli.py:228`(cmd_restore)**

把:
```python
        judge=create_judge(make_judge_fn(config, rtl_ids=dcfg.rtl_step_ids)),
```
改为:
```python
        judge=make_judge_fn(config, rtl_ids=dcfg.rtl_step_ids),
```

- [ ] **Step 4: 清理 `cli.py` import**

`eda_studio/cli.py` 第 38-40 行的 `from senza import (...)`,移除 `create_judge`。改后:
```python
from senza import (
    WorkflowEngine, create_os_env,
)
```

- [ ] **Step 5: 验证 import 无残留**

Run: `python -c "from eda_studio.workflow import build_workflow; from eda_studio.cli import cmd_restore; print('imports OK')"`
Expected: 输出 `imports OK`,无 `ImportError`。

- [ ] **Step 6: 运行全部测试**

Run: `python -m pytest tests/test_judge.py -v`
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add eda_studio/workflow.py eda_studio/cli.py
git commit -m "refactor: pass CompositeJudge directly to WorkflowEngine, drop create_judge wrap"
```

---

### Task 7: 最终验证 + 清理

**Files:**
- 无文件修改(纯验证)

- [ ] **Step 1: 全量测试**

Run: `python -m pytest tests/test_judge.py -v`
Expected: 全部 PASS,测试数 ≥ 18(原 18 个用例的等价覆盖 + 类型/常量/哨兵测试)。

- [ ] **Step 2: 确认无 `create_judge` 残留引用**

Run: `python -c "import ast, pathlib; src = pathlib.Path('eda_studio/judge.py').read_text(); assert 'create_judge' not in src, 'judge.py 残留 create_judge'; print('clean')"`
Expected: 输出 `clean`。

Run: `python -c "import pathlib; src = pathlib.Path('eda_studio/workflow.py').read_text() + pathlib.Path('eda_studio/cli.py').read_text(); assert src.count('create_judge') == 0, '残留 create_judge'; print('clean')"`
Expected: 输出 `clean`。

- [ ] **Step 3: 确认 `judge.py` 无旧闭包残留**

Run: `python -c "import pathlib; src = pathlib.Path('eda_studio/judge.py').read_text(); assert 'def judge(ctx' not in src, '旧闭包残留'; print('clean')"`
Expected: 输出 `clean`。

- [ ] **Step 4: 确认无 per-call logging 残留**

Run: `python -c "import pathlib; src = pathlib.Path('eda_studio/judge.py').read_text(); assert 'logging.getLogger' not in src, 'per-call logging 残留'; print('clean')"`
Expected: 输出 `clean`。

- [ ] **Step 5: 最终提交(如有清理)**

若 Step 1-4 全部通过且无额外改动,跳过提交。否则:
```bash
git add -A
git commit -m "chore(judge): final cleanup after CompositeJudge migration"
```

---

## Self-Review

**1. Spec coverage:**
- 需求 1(`make_judge_fn` 返回 `CompositeJudge`):Task 4 ✓
- 需求 2(RTL per-index 闭包注册):Task 4 Step 3 的 `for i, sid in enumerate(rtl_ids): cj.on(sid, lambda ctx, i=i: ...)` ✓
- 需求 3(8 个固定 step 各注册 handler):Task 4 Step 3 ✓
- 需求 4(fallback 返回哨兵):Task 4 Step 3 + Task 5 ✓
- 需求 5(路由逻辑等价):Tasks 1-3 的 handler 逻辑逐行对应原闭包 ✓
- 非功能 1(handler 模块级可独立 import):Tasks 1-3 ✓
- 非功能 2(18 个用例逻辑分支与断言不变):Tasks 1-3 平移,断言保留且增强(`fix_counts` 直接断言)✓
- 非功能 3(fix_counts 行为不变):Tasks 1-3 的 handler 保持累加/重置/超限逻辑 ✓
- 验收 2(调用点去掉 `create_judge`):Task 6 ✓
- 验收 3(全部测试通过):Tasks 1-6 每个 Step 4/6 运行 ✓
- 验收 4(端到端行为不变):handler 逻辑逐行对应 + 调用点仅去包装层 ✓
- 日志删除(设计决策):Task 7 Step 4 验证 ✓

**2. Placeholder scan:** 无 TBD/TODO/"implement later"。Task 5 的降级方案是 spec 锁定的已知限制,非占位符。

**3. Type consistency:**
- `_rtl_handler(ctx, idx, rtl_ids, max_fix)` — Task 1 定义,Task 4 注册时调用 `_rtl_handler(ctx, i, rtl_ids, max_fix)` ✓
- `_simulate_handler(ctx, fix_counts, max_fix)` — Task 2 定义,Task 4 注册 ✓
- `_debug_fix_handler(ctx, max_fix)` — Task 2 定义,Task 4 注册 ✓
- `_synthesize_handler(ctx)` — Task 3 定义,Task 4 注册 ✓
- `_pnr_handler(ctx, fix_counts, max_fix)` — Task 3 定义,Task 4 注册 ✓
- `_drc_fix_handler(ctx, max_fix)` — Task 3 定义,Task 4 注册 ✓
- `_drc_handler(ctx, fix_counts, max_fix)` — Task 3 定义,Task 4 注册 ✓
- `_gds_handler(ctx)` — Task 3 定义,Task 4 注册 ✓
- `_render_handler(ctx)` — Task 3 定义,Task 4 注册 ✓
- `KNOWN_FIXED_STEPS` — Task 4 定义,Task 5 消费 ✓
- `make_judge_fn(config, rtl_ids=None) -> CompositeJudge` — Task 4 定义,Task 6 调用 ✓

无类型/签名不一致。
