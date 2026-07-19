# EDA Studio 可见性 + Web UI + Workflow 细化设计

日期: 2026-07-19

## 背景

`python -m eda_studio run uart` 用 glm-5.2 时卡住 13 分钟无输出。排查确认根因:

**glm-5.2 的 thinking 约 8K token,senza 默认 `max_tokens=8192` 不够,thinking 没结束就触发 MaxTokens 截断,导致 content 和 tool_call 无法输出。** 同仓库的 blender-scene-generator 已踩过此坑,在 `main.py:239-241` 留下注释并调用 `engine.with_max_tokens(32768)` 修复。

次要原因: `rtl_design` 单 step 让模型一次设计完整 UART(TX+RX+顶层),prompt 复杂 → reasoning 链极长(实测 15697 字符 / ~5500 token,87 秒)。

当前 `cmd_run` 直接调 `engine.run()` 阻塞,期间零输出,无法观察进度。

## 目标

1. 修复 max_tokens 截断根因。
2. workflow 细化: `rtl_design` 拆成 `rtl_tx` → `rtl_rx` → `rtl_top` 3 步,缩短单步 reasoning。
3. CLI 可见性: `run` 改成后台线程跑 `engine.run()`,主线程迭代 `engine.subscribe()` 实时打印事件。
4. Web UI(仿 blender-scene-generator): FastAPI + WebSocket + 单页前端,实时显示 workflow 进度。

## 设计

### 1. max_tokens 修复

`eda_studio/workflow.py` 的 `build_workflow` 链式构建中加 `.with_max_tokens(32768)`。

### 2. workflow 细化

`rtl_design` 拆成 3 步:

| step_id | name | 产出 | allowed_tools |
|---------|------|------|---------------|
| rtl_tx | UART 发送器设计 | rtl/uart_tx.v | write_rtl, read_rtl, list_design_files |
| rtl_rx | UART 接收器设计 | rtl/uart_rx.v | write_rtl, read_rtl, list_design_files |
| rtl_top | 顶层模块设计 | rtl/uart.v(例化 tx+rx) | write_rtl, read_rtl, list_design_files |

prompts: 每个 step 只描述该模块的接口和约束,不一次性给完整需求。rtl_tx/rx 给模块级接口,rtl_top 给顶层例化要求并提示参考已写的 tx/rx。

judge 路由:
- `rtl_tx` → `to:rtl_rx`(有 output)/ `abort:done`(无)
- `rtl_rx` → `to:rtl_top`(有 output)/ `abort:done`(无)
- `rtl_top` → `to:simulate`(有 output)/ `abort:done`(无)

edges 新增: `rtl_tx→rtl_rx`, `rtl_rx→rtl_top`, `rtl_top→simulate`。删除 `rtl_design→simulate`。

### 3. CLI 可见性

`__main__.py` 的 `cmd_run`:
- 后台线程跑 `engine.run()`
- 主线程迭代 `engine.subscribe(timeout_ms=1000)`,打印事件:
  - `step_started`: `▶ <step_name> 开始`
  - `step_progress.tool_call_start`: `  🔧 调用工具: <name>`
  - `step_progress.tool_execution_end`: `  ✓ 工具完成` / `  ✗ 工具失败: <error>`
  - `step_finished`: `✓ <step_name> 完成`
  - `failed`: `✗ 失败: <error>`
- engine.run() 结束后打印总结(state/cost/step_history/GDS 产物)

### 4. Web UI

#### 4.1 server.py (FastAPI)

路由(仿 blender,裁剪 EDA 不需要的):
- `POST /api/task` — body: `{design: "uart"}`,启动 workflow,返回 202;409 if running
- `GET /api/status` — 返回 `{running, state, current_step, task_id, total_cost, step_history}`
- `GET /api/report/{step}` — 返回对应 step 的报告文件内容(sim/report.txt, pnr/drc.rpt 等)
- `WS /ws` — 转发 WorkflowEvent

#### 4.2 state.py (AppState)

字段: `task_running`, `engine`, `event_iterator`, `task_id`, `design_name`。
方法: `status_snapshot()`, `clear_active_task()`。

#### 4.3 main.py

`serve` 子命令入口:
- 加载 config
- 构建 provider(从环境变量,仿 blender main.py:208-231)
- 启动 uvicorn(host=0.0.0.0, port=3000)
- `workflow_runner(state, design_name)` 在后台线程: build_workflow → subscribe → engine.run()

#### 4.4 static/index.html

三栏布局(仿 blender):
- 左: workflow 流程图(10 个 step 节点:rtl_tx/rtl_rx/rtl_top/simulate/debug_fix/synthesize/pnr/drc_fix/drc/gds),高亮当前 step
- 中: step 输出区(step_finished 显示 output 摘要,EDA 报告链接)
- 右: 事件时间线

顶栏: design 选择(默认 uart)、Generate 按钮、当前 step、cost、状态徽章。

#### 4.5 __main__.py 新增 serve 子命令

```
python -m eda_studio serve [--config config.yaml] [--port 3000]
```

## 改动文件

| 文件 | 改动 |
|------|------|
| eda_studio/workflow.py | +with_max_tokens(32768);rtl_design 拆 3 步;edges 调整 |
| eda_studio/prompts.py | 新增 RTL_TX_PROMPT / RTL_RX_PROMPT / RTL_TOP_PROMPT;build_prompts 返回新 key |
| eda_studio/judge.py | rtl_tx/rtl_rx/rtl_top 路由;删除 rtl_design |
| eda_studio/__main__.py | cmd_run 后台线程+subscribe;新增 cmd_serve + argparse |
| eda_studio/server.py | 新建:FastAPI 路由 |
| eda_studio/state.py | 新建:AppState |
| eda_studio/main.py | 新建:serve 入口 + workflow_runner |
| static/index.html | 新建:单页 UI |
| tests/test_workflow.py | 更新 step 数量断言 |
| tests/test_prompts.py | 更新 prompt key 断言 |
| tests/test_judge.py | 更新 rtl_tx/rtl_rx/rtl_top 路由测试,删除 rtl_design |
| tests/test_cli.py | 新增 serve 子命令测试 |
| pyproject.toml | +fastapi, +uvicorn[standard], +websockets |
| config.example.yaml | 无改动(max_tokens 在代码里,非配置) |

## 验收

1. `python -m eda_studio run uart` 不再卡住,实时打印 step/tool 事件,最终产出 GDS 或报错。
2. `python -m eda_studio serve` 启动后浏览器访问 localhost:3000,能看到 workflow 流程图,提交 uart 任务后实时看到 step 推进和事件。
3. 所有测试通过。
