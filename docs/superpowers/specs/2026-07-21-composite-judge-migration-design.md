# CompositeJudge 迁移设计

- **Issue**: [#3 — judge: 为何不用 CompositeJudge 替代单一闭包的分发?](https://github.com/oh-my-harness/eda-studio/issues/3)
- **日期**: 2026-07-21
- **状态**: 待评审

## 背景

`eda_studio/judge.py` 的 `make_judge_fn` 返回一个单一 closure,内部用一长串 `if step_id == ...` 分发到每个 step 的路由逻辑(rtl_tx/rtl_rx/rtl_top/simulate/debug_fix/synthesize/pnr/drc_fix/drc/gds/render),并通过闭包变量 `fix_counts` 维护 per-环节 回环计数。单函数 ~95 行,分支密集。

senza SDK 提供了 `CompositeJudge`,支持按节点注册独立路由函数。issue 提出是否值得迁移,并列出三个顾虑。

### 顾虑核实结果

1. **跨 step 共享状态**:`CompositeJudge` 的 `.on(step, callback)` 接受普通 Python callable,handler 可闭包捕获外部 dict。`fix_counts` 在 `make_judge_fn` 作用域声明,被 `simulate`/`pnr`/`drc` 三个 handler 闭包共享 —— 与当前单闭包语义完全等价。**非阻碍**。
2. **`rtl_ids` 动态路由**:`.on()` 需字面 step id,但可在 `make_judge_fn` 里循环注册:`for i, sid in enumerate(rtl_ids): cj.on(sid, make_rtl_handler(i, ...))`。**非阻碍**。
3. **`retry_count` 与 `fix_counts` 语义差异**:迁移后两种计数机制分别落在不同 handler 里,通过 docstring 文档化。**非阻碍**。

### SDK 能力确认(来自 `.venv/lib/python3.12/site-packages/senza/__init__.pyi`)

- `WorkflowEngine.__init__` 签名:`judge: Judge | CompositeJudge` —— `CompositeJudge` 可直接传给 engine,无需 `create_judge()` 包装。
- `CompositeJudge` 仅暴露 `on(step, callback)` 和 `fallback(callback)`,handler 是 `Callable[[dict], str]`。
- `CompositeJudge` 本身不可 call、不暴露 handler 查询接口。
- engine 对 judge 返回值的路由:`"to:<step_id>"` 路由到下一节点,`"retry"` 重试当前步,`"done"` / `"abort:<reason>"` / `"fail:<reason>"` 终止。`abort:` 后的 reason 仅作诊断,engine 不做路由判断(见 `workflow.py` 顶部注释)。

## 目标

将 `judge.py` 的单一闭包迁移为 `CompositeJudge` + 模块级 handler 函数,使每个 step 的路由逻辑独立可测,并与 senza 的声明式设计意图一致。

## 需求

### 功能性

1. `make_judge_fn(config, rtl_ids=None)` 返回 `CompositeJudge` 对象。
2. 每个 RTL step id(`rtl_ids` 的每个元素)注册独立 handler,handler 闭包捕获该 step 在链中的 index。
3. 固定 step(simulate/debug_fix/synthesize/pnr/drc_fix/drc/gds/render)各注册一个 handler。
4. 未知 step id 落入 fallback,返回 `"abort:unknown_step"`(哨兵,用于注册测试;engine 仍按 `abort:` 前缀终止)。
5. 路由逻辑与当前实现完全等价 —— 同样的 ctx 字段、同样的判断、同样的返回值。

### 非功能性

- handler 提到模块级,可独立 import 测试。
- 现有 18 个测试用例的逻辑分支与断言保持不变,改为直接调用 handler。
- `fix_counts` 共享状态的行为不变:simulate/pnr/drc 的计数累加、成功重置、超限 abort。

## 设计

### 架构

```
make_judge_fn(config, rtl_ids)
   ├─ 声明 fix_counts = {"simulate":0, "pnr":0, "drc":0}  (共享可变状态)
   ├─ cj = create_composite_judge()
   ├─ for i, sid in enumerate(rtl_ids):
   │     cj.on(sid, lambda ctx, i=i: _rtl_handler(ctx, i, rtl_ids, max_fix))
   ├─ cj.on("simulate",   lambda ctx: _simulate_handler(ctx, fix_counts, max_fix))
   ├─ cj.on("debug_fix",  lambda ctx: _debug_fix_handler(ctx, max_fix))
   ├─ cj.on("synthesize", lambda ctx: _synthesize_handler(ctx))
   ├─ cj.on("pnr",        lambda ctx: _pnr_handler(ctx, fix_counts, max_fix))
   ├─ cj.on("drc_fix",    lambda ctx: _drc_fix_handler(ctx, max_fix))
   ├─ cj.on("drc",        lambda ctx: _drc_handler(ctx, fix_counts, max_fix))
   ├─ cj.on("gds",        lambda ctx: _gds_handler(ctx))
   ├─ cj.on("render",     lambda ctx: _render_handler(ctx))
   ├─ cj.fallback(lambda ctx: "abort:unknown_step")
   └─ return cj
```

handler 是无状态纯函数(从入参读 ctx + deps),`fix_counts` 作为可变 dict 参数传入,handler 原地修改。

### 组件:模块级 handler 函数

| Handler | 签名 | 职责 | 计数机制 |
|---|---|---|---|
| `_rtl_handler` | `(ctx, idx, rtl_ids, max_fix)` | `tool_calls_count>0` → `to:rtl_ids[idx+1]` 或 `to:simulate`;否则 `retry`/`abort:done` | `retry_count`(engine 维护) |
| `_simulate_handler` | `(ctx, fix_counts, max_fix)` | success → 重置计数+`to:synthesize`;否则计数++→`to:debug_fix`/`abort:done` | `fix_counts["simulate"]`(闭包维护) |
| `_debug_fix_handler` | `(ctx, max_fix)` | `tool_calls_count>0` → `to:simulate`;否则 `retry`/`abort:done` | `retry_count` |
| `_synthesize_handler` | `(ctx)` | success → `to:pnr`;否则 `to:debug_fix` | 无 |
| `_pnr_handler` | `(ctx, fix_counts, max_fix)` | 同 simulate 模式,指向 drc/drc_fix | `fix_counts["pnr"]` |
| `_drc_fix_handler` | `(ctx, max_fix)` | 同 debug_fix 模式,回 pnr | `retry_count` |
| `_drc_handler` | `(ctx, fix_counts, max_fix)` | 同 simulate 模式,指向 gds/drc_fix | `fix_counts["drc"]` |
| `_gds_handler` | `(ctx)` | success → `to:render`;否则 `abort:done` | 无 |
| `_render_handler` | `(ctx)` | 恒 `abort:done` | 无 |

每个 handler 的 docstring 明确写清用的是 `retry_count` 还是 `fix_counts`,以及原因(`retry_count` 只对 `"retry"` 累加,`to:` 回环不累加,故 simulate/pnr/drc 需自行维护计数)。

### 模块常量

```python
KNOWN_FIXED_STEPS = (
    "simulate", "debug_fix", "synthesize",
    "pnr", "drc_fix", "drc", "gds", "render",
)
```

供注册测试遍历(RTL steps 动态,单独从 `rtl_ids` 取)。

### 调用点改动

- `workflow.py:175`:`judge = create_judge(make_judge_fn(...))` → `judge = make_judge_fn(...)`
- `cli.py:228`:同上
- 若 `cmd_restore` 路径也构造 judge,同步处理。
- `workflow.py` / `cli.py` 的 `from senza import ...` 中移除不再使用的 `create_judge`(若别处未用)。

### 数据流

```
WorkflowEngine 每步结束
   ↓ 构造 ctx dict {step_id, output, step_count, retry_count, tool_calls_count, structured}
CompositeJudge.dispatch(step_id, ctx)
   ↓ 查 .on(step_id) 注册表
命中的 handler(ctx, deps...) → "to:X" | "retry" | "abort:done"
   ↓ 未命中
fallback(ctx) → "abort:unknown_step"
   ↓
engine 根据 "to:" / "retry" / "abort:" 前缀路由
```

### 错误处理

- handler 内部错误路径保持原样:RTL/debug_fix/drc_fix 用 `retry_count >= max_fix` → `abort:done`;simulate/pnr/drc 用 `fix_counts[step] > max_fix` → `abort:done`;gds 失败、render 完成、未知 step → `abort`。
- `ctx` 字段缺失继续用 `.get()` 兜底,不引入额外校验(engine 保证 ctx 完整)。
- fallback 返回 `"abort:unknown_step"` 而非 `"abort:done"`,仅为注册测试提供可区分的哨兵;engine 对两种返回的处理一致(终止)。

### 不变式

1. `make_judge_fn` 返回的 `CompositeJudge` 对每个已知 step id(`rtl_ids` ∪ `KNOWN_FIXED_STEPS`)都注册了 handler,未知 step 落入 fallback。
2. `fix_counts` 的三个 key 只在对应的 handler 内被读写,无跨 step 交叉。
3. `retry_count`(engine 维护)只用于 RTL/debug_fix/drc_fix 三个 `retry` 路径;`fix_counts` 只用于 simulate/pnr/drc 三个 `to:` 回环路径。两者语义不混用。

## 测试

### 层 1:handler 单元测试(主)

`tests/test_judge.py` 现有 18 个用例平移到 handler 单元测试,直接 import 调用,不走 `CompositeJudge`。`fix_counts` 显式构造并传入,可断言:

```python
from eda_studio.judge import _rtl_handler, _simulate_handler, _debug_fix_handler

def ctx(step_id, success=None, tool_calls_count=0, retry_count=0):
    return {"step_id": step_id, "output": "", "step_count": 1,
            "retry_count": retry_count, "tool_calls_count": tool_calls_count,
            "structured": {"success": success} if success is not None else {}}

def test_rtl_tx_done_when_tool_called():
    assert _rtl_handler(ctx("rtl_tx", tool_calls_count=1), idx=0,
                        rtl_ids=["rtl_tx","rtl_rx","rtl_top"], max_fix=3) == "to:rtl_rx"

def test_simulate_fix_count_exceeds_max_aborts():
    fix_counts = {"simulate": 0, "pnr": 0, "drc": 0}
    assert _simulate_handler(ctx("simulate", success=False), fix_counts, max_fix=2) == "to:debug_fix"
    assert _simulate_handler(ctx("simulate", success=False), fix_counts, max_fix=2) == "to:debug_fix"
    assert _simulate_handler(ctx("simulate", success=False), fix_counts, max_fix=2) == "abort:done"
```

逻辑分支与断言与原测试一致。`fix_counts` 现在可直接 `assert fix_counts["simulate"] == 2`,比原测试的间接观察更精确。

### 层 2:注册正确性测试(补)

一个用例,验证 `make_judge_fn` 返回的 `CompositeJudge` 对所有已知 step id 都注册了 handler,未知 step 落入 fallback:

```python
from eda_studio.judge import make_judge_fn, KNOWN_FIXED_STEPS

def test_registration_covers_all_steps():
    config = make_config()
    rtl_ids = ["rtl_tx", "rtl_rx", "rtl_top"]
    cj = make_judge_fn(config, rtl_ids=rtl_ids)
    sentinel = "abort:unknown_step"
    # 用最小 ctx 逐个触发,断言已知 step 不返回哨兵
    for sid in list(rtl_ids) + list(KNOWN_FIXED_STEPS):
        result = _probe(cj, sid)
        assert result != sentinel, f"{sid} 未注册(落入 fallback)"
    # 未知 step 应返回哨兵
    assert _probe(cj, "unknown_step") == sentinel
```

`CompositeJudge` 不可 call、不暴露 dispatch 或 handler 查询接口,因此探针 `_probe(cj, sid)` 是测试本地的适配器:在 `make_judge_fn` 之外,用一个独立的 `create_composite_judge()` 实例,以相同方式注册一个"记录被调用 step id"的 wrapper handler,再比对。**实现锁定**:`_probe` 的具体形式在实现阶段确定,但必须满足 —— 对已注册 step 返回该 step 的 handler 结果(非哨兵),对未注册 step 返回哨兵 `abort:unknown_step`。由于 SDK 不暴露内部注册表,探针可能需要借助 `WorkflowEngine` 的单步执行事件或自建并行注册表来间接验证;若证实无法在不污染生产代码的前提下实现,降级为仅断言 `make_judge_fn` 不抛异常且返回 `CompositeJudge` 实例,并在该用例注释中标记为已知限制。

## 不做的事(YAGNI)

- 不为 handler 加 `Literal` 返回类型注解 —— 过度约束,返回普通 `str`。
- 不引入 `dataclass` 包装 ctx —— engine 给的就是 dict,保持 dict。
- 不加跑真 engine 的集成测试 —— 单元测试 + 注册测试已覆盖逻辑,真 engine 集成属于 `workflow.py` 的职责。
- 不保留 per-call `logging.info(f"judge: step=...")` 日志 —— engine 的 `step_started`/`step_finished` 事件已覆盖 step 级信息,handler 不再内嵌日志。

## 验收标准

1. `eda_studio/judge.py` 改为返回 `CompositeJudge`,9 个模块级 handler 函数,无单闭包 if-else 分发。
2. `workflow.py` / `cli.py`(及 `cmd_restore` 若涉及)的 judge 构造改为直接传 `make_judge_fn(...)` 返回值,去掉 `create_judge()` 包装。
3. `tests/test_judge.py` 全部用例通过,18 个原用例逻辑分支与断言不变,新增注册测试通过。
4. 现有 EDA workflow 端到端行为不变(同一 ctx 序列产生相同的路由决策)。
