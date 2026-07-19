# 开发笔记

EDA Studio 开发期诊断笔记。记录 executor bug 修复历程、PDK 路径踩坑、senza API 偏差等。

## Executor 修复历程

### simulate executor
- **sim_out 路径**:verilator `--binary -o sim_out` 产出在 `obj_dir/sim_out` 不是 `sim_dir/sim_out`。之前跑 `./sim_out` → returncode=127 → success=False → 误触发 debug_fix。修复为 `./obj_dir/sim_out`。
- **verilator -Wno-fatal**:避免无害 warning(TIMESCALEMOD 等)导致 simulate 失败。

### synthesize executor
- yosys `-p "cmd; cmd"` 的分号被 `shell_safety.denied_args` 拦截 → script 写文件用 `-s`(yosys script 模式)
- `synth` 无 PDK 映射 → `$_NOT_` 等 generic cell,openroad 不认 → 加 `dfflibmap -liberty` + `abc -liberty`
- `write_verilog` 属性/reg 声明 openroad 不认 → `-noattr -noexpr`
- PDK liberty 路径用 `docker exec ls` 查找

### pnr executor
- 缺 tech LEF(`.tlef`)→ layers/sites undefined → 先 `read_lef tlef` 再 macro LEF
- `read_libs` → `read_liberty`(openroad 命令名)
- 层名 `metal2/metal3` → `met2/met3`(sky130 命名)
- met2 是垂直方向 → 交换 `-hor_layers`/`-ver_layers`
- 缺 `make_tracks` → `place_pins` 报 no tracks
- 缺 `-core_space` → IFP-0034
- 去掉 `detailed_route`(DRT-0305 special nets 问题)
- openroad 不认 `-cmd` → tcl 脚本文件位置参数

### drc executor
- magic 不认 `-cmd` → tcl 脚本文件
- magic 需先 `lef read`(tech+macro)再 `def read`
- `drc count total` 输出判成功

### gds executor
- klayout 不认 `-cmd` → `-r` ruby 脚本
- `RBA::Layout` API read LEF + DEF, write GDS
- tech LEF(`.tlef`)klayout 不认,只读 macro LEF(有 dummy macro warning 但产出 GDS)

### render executor
- `set_active_layer` 在 klayout 0.30.9 不存在(NoMethodError)→ 去掉,`show_layout` + `zoom_fit` + `save_image` 足够

## PDK 路径

- sky130 PDK 路径模式:`/foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd/{lib,lef,techlef}/`
- tech LEF 是 `.tlef` 文件,含 LAYER/SITE 定义
- sky130 layer 命名:`met1/met2/met3`(不是 `metal1/metal2/metal3`),met2 是垂直方向

## docker exec [INFO] 行污染

容器 login profile 打印 `[INFO] Final PATH variable: ...` 混入 stdout。所有从 docker exec 解析路径的地方都要过滤 `l.startswith("[INFO]")`。

## senza API 偏差(以实际 pyi/runtime 为准)

1. `create_tool` 的 `parameters_schema` 形参类型是 str(JSON 字符串),不是 dict。传 dict 会 TypeError;用 `json.dumps` 序列化。
2. workflow_dict 的 edges 中 `to` 必须指向 steps 里已声明的 step_id;没有 `done` 这个内置终止 step。终止由 judge 返回 `"done"` / `"abort:done"` / `"fail:<reason>"` 实现。
3. `WorkflowEngine.total_cost()` 返回 dict(含 `total_cost` 字段),非 float。
4. `set_context_variable` 要求 JSON 可序列化值,dataclass 实例(DockerConfig/ShellConfig)无法直接序列化,转 dict。
5. `with_max_tokens(32768)` 必须:glm-5.2 thinking ~8K token,默认 8192 会截断导致 content/tool_call 无法输出。

## 空响应问题(已修复)

- **FinalAnswerMode::Heuristic** 把 EndTurn(空 text)分类为 FinalAnswer,`final_answer_output = Some("")` 覆盖 `text_delta_output`。
- **judge 用 `tool_calls_count > 0` 判断完成**:`output` 被 FinalAnswer 空文本覆盖不可靠。没调工具 → retry;耗尽 → abort:done。
- **should_stop + transform_context 组合**:turn 0 EndTurn 且无 tool_use → 返回 False(继续 turn)+ 标记。transform_context 检测标记 → 往 messages 追加 nudge。每个 step 最多 nudge 一次。

## budget should_stop hook(已去掉)

`budget_should_stop` 返回 `false` → runtime 强制继续 turn → 无限重试。`should_stop=false` 语义是"强制继续 turn"不是"不超预算"。修复:去掉所有 budget should_stop hook。

## WS 事件结构

`step_finished` 事件 payload:`{type, step_id, output, structured, tool_calls_count}`。
- LLM step 的 `structured` 为 null
- EXEC step 的 `structured` 为 `{success: bool, ...}`
- 无 `cost` 字段(前端读 `event.cost` 拿到 undefined,不影响)

taskstore `workflow.json` 的 `step_history` 更完整:每项有 `result.{output, structured, tool_calls_count, cost, session_id, ...}`。
