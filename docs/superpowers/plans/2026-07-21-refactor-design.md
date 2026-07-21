# 重构计划:eda-studio 结构整理与代码质量

> 日期:2026-07-21
> 规格:[`docs/superpowers/specs/2026-07-21-refactor-design.md`](../specs/2026-07-21-refactor-design.md)
> 范围:方案 B(结构整理 + 代码质量,不动核心 workflow/judge/executor 领域逻辑)
> 验证:75 tests green + 重跑 uart/i2c 端到端 RTL→GDS

---

## 任务依赖与并行性

```
Phase 1 (可并行,4 个独立文件级任务):
  T1 死代码清理(eda_studio/agents/, budget.py, .superpowers/, egg-info)
  T2 CLI 三文件合并(__main__.py + cli_commands.py + main.py → cli.py)
  T3 executor 公共逻辑提取(executors/base.py)
  T4 workflow 构建 vs restore 去重(_register_engine)

Phase 2 (依赖 Phase 1 完成):
  T5 README + 文档重写(反映新结构)
  T6 CLAUDE.md / CONTRIBUTING.md 更新(反映新结构)
  T7 代码自解释(补/修注释,删过时注释)

Phase 3 (依赖 Phase 1+2):
  T8 验证:pytest 全绿 + 重跑 uart + i2c
```

---

## Phase 1: 结构整理(4 个任务,可并行)

### T1 死代码清理

**目标**:删除 spec §1 列出的死代码与冗余目录。

**改动**:
1. 删除 `eda_studio/agents/`(整个目录,死代码,无 import 引用)
2. 删除 `eda_studio/budget.py`(14 行,`make_budget_cb` 未被 `build_workflow` 调用)
3. 删除 `eda_studio.egg-info/`(构建产物,应 gitignore)
4. 删除 `.superpowers/`(空的或过时的 skill 脚手架)
5. 删除 `eda_studio/tools/`、`eda_studio/rules.py`(若仍存在;summary 说已删,确认)
6. 更新 `.gitignore`:加 `*.egg-info/` 已有,确认 `eda_studio.egg-info/` 被忽略

**测试影响**:
- `tests/test_hooks_rules_budget.py` 第 2 行 `from eda_studio.budget import make_budget_cb`、3 个 budget 测试(test_budget_cb_*)需删除
- 保留 `make_hooks`、`make_max_tokens_continue_hook` 的测试,文件改名 `test_hooks.py`

**验证**:
- `pytest tests/ -q` 绿
- `grep -r "from eda_studio.budget\|from eda_studio.agents\|import budget"` 无命中
- `python -c "import eda_studio"` 无报错

**风险**:
- 若 `make_budget_cb` 实际被某处调用(需 grep 确认),则不删,改为保留 + 文档说明。预期:无调用点。

---

### T2 CLI 三文件合并 → `cli.py`

**目标**:合并 `__main__.py`(316 行) + `cli_commands.py`(cmd_init/cmd_check) + `main.py`(serve 入口)为单一 `eda_studio/cli.py`,减少入口分散。

**改动**:
1. 新建 `eda_studio/cli.py`,内容 = `__main__.py` 全部 + `cli_commands.py` 的 `cmd_init`/`cmd_check` + `main.py` 的 `run_server`
2. `__main__.py` 改为 3 行 stub:`from .cli import main; main()`(保 `python -m eda_studio` 入口)
3. 删除 `cli_commands.py`、`main.py`
4. 修复 `cmd_run` 硬编码 bug:第 224 行 `gds/uart.gds` → `gds/{design_name}.gds`
5. `pyproject.toml` 的 `[project.scripts]` 保持 `eda-studio = "eda_studio.__main__:main"`(或改指向 `cli:main`,二选一,保 `python -m eda_studio` 和 `eda-studio` 都能跑)

**测试影响**:
- `tests/test_cli.py`:第 3 行 `from eda_studio.__main__ import main`、第 19/27/34 行 `patch("eda_studio.__main__.cmd_run")` 等 —— 改为 `from eda_studio.cli import main` + `patch("eda_studio.cli.cmd_run")`
- `tests/test_cli_commands.py`:第 11/25/33/41/72 行 `from eda_studio.cli_commands import cmd_init/cmd_check` —— 改为 `from eda_studio.cli import cmd_init/cmd_check`
- `tests/test_run_summary.py`:第 32/44 行 `from eda_studio.__main__ import _print_run_summary` —— 改为 `from eda_studio.cli import _print_run_summary`

**验证**:
- `pytest tests/test_cli.py tests/test_cli_commands.py tests/test_run_summary.py -q` 绿
- `eda-studio init uart`(在 tmp dir)能跑
- `python -m eda_studio --help` 能跑

**风险**:
- `main.py` 若被 `pyproject.toml` 的 `[project.scripts]` 或 `[tool.setuptools]` 引用,需同步更新。需 grep 确认。
- `server.py` import `from .main import run_server`?需确认 main.py 的实际内容。

---

### T3 executor 公共逻辑提取 → `executors/base.py`

**目标**:提取 6 个 executor 共享的 preamble(design_dir/docker_cfg/shell_cfg 提取 + load_design_config)和 PDK 路径查找逻辑,减少重复。

**改动**:
1. 新建 `eda_studio/executors/base.py`,提供:
   ```python
   @dataclass
   class ExecutorContext:
       design_dir: Path
       docker_config: DockerConfig
       shell_config: ShellConfig
       dcfg: DesignConfig

       @classmethod
       def from_ctx(cls, ctx: dict) -> "ExecutorContext":
           """从 executor ctx 字典提取公共字段。"""

   def find_pdk_lib(docker_config, lib_name: str = "sky130_fd_sc_hd") -> str:
       """docker exec ls 查 PDK 标准单元库目录,返回容器内绝对路径。"""

   def find_pdk_files(docker_config, patterns: list[str]) -> dict[str, str]:
       """按扩展名(.lib/.lef/.tlef/.gds)查 PDK 文件,返回 {ext: path}。"""

   def filter_info_lines(stdout: str) -> str:
       """过滤 [INFO] 行,返回干净输出。"""
   ```
2. 改造 6 个 executor:`synthesize.py`/`pnr.py`/`drc.py`/`gds.py` 用 `ExecutorContext.from_ctx` + `find_pdk_lib`/`find_pdk_files`;`simulate.py`/`render.py` 用 `ExecutorContext.from_ctx`(无 PDK 查找)
3. **不改 executor 的业务逻辑**(命令构造、report 解析、success 判断、timeout 处理全部保留)
4. `executors/__init__.py` 导出 `ExecutorContext`

**测试影响**:
- `tests/test_executors.py` 的 `make_ctx` helper 仍可用(ctx 结构不变)
- `fake_pdk_find` mock 目标 `subprocess.run` 不变(因 `find_pdk_lib` 内部仍调 `subprocess.run`)
- 所有 executor 测试应无需改 test 逻辑即通过

**验证**:
- `pytest tests/test_executors.py -q` 绿(不改测试)
- 6 个 executor 的成功/失败/timeout/safety_error 用例全过

**风险**:
- `find_pdk_lib`/`find_pdk_files` 的返回结构必须与现有 executor 内联代码的期望严格一致。需逐个 executor 对照现有 glob pattern:
  - synthesize:`/foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd` + `.lib`
  - pnr:`.lib` + `.lef` + `.tlef`
  - drc:`.gds`
  - gds:`.gds`
- mock `fake_pdk_find` 返回 4 行路径,现有 executor 按扩展名拆分。提取后 `find_pdk_files` 必须保持相同拆分逻辑。

---

### T4 workflow 构建 vs restore 去重 → `_register_engine`

**目标**:`build_workflow`(workflow.py)和 `cmd_restore`(__main__.py → cli.py)都注册 executor/plugin/hooks/context_var,逻辑重复。提取 `_register_engine(engine, config, design_name, rtl_ids)` 复用。

**改动**:
1. 在 `workflow.py` 新增 `_register_engine(engine, config, design_name, rtl_ids) -> engine`:
   - 注册 7 个 executor(simulate/synthesize/pnr/drc/gds/render/shell)
   - 注册 hooks(`_wrap_hooks(make_hooks(config))` + max_tokens + provider logger + system_prompt)
   - 注册 FsToolsPlugin 到 rtl_ids + debug_fix/drc_fix
   - set_context_variable(design_dir/docker_config/shell_config)
2. `build_workflow` 构建新 engine 后调 `_register_engine`
3. `cmd_restore` restore 出 engine 后调 `_register_engine`
4. 删除 `cmd_restore` 里的 `_re_register`(逻辑搬到 `_register_engine`)

**测试影响**:
- `tests/test_workflow.py`:2 个测试只检查 engine 可构建 + context_var 设置,不依赖内部结构 → 应无需改
- 无 restore 的专门测试(summary 未提及),需 grep 确认

**验证**:
- `pytest tests/test_workflow.py -q` 绿
- `pytest tests/ -q` 全绿

**风险**:
- restore 后的 engine 是否能再次 `with_executor`/`with_hooks`?需确认 Senza API:restore 返回的 engine 是否支持 builder 方法。预期:支持(builder pattern 返回新 engine)。
- 若 restore 的 engine 不支持 `with_step_plugin`(因 taskstore 已序列化 plugin 状态),则 `_register_engine` 对 restore 路径要跳过 plugin 注册。需测试确认。

---

## Phase 2: 文档与注释(依赖 Phase 1)

### T5 README 重写

**目标**:README 服务两类读者(Senza SDK 用户 + EDA 关注者),讲清 eda-studio 与 Senza 的关系,不提 runtime。

**改动**:
1. 重写 `README.md`,结构:
   - **What is EDA Studio**:一句话定位(Senza 的教学项目,用 LLM + 开源 EDA 工具跑通 RTL→GDS)
   - **EDA Studio vs Senza**:对照表
     | | Senza | EDA Studio |
     |---|---|---|
     | 定位 | Python SDK(WorkflowEngine + judge + executor + hooks) | 基于 Senza 的端到端 EDA 应用 |
     | 仓库 | oh-my-harness/Senza | 本仓库 |
     | 安装 | `pip install senza-sdk` | `pip install -e .`(消费 senza-sdk) |
     | 关系 | 上游 SDK | 下游消费者/教学示例 |
   - **Quickstart**:init → check → run(3 步,含 docker 启动)
   - **Workflow**:RTL→仿真→综合→PnR→DRC→GDS 流程图(mermaid)
   - **Project Structure**:简述 `eda_studio/` 各文件职责(反映 Phase 1 新结构)
   - **Limitations**:教学项目,不追求 PPA,只支持 Sky130
2. 删除 README 中过时的 "runtime"/"G1/G2/G3" 引用(若有)

**验证**:
- README 无 "runtime" 字样
- README 有 Senza vs EDA Studio 对照表
- README Quickstart 可复制粘贴跑通(在干净 tmp dir)

---

### T6 CLAUDE.md / CONTRIBUTING.md 更新

**目标**:反映 Phase 1 新结构。

**改动**:
1. `CLAUDE.md`:
   - 第 177 行 `eda_studio/main.py — serve 入口` → `eda_studio/cli.py — serve 入口(合并后)`
   - 第 159 行 "shell_safety 白名单" 描述保留(仍准确)
   - 确认无 "budget.py"/"agents/" 引用
2. `CONTRIBUTING.md`:
   - 第 10 行 `pip install -e .` 保留
   - "加 Executor" 第 4 步 `eda_studio/workflow.py` → 保留(仍准确)
   - 确认无 `cli_commands.py`/`main.py` 引用

**验证**:
- `grep -r "cli_commands\|eda_studio.main\|budget.py\|agents/" CLAUDE.md CONTRIBUTING.md` 无命中

---

### T7 代码自解释

**目标**:补/修注释,删过时注释,让代码自解释。

**改动**:
1. 扫描 `eda_studio/` 所有文件,删除引用已删模块的注释(如 "见 budget.py"、"本地文件工具" 等)
2. `cli.py` 合并后,顶部加模块 docstring 说明各 cmd 职责
3. `executors/base.py` 新文件加完整 docstring
4. `workflow.py` 的 `_register_engine` 加 docstring 说明与 `build_workflow`/`cmd_restore` 的关系
5. 不做大范围注释重写,只修过时/错误注释

**验证**:
- `grep -r "budget\|agents/\|cli_commands\|本地文件工具\|write_rtl\|read_rtl" eda_studio/` 无命中(除注释里解释历史的)

---

## Phase 3: 验证

### T8 全量验证

**步骤**:
1. `pytest tests/ -q` —— 75 tests(或调整后数量)全绿
2. `python -c "import eda_studio; from eda_studio.cli import main; from eda_studio.workflow import build_workflow; from eda_studio.executors.base import ExecutorContext"` —— 无 ImportError
3. `eda-studio --help` —— 列出 6 个子命令
4. 重跑 uart 端到端(需 docker + LLM API):
   ```bash
   eda-studio run uart --config config.yaml
   ```
   预期:仿真 PASSED + GDS 生成,token 消耗与重构前相当(70-94K input)
5. 重跑 i2c 端到端(需 docker + LLM API):
   ```bash
   eda-studio run i2c --config config.yaml
   ```
   预期:仿真通过 + GDS 生成

**回滚条件**:
- 若 uart/i2c 端到端失败且根因是 Phase 1 改动(非模型/上游问题),回滚对应 commit
- 若仅测试失败,修测试不回滚

---

## 执行顺序

1. **T1 + T3 并行**(独立文件,无依赖)
2. **T2**(CLI 合并,依赖 T1 确认 `budget.py`/`agents/` 确实可删,因 `__main__.py` 可能 import budget)
3. **T4**(依赖 T3 的 `ExecutorContext` 不直接依赖,但 workflow 注册 executor 的逻辑最好在 T3 后改)
4. **T5 + T6 + T7 并行**(文档,依赖 Phase 1 结构定型)
5. **T8**(最终验证)

实际执行:T1 → T3 → T2 → T4 → T5/T6/T7 → T8,其中 T1∥T3、T5∥T6∥T7 可并行。

---

## 不在本次范围(spec 明确排除)

- system_prompt 关键词匹配改 `with_step_builder`(等 Senza issue #10)
- workflow/judge/executors 核心领域逻辑
- 目录大范围重组(如 `src/` layout)
- testbench 被模型修改的问题
- senza-sdk 升级到 v0.4.7(未发布)
