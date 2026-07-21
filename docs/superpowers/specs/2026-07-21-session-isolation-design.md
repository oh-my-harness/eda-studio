# Session 隔离设计

- **关联 issue**: [#4 — session: 不同 design / 不同 run 的 sub-agent session 全堆在同一个 sessions/sub-agents/ 目录](https://github.com/oh-my-harness/eda-studio/issues/4)
- **日期**: 2026-07-21
- **状态**: 设计已确认,待上游 issue 解决后实施

## 背景与问题

不同 design、不同次 run 产生的 workflow session 全部混写在同一个目录 `sessions/sub-agents/`,没有按 design / task / step 隔离。每个 session 的 `meta.json` 里 `name: null` 且 `parent_session_path: null`,无法从 session 自身判断它属于哪个 design / 哪次 task run。要追溯只能 parse `entries.jsonl` 首条消息的 `design_dir` 字段。

### 根因(经 runtime 源码核实)

`llm-harness-runtime` 的 `WorkflowEngine` 在两个地方调用 `SessionFactory::create(&self.config.session_base_dir, model)`:

1. `workflow/engine/runner.rs:822-826` — 每个 LLM step 的主 session
2. `workflow/engine/runner.rs:1150-1165`(`build_step_spawner`)— 传给 `HarnessSubAgentSpawner`,用于 sub-agent session

两处都直接传 `session_base_dir`(默认 `sessions`),没有拼 task_id / step_id 前缀。

`JsonlSessionFactory::create`(`spawn/spawner.rs:426-460`)**硬编码** `base_dir.join("sub-agents")`,导致主 step session 和真 sub-agent session 都写到 `<session_base_dir>/sub-agents/<session_id>/`。

> **注**:issue 标题说"sub-agent session",但经核实 eda-studio 当前所有 LLM step 的 `allowed_tools` 是 `["write","read","edit"]`(`workflow.py:128,134,139`),不含 `spawn_agent`。因此 `sessions/sub-agents/` 下的 10 个目录**不是真 sub-agent session,而是主 workflow 各个 LLM step 的 session**。`sub-agents/` 这个子目录名是 runtime 硬编码的,不区分主/子。这不影响修复方向,但解释了为什么"sub-agent session"里其实没有真 sub-agent。

### Senza / Runtime 限制清单

1. **Python 只能传 `session_base_dir: str`**,内部硬编码 `JsonlSessionFactory`,无 `with_session_factory`。(`Senza/src/pyworkflow.rs:940, 966, 1028`)
2. **`SessionFactory::create(base_dir, model)` 签名拿不到 `task_id` / `step_id` / `attempt` / `scope`**。(`spawner.rs:37-44`)
3. **`JsonlSessionFactory::create` 硬编码 `base_dir.join("sub-agents")`**,主 step 和真 sub-agent session 都写这里。(`spawner.rs:432`)
4. **engine 两个调用点都传 `session_base_dir`**,没拼 task_id/step_id 前缀。(`runner.rs:825` 主 step、`runner.rs:1158` sub-agent spawner)
5. **`build_step_spawner` 没传 step_id 给 spawner**,sub-agent session 创建时不知道属于哪个 step。(`runner.rs:1150-1165`)
6. **engine 有 `task_id: TaskId`**,restore 时从外部传入,run 路径一致性好保证。(`runner.rs:219, 111`)

## 目标

workflow session 按 `session_root / task_id / step_id-attempt_seq` 隔离,主 step session 与该 step 派生的 sub-agent session 分离。最清晰分割,retry 算独立 step。

## 最终布局

```
<session_root>/                    ← 环境变量 EDA_STUDIO_SESSION_DIR 决定,默认 "sessions"
    task-<uuid>/                    ← runtime 拼,每次 run 独立 (TaskId.0 形如 "task-<uuid>")
    <step_id>-<attempt_seq>/       ← runtime 拼,每次执行(含 retry)独立
      <session_id>/                ← 主 step session (factory 创建)
      sub-agents/<session_id>/     ← 该次执行派生的 sub-agent
```

- `<session_root>` 由环境变量 `EDA_STUDIO_SESSION_DIR` 决定,默认 `sessions`(仓库根的 `sessions/` 目录)。
- `<task_id>` 是 runtime 内部生成的 uuid(`TaskId(format!("task-{}", uuid::Uuid::new_v4()))`),restore 时从 `.taskstore/task_id` 读回。
- design 归属反查路径:`designs/<design>/.taskstore/task_id` → task_id → `<session_root>/<task_id>/`。不设 `<design>/` 子目录(task_id 全局唯一,design 层冗余)。
- executor step(如 `simulate`/`synthesize`/`pnr`/`drc`/`gds`/`render`)不创建 session,仅 LLM step 才有目录。

## 职责划分

- **eda-studio**:读环境变量得 `session_root`,直接作为 `session_base_dir` 传给 engine。不感知 task_id/step/attempt。
- **runtime `WorkflowEngine`**:在 `run_llm_step` 拼 `<task_id>/<step_id>-<attempt_seq>`;`build_step_spawner` 再加 `sub-agents/`。
- **runtime `JsonlSessionFactory`**:去掉硬编码的 `base_dir.join("sub-agents")`,直接在传入的 `base_dir` 下创建 `<session_id>/`。回归单一职责。
- **runtime `HarnessSubAgentSpawner`**:接受 engine 已拼好的 dir(含 `sub-agents/`),原样传给 factory。`new()` 签名不变。

## 改动分布

| 仓库 | 文件 | 改动 | 执行者 |
|------|------|------|--------|
| eda-studio | `workflow.py`, `cli.py` | 新增 1 个 `_session_base_dir()` helper + 2 处调用点传 `session_base_dir` | eda-studio 维护者(本仓库) |
| Senza | `pyworkflow.rs` | 无实质改动(`session_base_dir` 参数已存在,透传即可) | — |
| runtime | `spawn/spawner.rs` | `JsonlSessionFactory::create` 去 `sub-agents/` 硬编码 | 提 issue 给 runtime 仓库 |
| runtime | `workflow/engine/runner.rs` | `run_llm_step` 拼 task_id/step-attempt 前缀;`build_step_spawner` 拼 sub-agents 后缀 | 提 issue 给 runtime 仓库 |

### 实现分工

- **eda-studio 侧**(本仓库自行实施):`workflow.py` + `cli.py` 改动。**必须等上游 runtime issue 解决后才能接入**(否则 runtime 仍硬编码 `sub-agents/` 子目录,eda-studio 传 `session_base_dir` 只能让所有 session 落到 `<session_root>/sub-agents/` 下,达不到 task_id/step 级隔离)。
- **runtime 侧**(提 issue,由 runtime 维护者推进):
  - `JsonlSessionFactory::create` 去掉 `base_dir.join("sub-agents")` 硬编码。
  - `run_llm_step` 拼 `session_base_dir/<task_id>/<step_id>-<attempt_seq>` 前缀。
  - `build_step_spawner` 拼 `session_base_dir/<task_id>/<step_id>-<attempt_seq>/sub-agents` 后缀,并把 step_id + attempt_seq 从 `run_llm_step` 传入。
- **Senza 侧**(提 issue,由 Senza 维护者确认):无实质代码改动,但需确认 `session_base_dir` 参数透传到 `WorkflowEngineConfig` 的行为不变(已核实 `pyworkflow.rs:966, 1028` 透传)。

## Runtime 改动细节

### 改动 1:`JsonlSessionFactory::create`(`spawn/spawner.rs:426-460`)— 去硬编码

**现状:**
```rust
let session_dir = base_dir.join("sub-agents");  // 硬编码
```

**改后:** 直接用 `base_dir`:
```rust
let session_dir = base_dir.to_path_buf();  // 调用方负责拼好路径
```

factory 回归单一职责——在传入的 `base_dir` 下创建 `<session_id>/`。`NoOpSessionFactory` 不受影响。

### 改动 2:`run_llm_step`(`runner.rs:817-826`)— engine 拼主 step session 路径

**现状:**
```rust
let (storage, session_id) = self
    .config
    .session_factory
    .create(&self.config.session_base_dir, &self.config.model)
    .await?;
```

**改后:** 先拼路径再调 factory:
```rust
// 算 attempt_seq:step_history 中同 step_id 的 record 数 +1
let attempt_seq = {
    let state = self.workflow_state.lock().await;
    state.step_history.iter().filter(|r| r.step_id == step.id()).count() + 1
};
let session_dir = self.config.session_base_dir
    .join(&self.task_id.0)
    .join(format!("{}-{}", step.id(), attempt_seq));
let (storage, session_id) = self
    .config
    .session_factory
    .create(&session_dir, &self.config.model)
    .await?;
```

- `task_id` 从 `self.task_id` 取(engine 内部已有)。
- `step_id` 从 `step.id()` 取。
- `attempt_seq` 查 `step_history`:session 创建时本次 `StepRecord` 尚未 push(push 发生在 `apply_transition`,即 transition 决策后),所以 `step_history` filter count +1 即当前 attempt。

### 改动 3:`build_step_spawner`(`runner.rs:1150-1165`)— 拼 sub-agents 后缀

**现状:**
```rust
fn build_step_spawner(&self, bus: ...) -> HarnessSubAgentSpawner {
    HarnessSubAgentSpawner::new(
        self.config.model.clone(),
        self.config.client.clone(),
        self.config.session_base_dir.clone(),
        bus, ...
    )
    .env_factory(...)
    .session_factory(...)
    .builder_customize(...)
}
```

**改后:** 接收 `step_id` + `attempt_seq`,拼好 sub-agent dir 传入:
```rust
fn build_step_spawner(
    &self,
    bus: ...,
    step_id: &StepId,
    attempt_seq: usize,
) -> HarnessSubAgentSpawner {
    let sub_agent_base = self.config.session_base_dir
        .join(&self.task_id.0)
        .join(format!("{}-{}", step_id, attempt_seq))
        .join("sub-agents");
    HarnessSubAgentSpawner::new(
        self.config.model.clone(),
        self.config.client.clone(),
        sub_agent_base,
        bus, ...
    )
    ...
}
```

调用点(`runner.rs:860`)同步传 `step.id()` 和 `attempt_seq`:
```rust
let spawner = Arc::new(self.build_step_spawner(bus.clone(), step.id(), attempt_seq));
```

`HarnessSubAgentSpawner::new` 签名不变(仍接收 `session_base_dir: PathBuf`),语义从"根目录"变成"已拼好的 sub-agent 目录"。spawner 内部 `spawn_inner` 里 `self.session_base_dir.clone()` 传给 factory 的逻辑不变(`spawner.rs:184-185, 211`)。

### 关键不变量

- **restore 路径一致性**:`task_id` 从外部传入(`TaskId`),restore 时 eda-studio 传同一个 task_id,runtime 用 `self.task_id` 拼路径 → restore 后新创建的 session 落到同一 `<task_id>/` 目录下。
- **executor step 不创建 session**:仅 `run_llm_step` 调 factory,`run_executor_step` 不调。
- **attempt_seq 准确性**:session 创建时本次 `StepRecord` 尚未 push,`step_history` filter count +1 即当前 attempt。retry(`Transition::Retry`)和 `StepExecutionPolicy.max_attempts` 都会重新进入 `run_llm_step`,各自产生新 attempt_seq。
- **`restore_from_step` 场景**:`restore_from_step`(`runner.rs:158`)会 truncate `step_history` 中目标 step 及其下游 record,因此重跑时 `attempt_seq` 从 1 重新计数(被截断的 record 不再计入)。这会导致重跑的 session 目录与首次 run 的同名目录(如 `rtl_tx-1/`)路径相同但 session_id 不同,`<session_id>/` 子目录不冲突(uuid 唯一),`<step_id>-<attempt>/` 父目录会被复用。这是可接受的行为——`restore_from_step` 语义就是"从该步重跑",旧 session 仍保留在父目录下作为历史。

## eda-studio 改动细节

### 环境变量读取

新增 helper(放 `workflow.py`):
```python
import os

def _session_base_dir() -> str:
    """session 根目录。默认 'sessions'(仓库根),可通过环境变量覆盖。"""
    return os.environ.get("EDA_STUDIO_SESSION_DIR", "sessions")
```

### `build_workflow`(`workflow.py:177-179`)

```python
engine = WorkflowEngine(
    workflow_dict, provider, config.model, judge, env=env,
    session_base_dir=_session_base_dir(),
)
```

### `cmd_restore`(`cli.py:224-230`)

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

### serve 路径

`_workflow_runner`(`cli.py:265-284`)直接调 `build_workflow`(`cli.py:274`),自动继承 `session_base_dir`,**无需额外改**。

### eda-studio 改动汇总

| 文件 | 位置 | 改动 |
|------|------|------|
| `workflow.py` | 新增 `_session_base_dir()` helper | 读 `EDA_STUDIO_SESSION_DIR` 环境变量,默认 `sessions` |
| `workflow.py:177-179` | `build_workflow` 的 `WorkflowEngine(...)` | 加 `session_base_dir=_session_base_dir()` |
| `cli.py:224-230` | `cmd_restore` 的 `WorkflowEngine.restore(...)` | 加 `session_base_dir=_session_base_dir()` |

## restore 一致性

- `cmd_run` → `build_workflow` → runtime `WorkflowEngine::new` 内部生成 `task_id`(uuid),写进 `designs/<design>/.taskstore/task_id`。
- `cmd_restore` 从 `.taskstore/task_id` 读回 `task_id`(`cli.py:218`),传给 `WorkflowEngine.restore`。runtime 用这个 `task_id` 拼 `sessions/<task_id>/<step_id>-<attempt>/`。
- 两处 `session_base_dir` 相同(都从同一环境变量读),`task_id` 相同 → restore 后新 session 落到同一 `<task_id>/` 目录下,与原 run 的 session 并列。**一致性保证。**

## 历史 session 处理

- 旧 session 在 `sessions/sub-agents/<session_id>/`。
- 改动后新 session 落到 `sessions/<task_id>/<step_id>-<attempt>/<session_id>/`。
- **不提供迁移脚本**:旧 session 的 `meta.json` 无 task_id/step_id 信息(只有 `name: null`),要迁移得 parse `entries.jsonl` 首条消息的 `design_dir`——成本高且不可靠(restore 路径要求 task_id 一致,旧 session 的 task_id 关联也已丢失)。
- **处理方式**:接受新路径只对后续 run 生效。旧的 `sessions/sub-agents/` 可手动清理(`rm -rf sessions/sub-agents/`)或保留。

## 测试

### eda-studio 侧测试
- `test_workflow.py`:验证 `_session_base_dir()` helper 返回值(默认 `sessions`,环境变量覆盖生效)。`build_workflow` 返回 `WorkflowEngine` 对象,runtime 不暴露内部 `session_base_dir` 字段,故不直接断言传入值,而是测 helper 单元逻辑 + 构造不抛异常。
- `test_cli_commands.py`:验证 `cmd_restore` 在有 taskstore 的情况下能构造 engine 不抛异常(用 mock provider)。
- 环境变量覆盖测试:`EDA_STUDIO_SESSION_DIR=/tmp/foo` → `_session_base_dir() == "/tmp/foo"`。

### runtime 侧测试(上游 issue 范围)

- `tests.rs`:验证 LLM step session 落到 `<session_base_dir>/<task_id>/<step_id>-1/<session_id>/`。
- retry 场景:同 step 跑两次 → 两个目录 `<step_id>-1/` 和 `<step_id>-2/`。
- sub-agent 场景(若 `allowed_tools` 含 `spawn_agent`):sub-agent session 落到 `<step_id>-1/sub-agents/<session_id>/`。
- restore 场景:restore 后新 session 与原 run session 在同一 `<task_id>/` 下。

## 非目标

- 不改 `.taskstore` 路径(仍在 `designs/<design>/.taskstore`)。
- 不迁移历史 session。
- 不改 Senza Python 绑定 API(`session_base_dir` 参数已存在)。
- 不做 session 清理自动化(手动 `rm -rf` 或保留)。
- 不引入 `<design>/` 子目录(task_id 全局唯一,design 层冗余)。
