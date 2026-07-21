# Token 用量与成本显示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WebUI 显示每步和总的 token 用量(输入/输出/cache)与真实成本,修复前端字段名 bug,挂载 PricingProvider。

**Architecture:** 后端 `workflow.py` 调 `engine.with_pricing(pricing)` 挂载 PricingProvider(Senza #20 已修复);`state.py` 的 `status_snapshot()` 加 `total_tokens` 字段;前端 `index.html` 修字段名 bug(`input_tokens`→`total_input_tokens`)、加 `totalTokens` 累加器、顶栏并排显示 cost+token、step card 显示完整分项。

**Tech Stack:** Python 3.12, senza-sdk 0.4.8(dev 安装,含 `with_pricing`), FastAPI, 原生 HTML/JS(无前端框架), pytest

## Global Constraints

- senza-sdk 0.4.8,本地 dev 安装(`scripts/install-senza-dev.sh`),含 `WorkflowEngine.with_pricing`
- `CostAggregate` 字段名:`total_input_tokens` / `total_output_tokens` / `total_cache_read_tokens` / `total_cache_write_tokens` / `total_reasoning_tokens` / `total_cost` / `by_model`
- `TokenPrice` 字段默认 0.0,不补 cache 字段也能跑,但补上更完整
- 前端无构建系统,`static/index.html` 是单文件 HTML+CSS+JS
- 测试不依赖真实 LLM API 和 EDA 工具
- 不动 workflow/judge/executor 逻辑
- 不改 `WorkflowEvent` payload 结构

**Spec:** `docs/superpowers/specs/2026-07-21-token-usage-display-design.md`

---

## File Structure

| 文件 | 职责 | 改动类型 |
|------|------|---------|
| `eda_studio/workflow.py` | `build_workflow` 链式调用加 `.with_pricing(pricing)` | Modify |
| `eda_studio/state.py` | `status_snapshot()` 加 `total_tokens` 字段 | Modify |
| `eda_studio/cli.py` | 更新 line 14-17 过时注释 | Modify |
| `config.yaml` | pricing 表补 cache 字段 | Modify |
| `config.example.yaml` | pricing 表补 cache 字段 | Modify |
| `static/index.html` | 修字段名 bug + 显示 token/cost | Modify |
| `tests/test_state.py` | `total_tokens` 字段测试 | Create |
| `tests/test_workflow.py` | `with_pricing` 挂载验证 | Modify |

---

### Task 1: `state.py` — `status_snapshot()` 加 `total_tokens` 字段

**Files:**
- Modify: `eda_studio/state.py:30-59`
- Test: `tests/test_state.py` (Create)

**Interfaces:**
- Consumes: `engine.total_cost()` 返回 dict(含 `total_cost` / `total_input_tokens` / `total_output_tokens` / `total_cache_read_tokens` / `total_cache_write_tokens` / `total_reasoning_tokens`)
- Produces: `status_snapshot()` 返回 dict 新增 `total_tokens` 字段(`{input, output, cache_read, cache_write, reasoning}` 或 `None`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_state.py`:

```python
from eda_studio.state import AppState


class FakeEngine:
    """Mock engine for status_snapshot tests."""

    def total_cost(self):
        return {
            "total_input_tokens": 100,
            "total_output_tokens": 50,
            "total_cache_read_tokens": 10,
            "total_cache_write_tokens": 5,
            "total_reasoning_tokens": 0,
            "total_cost": 0.0025,
            "by_model": {},
        }

    def state(self):
        return "running"

    def current_step(self):
        return "rtl_tx"

    def step_history(self):
        return []


def test_status_snapshot_includes_total_tokens():
    s = AppState()
    s.engine = FakeEngine()
    s.task_running = True
    snap = s.status_snapshot()
    assert snap["total_cost"] == 0.0025
    assert snap["total_tokens"] == {
        "input": 100,
        "output": 50,
        "cache_read": 10,
        "cache_write": 5,
        "reasoning": 0,
    }


def test_status_snapshot_idle_total_tokens_none():
    s = AppState()
    snap = s.status_snapshot()
    assert snap["total_tokens"] is None
    assert snap["total_cost"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state.py -v`
Expected: FAIL with `KeyError: 'total_tokens'` or `assert None == {...}`

- [ ] **Step 3: Write minimal implementation**

Modify `eda_studio/state.py` `status_snapshot()` — replace the whole method:

```python
    def status_snapshot(self) -> dict:
        """返回可序列化的 workflow 运行时状态快照。"""
        engine = self.engine
        if engine is None:
            return {
                "running": False,
                "state": "idle",
                "current_step": None,
                "task_id": None,
                "total_cost": None,
                "total_tokens": None,
                "step_history": [],
                "design": self.design_name,
            }
        try:
            cost_aggregate = engine.total_cost()
            total_cost = cost_aggregate.get("total_cost", 0.0)
            total_tokens = {
                "input": cost_aggregate.get("total_input_tokens", 0),
                "output": cost_aggregate.get("total_output_tokens", 0),
                "cache_read": cost_aggregate.get("total_cache_read_tokens", 0),
                "cache_write": cost_aggregate.get("total_cache_write_tokens", 0),
                "reasoning": cost_aggregate.get("total_reasoning_tokens", 0),
            }
        except Exception:
            total_cost = 0.0
            total_tokens = None
        try:
            history = engine.step_history()
        except Exception:
            history = []
        return {
            "running": self.task_running,
            "state": engine.state(),
            "current_step": engine.current_step(),
            "task_id": self.task_id,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "step_history": history,
            "design": self.design_name,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_state.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_state.py eda_studio/state.py
git commit -m "feat(state): status_snapshot 加 total_tokens 字段"
```

---

### Task 2: `workflow.py` — 挂载 PricingProvider

**Files:**
- Modify: `eda_studio/workflow.py:185-191`
- Test: `tests/test_workflow.py` (Modify — 加测试)

**Interfaces:**
- Consumes: `build_providers(config)` 返回 `(provider, pricing)`,`pricing` 是 `PricingProvider`(senza)
- Produces: `build_workflow` 返回的 engine 已挂载 pricing,所有 LLM step 自动计价

- [ ] **Step 1: Write the failing test**

Append to `tests/test_workflow.py`:

```python
def test_build_workflow_mounts_pricing(monkeypatch, tmp_path):
    """build_workflow 应挂载 PricingProvider 不报错。

    真实计价需 LLM 调用,单测只验证挂载成功(engine 构造无异常)。
    with_pricing 通过共享 customize_builder 闭包注入,与 with_thinking_level 同链。
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    (tmp_path / "designs" / "uart" / "requirement.md").write_text("# UART")
    (tmp_path / "designs" / "uart" / "design.yaml").write_text(
        "modules:\n  - id: tx\n    name: TX\n    file: uart_tx.v\n"
        "  - id: rx\n    name: RX\n    file: uart_rx.v\n"
        "  - id: top\n    name: Top\n    file: uart.v\n"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    from eda_studio.config import load_config
    from eda_studio.workflow import build_workflow
    import yaml
    config = AppConfig(
        provider_spec={"type": "openai", "api_key": "sk-test", "base_url": None},
        model="gpt-4o",
        pricing_spec={"gpt-4o": {"input_per_mtok": 2.5, "output_per_mtok": 10.0}},
        budget_limit=5.0,
        budget_exceeded_action="stop",
        workflow_config=WorkflowConfig(max_steps=50, max_fix_retries=3),
        shell_config=ShellConfig(allowed_commands=[], denied_args=[]),
        docker_config=DockerConfig(image="", container="", workdir="", pdk=""),
    )
    engine = build_workflow(config, "uart")
    assert engine is not None
```

Note: 检查 `tests/test_workflow.py` 顶部已有的 import,复用 `AppConfig` / `WorkflowConfig` / `ShellConfig` / `DockerConfig`。如果已有 `make_config` helper,用它替代手写 AppConfig。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workflow.py::test_build_workflow_mounts_pricing -v`
Expected: FAIL — `build_workflow` 构造成功(当前代码不挂 pricing 也不报错),但测试可能因其他原因失败。如果直接 PASS,说明挂载与否不影响构造——此时改为验证 `engine` 的 customize_builder 非空(但 senza Python 侧不暴露此字段)。替代:验证 `build_providers` 返回的 pricing 非 None。

如果测试直接 PASS(因为不挂 pricing 也不报错),改为断言 `build_providers` 返回的 pricing 非 None:

```python
def test_build_providers_returns_pricing():
    from eda_studio.workflow import build_providers
    from eda_studio.config import AppConfig, WorkflowConfig, ShellConfig, DockerConfig
    config = AppConfig(
        provider_spec={"type": "openai", "api_key": "sk-test", "base_url": None},
        model="gpt-4o",
        pricing_spec={"gpt-4o": {"input_per_mtok": 2.5, "output_per_mtok": 10.0}},
        budget_limit=5.0,
        budget_exceeded_action="stop",
        workflow_config=WorkflowConfig(max_steps=50, max_fix_retries=3),
        shell_config=ShellConfig(allowed_commands=[], denied_args=[]),
        docker_config=DockerConfig(image="", container="", workdir="", pdk=""),
    )
    provider, pricing = build_providers(config)
    assert pricing is not None
```

- [ ] **Step 3: Write minimal implementation**

Modify `eda_studio/workflow.py:185-191` — 链式调用加 `.with_pricing(pricing)`:

```python
    engine = (
        engine
        .with_task_store(f"designs/{design_name}/.taskstore")
        .with_max_tokens(16384)  # glm-5.2 thinking 动辄 8000+ tokens,8192 全被吃完;adapter timeout 已修复连接超时
        .with_thinking_level("high")  # 与 omp 一致:reasoning_effort=high
        .with_max_retries(config.workflow_config.max_fix_retries)  # judge 返回 "retry" 时的重试上限
        .with_pricing(pricing)  # 挂载 PricingProvider,所有 LLM step 自动计价(Senza #20)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workflow.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regression**

Run: `pytest tests/ -q`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add eda_studio/workflow.py tests/test_workflow.py
git commit -m "feat(workflow): 挂载 PricingProvider via with_pricing (Senza #20)"
```

---

### Task 3: config 补 cache 定价字段 + cli.py 注释更新

**Files:**
- Modify: `config.yaml:8-11`
- Modify: `config.example.yaml:8-11`
- Modify: `eda_studio/cli.py:14-17`

**Interfaces:**
- Consumes: `TokenPrice` 字段(`input_per_mtok` / `output_per_mtok` / `cache_read_per_mtok` / `cache_write_per_mtok`,默认 0.0)
- Produces: config pricing 表完整覆盖 4 个字段

- [ ] **Step 1: Update `config.yaml`**

Replace lines 8-11:

```yaml
pricing:
  glm-5.2:
    input_per_mtok: 2.5
    output_per_mtok: 10.0
    cache_read_per_mtok: 1.25
    cache_write_per_mtok: 2.5
```

- [ ] **Step 2: Update `config.example.yaml`**

Replace lines 8-11:

```yaml
pricing:
  gpt-4o:
    input_per_mtok: 2.5
    output_per_mtok: 10.0
    cache_read_per_mtok: 1.25
    cache_write_per_mtok: 2.5
```

- [ ] **Step 3: Update `eda_studio/cli.py` comments**

Replace lines 14-17:

```python
# 1. WorkflowEngine.total_cost() 返回 dict(含 total_cost 字段),非 float。
#    cmd_run 用 .get("total_cost", 0.0) 取值。PricingProvider 通过
#    WorkflowEngine.with_pricing() 挂载(Senza #20 修复),build_workflow
#    已调用,total_cost 反映真实成本。
```

- [ ] **Step 4: Run tests to verify no regression**

Run: `pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.yaml config.example.yaml eda_studio/cli.py
git commit -m "chore: config 补 cache 定价字段 + cli.py 注释更新"
```

---

### Task 4: `index.html` — 修字段名 bug + 加 token 累加器与辅助函数

**Files:**
- Modify: `static/index.html:27,96,117,208-210,284-300,385-392,420-422,448-453`

**Interfaces:**
- Consumes: `step_finished` event 的 `event.cost`(`CostAggregate` dict),`/api/status` 的 `total_cost` + `total_tokens`
- Produces: 顶栏显示 cost + token 汇总,step card 显示完整 token 分项,页面刷新恢复

此 task 较大,拆为多个 step。无前端测试框架,靠手动验证(Task 5)。

- [ ] **Step 1: Add `#token-display` CSS**

Modify `static/index.html` line 27 — 在 `#cost-display` 样式后加 `#token-display`:

```css
        #cost-display { font-family: monospace; color: #0f3460; background: #e94560; padding: 2px 8px; border-radius: 4px; color: #fff; }
        #token-display { font-family: monospace; font-size: 12px; color: #aaa; background: #1a1a2e; padding: 2px 8px; border-radius: 4px; }
```

- [ ] **Step 2: Add `#token-display` HTML element**

Modify `static/index.html` line 96 — 在 `#cost-display` 后加 `#token-display`:

```html
        <span id="cost-display">$0.0000</span>
        <span id="token-display"></span>
```

- [ ] **Step 3: Add `totalTokens` JS state**

Modify `static/index.html` line 117 — 在 `let totalCost = 0;` 后加:

```javascript
        let totalCost = 0;
        let totalTokens = { input: 0, output: 0, cache_read: 0, cache_write: 0, reasoning: 0 };
```

- [ ] **Step 4: Rewrite `updateCostDisplay()` + add `formatTokenMeta()`**

Modify `static/index.html` lines 208-210 — 替换 `updateCostDisplay` 并加辅助函数:

```javascript
        function updateCostDisplay() {
            document.getElementById('cost-display').textContent = '$' + totalCost.toFixed(4);
            const parts = [];
            if (totalTokens.input) parts.push(`in: ${totalTokens.input.toLocaleString()}`);
            if (totalTokens.output) parts.push(`out: ${totalTokens.output.toLocaleString()}`);
            if (totalTokens.cache_read) parts.push(`cache_r: ${totalTokens.cache_read.toLocaleString()}`);
            if (totalTokens.cache_write) parts.push(`cache_w: ${totalTokens.cache_write.toLocaleString()}`);
            document.getElementById('token-display').textContent = parts.join('  ');
        }

        function formatTokenMeta(cost) {
            if (!cost) return '';
            const parts = [];
            if (cost.total_input_tokens > 0) parts.push(`in: ${cost.total_input_tokens.toLocaleString()}`);
            if (cost.total_output_tokens > 0) parts.push(`out: ${cost.total_output_tokens.toLocaleString()}`);
            if (cost.total_cache_read_tokens > 0) parts.push(`cache_r: ${cost.total_cache_read_tokens.toLocaleString()}`);
            if (cost.total_cache_write_tokens > 0) parts.push(`cache_w: ${cost.total_cache_write_tokens.toLocaleString()}`);
            if (cost.total_reasoning_tokens > 0) parts.push(`reasoning: ${cost.total_reasoning_tokens.toLocaleString()}`);
            if (cost.total_cost > 0) parts.push(`$${cost.total_cost.toFixed(4)}`);
            return parts.join('  ');
        }
```

- [ ] **Step 5: Fix `step_finished` handler — field names + token accumulation**

Modify `static/index.html` lines 290-294 — 替换 cost 处理 + meta 生成:

```javascript
                const cost = event.cost;
                if (cost) {
                    if (cost.total_cost) totalCost += cost.total_cost;
                    totalTokens.input += cost.total_input_tokens || 0;
                    totalTokens.output += cost.total_output_tokens || 0;
                    totalTokens.cache_read += cost.total_cache_read_tokens || 0;
                    totalTokens.cache_write += cost.total_cache_write_tokens || 0;
                    totalTokens.reasoning += cost.total_reasoning_tokens || 0;
                }
                updateCostDisplay();
                let meta = formatTokenMeta(cost);
```

- [ ] **Step 6: Fix step card meta in `renderStepView`**

Modify `static/index.html` lines 420-422 — 替换 meta 生成:

```javascript
            // cost
            const meta = formatTokenMeta(s.cost);
            const metaHtml = meta ? `<div class="step-meta">${meta}</div>` : '';
```

然后修改 line 433 的 `${meta}` → `${metaHtml}`。找到 step card 模板末尾:

```javascript
                    <div class="step-output">${linesHtml}${extra}</div>
                    ${metaHtml}
```

- [ ] **Step 7: Reset `totalTokens` in `submitTask`**

Modify `static/index.html` lines 226-227 — 在 `totalCost = 0;` 后加:

```javascript
                    totalCost = 0;
                    totalTokens = { input: 0, output: 0, cache_read: 0, cache_write: 0, reasoning: 0 };
                    updateCostDisplay();
```

- [ ] **Step 8: Restore token/cost from `/api/status` on page load**

Modify `static/index.html` lines 448-453 — 替换页面加载逻辑:

```javascript
        // 页面加载时同步一次状态
        fetch('/api/status').then(r => r.json()).then(s => {
            if (s.running) {
                document.getElementById('submit-btn').disabled = true;
                connectWS();
            }
            if (s.total_cost != null) totalCost = s.total_cost;
            if (s.total_tokens) totalTokens = s.total_tokens;
            updateCostDisplay();
        });
```

- [ ] **Step 9: Commit**

```bash
git add static/index.html
git commit -m "feat(webui): 显示每步/总 token 用量 + 真实成本,修字段名 bug"
```

---

### Task 5: 端到端手动验证

**Files:** 无文件改动,纯验证

- [ ] **Step 1: Run unit tests**

Run: `pytest tests/ -q`
Expected: All PASS

- [ ] **Step 2: Verify `with_pricing` is available**

Run: `python -c "import senza; print(hasattr(senza.WorkflowEngine, 'with_pricing'))"`
Expected: `True`

- [ ] **Step 3: Start server and run uart workflow**

```bash
eda-studio serve
```

Open browser, select `uart`, click 运行.

Expected:
- 顶栏显示 `$0.0000` + `in: ... out: ...`(随 step_finished 累加)
- step card 的 `.step-meta` 显示 `in: 34,499  out: 3,512  $0.0000`(LLM step)
- executor step(simulate/synthesize 等)不显示 `.step-meta`(cost 全 0)
- `total_cost` 非 0(pricing 挂载生效)

- [ ] **Step 4: Verify page refresh restores state**

During workflow run, refresh the page.
Expected: 顶栏 cost + token 从 `/api/status` 恢复,不丢

- [ ] **Step 5: Final commit (if any fixups needed)**

如果验证中发现问题,修复后提交。否则无需额外 commit。
