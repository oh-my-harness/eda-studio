# Token 用量与成本显示

- **Issue**: [#5 — webui: 显示每步和总的 token 用量(输入/输出/cache)](https://github.com/oh-my-harness/eda-studio/issues/5)
- **日期**: 2026-07-21
- **状态**: 已确认,待实现
- **关联**: [Senza #20](https://github.com/oh-my-harness/Senza/issues/20)(`WorkflowEngine.with_pricing` 已修复并装入 venv)

## 背景

WebUI 顶栏只显示总成本 `$0.000`,且 `total_cost` 因 `PricingProvider` 未挂载到 `WorkflowEngine` 一直为 0(Senza #20 已解除此限制)。`step_finished` event 携带的完整 token 用量数据(`CostAggregate`)在前端只用了 `input_tokens` / `output_tokens` 两个字段——而且字段名还是错的(真实字段名是 `total_input_tokens` / `total_output_tokens`),所以 step meta 一直静默不显示。

### 已验证的数据结构

从 `designs/uart/.taskstore/.../workflow.json` 实测,`event.cost` / `engine.total_cost()` 字段:

```json
{
  "total_input_tokens": 34499,
  "total_output_tokens": 3512,
  "total_cache_read_tokens": 0,
  "total_cache_write_tokens": 0,
  "total_reasoning_tokens": 0,
  "total_cost": 0.0,
  "by_model": {}
}
```

### 字段名 bug

前端 `static/index.html` 当前读 `cost.input_tokens` / `cost.output_tokens`(line 294、422),这两个字段不存在。真实字段名是 `total_input_tokens` 等。所以 step card 的 `.step-meta` 一直静默不显示。本次改动修复。

### Senza #20 已修复

`WorkflowEngine.with_pricing(provider)` 已实现(`Senza/src/pyworkflow.rs:1251`),通过 `set_customize_builder` 注入共享闭包 `|b| b.pricing(p)`,所有 LLM step 自动继承,executor step 不受影响(它们不构造 harness)。已通过 `scripts/install-senza-dev.sh` 装入 eda-studio venv。

`build_providers`(`workflow.py:33-46`)已返回 `(provider, pricing)`,但 `build_workflow` 拿到了 pricing 却没挂(line 115 取了 `pricing`,line 185-191 链式调用没调 `with_pricing`)。

## 目标

1. 挂载 `PricingProvider`,让 `total_cost` 反映真实成本
2. 修复前端字段名 bug
3. 每步 step card 显示完整 token 分项(非零项)
4. 顶栏并排显示 cost + token 汇总
5. `/api/status` 返回 `total_tokens`,刷新页面可恢复

## 需求

### 范围

| 文件 | 改动 |
|------|------|
| `eda_studio/workflow.py` | `build_workflow` 链式调用加 `.with_pricing(pricing)` |
| `eda_studio/state.py` | `status_snapshot()` 加 `total_tokens` 字段 |
| `eda_studio/cli.py` | 更新 line 14-17 过时注释 |
| `config.yaml` / `config.example.yaml` | pricing 表补 `cache_read_per_mtok` / `cache_write_per_mtok` |
| `static/index.html` | 修字段名 bug + 显示每步/总 token + 显示真实成本 |
| `tests/test_state.py` | 新建,覆盖 `total_tokens` 字段 |
| `tests/test_workflow.py` | 加 `with_pricing` 挂载验证 |

不动 workflow/judge/executor 逻辑。

### 非目标

- 不改 `WorkflowEvent` payload 结构(后端已全量吐出,纯前端展示问题)
- 不加 budget hook 逻辑(budget 已有,本次只补 pricing 挂载)

## 设计

### 后端

#### `workflow.py` — 挂载 PricingProvider

`build_workflow` 的链式调用(line 185-191)加一行:

```python
engine = (
    engine
    .with_task_store(f"designs/{design_name}/.taskstore")
    .with_max_tokens(16384)
    .with_thinking_level("high")
    .with_max_retries(config.workflow_config.max_fix_retries)
    .with_pricing(pricing)  # 挂载 PricingProvider,所有 LLM step 自动计价
)
```

**调用顺序**:`with_pricing` 内部用 `set_customize_builder` 注入共享闭包(`pyworkflow.rs:1271-1275`),`with_step_builder` 是 per-step 闭包,在共享闭包之后应用(`runner.rs:831-833`)。`with_pricing` 必须在 `_register_engine`(含 `with_step_builder`)之前调用——当前链式顺序已满足(line 193 `_register_engine` 在最后)。

`with_thinking_level` 也是共享闭包(`pyworkflow.rs:1294`),与 `with_pricing` 同链。`with_pricing` 实现保留了 prev 闭包(`pyworkflow.rs:1271` `let prev = engine.config_customize_builder().clone()`),两者可叠加,不冲突(一个改 thinking_level,一个改 pricing,字段不同)。

#### `state.py` — `status_snapshot()` 加 `total_tokens`

```python
def status_snapshot(self) -> dict:
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

#### `config.yaml` / `config.example.yaml` — pricing 表补 cache 字段

```yaml
pricing:
  glm-5.2:
    input_per_mtok: 2.5
    output_per_mtok: 10.0
    cache_read_per_mtok: 1.25
    cache_write_per_mtok: 2.5
```

`TokenPrice` 字段默认 0.0(`llm-harness-types/src/cost.rs:6-15`),不补也能跑,但 cache 有数据时会被计为 0 成本。补上以备 provider 解析出 cache 时自动计价。

#### `cli.py` 注释更新

line 14-17 改为:

```
1. WorkflowEngine.total_cost() 返回 dict(含 total_cost 字段),非 float。
   cmd_run 用 .get("total_cost", 0.0) 取值。PricingProvider 通过
   WorkflowEngine.with_pricing() 挂载(Senza #20 修复),build_workflow
   已调用,total_cost 反映真实成本。
```

### 前端(`static/index.html`)

#### 修字段名 bug

两处 `cost.input_tokens` / `cost.output_tokens` → `cost.total_input_tokens` / `cost.total_output_tokens`:
- line 294(event timeline meta)
- line 422(step card meta)

#### 顶栏:并排显示 cost + token 汇总

**HTML**(line 96 附近):把单个 `#cost-display` 换成并排两元素:

```html
<span id="cost-display">$0.0000</span>
<span id="token-display" class="token-summary"></span>
```

**CSS**:加 `#token-display` 样式:

```css
#token-display { font-family: monospace; font-size: 12px; color: #aaa; background: #1a1a2e; padding: 2px 8px; border-radius: 4px; }
```

**JS state**(line 117 附近):加 `totalTokens` 累加器:

```javascript
let totalCost = 0;
let totalTokens = { input: 0, output: 0, cache_read: 0, cache_write: 0, reasoning: 0 };
```

**`updateCostDisplay()`**(line 208):同时更新 cost 和 token:

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
```

#### `formatTokenMeta(cost)` 辅助函数(新加)

```javascript
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

executor step 的 cost 全 0 → `formatTokenMeta` 返回空串 → 不显示 meta(满足"全 0 不显示"要求)。

#### `step_finished` 事件处理(line 290-294)

修字段名 + 累加 token + 生成完整 meta:

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

#### step card meta(line 420-422)

用同一个 `formatTokenMeta`:

```javascript
const meta = formatTokenMeta(s.cost);
const metaHtml = meta ? `<div class="step-meta">${meta}</div>` : '';
```

#### 页面加载恢复状态(line 448-453)

从 `/api/status` 的 `total_cost` + `total_tokens` 恢复:

```javascript
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

#### `submitTask` 重置(line 226-227)

提交新任务时重置 token 累加器:

```javascript
totalCost = 0;
totalTokens = { input: 0, output: 0, cache_read: 0, cache_write: 0, reasoning: 0 };
updateCostDisplay();
```

### 测试

#### `tests/test_state.py`(新建)

```python
from eda_studio.state import AppState

class FakeEngine:
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
    def state(self): return "running"
    def current_step(self): return "rtl_tx"
    def step_history(self): return []

def test_status_snapshot_includes_total_tokens():
    s = AppState()
    s.engine = FakeEngine()
    s.task_running = True
    snap = s.status_snapshot()
    assert snap["total_cost"] == 0.0025
    assert snap["total_tokens"] == {
        "input": 100, "output": 50,
        "cache_read": 10, "cache_write": 5, "reasoning": 0,
    }

def test_status_snapshot_idle_total_tokens_none():
    s = AppState()
    snap = s.status_snapshot()
    assert snap["total_tokens"] is None
    assert snap["total_cost"] is None
```

#### `tests/test_workflow.py`(已有)

加 `with_pricing` 挂载验证:验证 `build_workflow` 返回的 engine 不报错(挂载成功)。真实计价靠端到端验证(单测里用 mock 无法证明 cost 非 0)。

## 验证计划

1. **单测**:`pytest tests/test_state.py tests/test_workflow.py -q` 绿
2. **字段名 bug 修复确认**:启动 `eda-studio serve`,跑 uart workflow,确认 step card 的 `.step-meta` 显示 token 分项(之前一直空)
3. **顶栏 token 汇总**:确认顶栏显示 `$0.0000 | in: 84,356  out: 8,902`
4. **真实成本**:pricing 表挂载后,`total_cost` 非 0(需真实 LLM 调用)
5. **页面刷新恢复**:workflow 运行中刷新页面,顶栏 token/cost 从 `/api/status` 恢复
6. **executor step 无 meta**:simulate/synthesize 等 step 的 cost 全 0,step card 不显示 `.step-meta`
