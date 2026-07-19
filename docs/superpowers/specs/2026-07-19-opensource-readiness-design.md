# EDA Studio 开源发布就绪设计

> **日期**：2026-07-19
> **目标**：提升 eda-studio 作为开源仓库发布的用户易用性，让新用户 clone 后 5 分钟内能跑通 RTL→GDS 全流程。

## 背景

eda-studio 是基于 Senza SDK 的开源 EDA 自动化芯片设计示例项目，完成 UART RTL→GDS 全流程。当前仓库功能完整（端到端已跑通，产出 `designs/uart/gds/uart.gds`），但作为开源仓库发布存在以下易用性问题：

1. **无 LICENSE** — 法律上不可用
2. **README 缺截图和模型能力说明** — 新用户不知道用啥模型、WebUI 长啥样
3. **`designs/` 被 gitignore** — 新用户 clone 后 `run uart` 直接报错（缺 requirement.md 和 tb_uart.v）
4. **config 默认 gpt-4o 但实际开发用 glm-5.2** — 弱模型跑不通，用户误以为是代码 bug
5. **Docker 容器启动参数 `--skip sleep infinity` 是踩坑出来的** — 没解释
6. **CLAUDE.md 303 行混了开发期诊断笔记** — 对新用户是噪音
7. **运行报错不可见** — render step 失败但 workflow 显示 succeeded，错误藏在 taskstore 里

## 方案

分三层独立交付，每层可独立发布：

- **层 1 — 法律与文档基础**：LICENSE、README 重写、CLAUDE.md 拆分、CONTRIBUTING、templates 目录
- **层 2 — 上手命令**：`init` 复制示例 design、`check` 预检环境
- **层 3 — 运行可见性**：CLI 最终状态表、WebUI 失败标记、render 语义修正

## 层 1 — 法律与文档基础

### 1.1 LICENSE

- 根目录加 `LICENSE` 文件（MIT，版权 `Copyright (c) 2026 oh-my-harness`）
- `pyproject.toml` 加 `license = {text = "MIT"}` 和 `authors = [{name = "oh-my-harness"}]`

### 1.2 README 重写

结构：

```
# EDA Studio
一句话定位 + badges(Python版本/License)

## 截图
WebUI 三栏截图 + GDS 渲染 PNG

## 快速开始
1. pip install -e .
2. eda-studio init uart
3. docker run ... --skip sleep infinity
4. eda-studio check
5. python -m eda_studio run uart

## 模型要求
已验证模型清单 + 能力门槛说明（需能写可综合 Verilog）

## 命令
表格：init/check/run/serve/restore/status

## 配置
config.yaml 字段说明 + 环境变量展开

## 架构
流程图 + executor/judge/hooks 一句话说明，指向 docs/

## 贡献
指向 CONTRIBUTING.md
```

截图来源：浏览器截 WebUI 三栏图 + `designs/uart/gds/uart.png`。

### 1.3 CLAUDE.md 拆分

- `CLAUDE.md` 保留：项目概述、Docker 容器用法（`--skip sleep infinity` 解释、`bash -lc` 要求、工具版本表、PDK 路径）、Senza SDK 版本、架构边界
- `docs/dev-notes.md` 新建：开发期诊断笔记（executor bug 修复历程、PDK 路径踩坑细节、FinalAnswer 覆盖问题、budget should_stop hook 问题、docker exec [INFO] 行污染）
- 删除 CLAUDE.md 里纯开发期的诊断内容

### 1.4 CONTRIBUTING.md

简短（<100 行）：

- 如何加 executor（实现 `fn(ctx) -> dict`，注册到 workflow.py 的 `.with_executor`）
- 如何加 design（在 `templates/` 加目录，写 requirement.md）
- 如何加 LLM step（prompt + allowed_tools + judge 路由 + edge）
- 测试要求（`pytest tests/`，不依赖真实 EDA 工具和 LLM API）

### 1.5 templates/ 目录

```
templates/
└── uart/
    ├── requirement.md
    └── rtl/
        └── tb_uart.v
```

内容从现有 `designs/uart/` 的输入文件复制。`init` 命令从此复制到 `designs/<name>/`。

## 层 2 — 上手命令

### 2.1 `eda-studio init <name>`

**用途**：从 `templates/<name>/` 复制 design 输入文件到 `designs/<name>/`。

**行为**：
- 检查 `templates/<name>/` 存在，不存在报错列出可用模板
- 检查 `designs/<name>/` 不存在（避免覆盖运行产物），已存在报错退出
- `shutil.copytree` 复制
- 成功输出：下一步提示 `docker run ...` + `eda-studio check` + `run <name>`

**实现**：
- `__main__.py` 加 `init` 子命令（argparse subparser）
- templates 目录定位：`Path(__file__).parent / "templates"`
- `pyproject.toml` 的 `tool.setuptools.packages` 加 `eda_studio.templates`，或用 `include-package-data` 确保 templates 被打包

### 2.2 `eda-studio check`

**用途**：预检环境，跑 workflow 前排雷。

**检查项**（每项 ✓/✗ + 修复建议）：

1. **config.yaml 存在且可解析** — ✗ 提示 `cp config.example.yaml config.yaml`
2. **API key 非空** — 读 config，`${VAR}` 展开，✗ 提示 `export OPENAI_API_KEY=...`
3. **API 端点可达** — 发最小 chat completion 请求（`messages: [{role:user, content:"ping"}]`，max_tokens=1），检查 HTTP 200 + 返回有 `choices`。✗ 提示检查 base_url/key/模型名
4. **模型名有效** — 从上一步响应确认 model 被接受
5. **docker 可用** — `docker info` 退出码 0
6. **eda-tools 容器在跑** — `docker ps --filter name=eda-tools`，✗ 提示 `docker run ...` 完整命令
7. **容器内 EDA 工具可用** — `docker exec eda-tools bash -lc 'verilator --version'` 等，逐个检查 5 个工具（verilator/yosys/openroad/magic/klayout）
8. **PDK 存在** — `docker exec eda-tools ls /foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd/lib/`

**输出示例**：
```
✓ config.yaml 可解析
✓ OPENAI_API_KEY 已设置
✓ API 端点可达 (http://api.hyper-op.com/, 287ms)
✓ 模型 glm-5.2 可用
✓ docker 可用
✗ eda-tools 容器未运行
  → docker run -d --name eda-tools -v $(pwd)/designs:/work/designs \
    -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity
```

**实现**：
- `eda_studio/check.py` 新建
- `__main__.py` 加 `check` 子命令
- API ping 用 stdlib `urllib.request`（不引入新依赖）
- 检查项并行（`concurrent.futures.ThreadPoolExecutor`），总耗时 <5s
- 每项检查返回 `(name, ok, detail, fix_hint)`，统一格式化输出

### 2.3 CLI 入口整合

现有 `run`/`restore`/`status`/`serve` 基础上加 `init`/`check`：

```
eda-studio init <name>     # 初始化 design
eda-studio check           # 预检环境
eda-studio run <name>      # 运行 workflow
eda-studio serve           # Web UI
eda-studio restore <name>  # 恢复
eda-studio status <name>   # 状态
```

两种入口都支持：`eda-studio <cmd>` 和 `python -m eda_studio <cmd>`。

## 层 3 — 运行可见性

### 3.1 render 失败语义修正

**问题**：judge 对 render 无条件 `abort:done`，不管 success。render 失败时 workflow 仍标 succeeded，但 PNG 没生成，用户无感知。

**改法**：保持 `abort:done`（宽容——GDS 已产出，workflow 算 succeeded），但 `structured.success` 传播到 UI/CLI 让用户看到。

### 3.2 CLI 最终状态表

workflow 结束后（`cmd_run` 在 `engine.run()` 后），读 taskstore `workflow.json` 的 `step_history`，打印：

```
═══ Workflow 完成 (succeeded) ═══
  rtl_tx      ✓  3.6k↓ 1.8k↑   $0.00
  rtl_rx      ✓  7.6k↓ 3.1k↑   $0.00
  rtl_top     ✓  7.1k↓ 0.7k↑   $0.00
  simulate    ✓  executor
  synthesize  ✓  executor
  pnr         ✓  executor
  drc         ✓  executor
  gds         ✓  executor
  render      ✗  executor      ← NoMethodError: set_active_layer
总耗时 1m22s
```

- 失败 step 红色 ✗ + 错误摘要（output 截断到 80 字符）
- 成功 step ✓ + token 用量（LLM step）或 `executor`（EXEC step）

**实现**：`__main__.py` 的 `cmd_run` 在 `engine.run()` 返回后，从 taskstore 读 `step_history`，格式化打印。taskstore 路径 `designs/<name>/.taskstore/<task_id>/workflow.json`。

### 3.3 WebUI 失败可见性

三处改动：

1. **flow-node 失败标记**：`step_finished` 事件处理从 `structured.success` 判断，失败时 `setFailedNode(sid)` 而非 `setDoneNode(sid)`（红色边框）。

2. **完成横幅**：workflow 结束时（succeeded/failed 事件）顶部弹横幅：
   ```
   ✓ Workflow 完成 — 8/9 步成功
   render 失败: NoMethodError...  [查看详情]
   ```
   点"查看详情"切换到失败 step 的 center-col 视图。

3. **render step PNG 容错**：render 失败时不显示 broken image，显示错误信息块（红色背景 + output 摘要）。

### 3.4 step_finished 事件补 structured

当前 `step_finished` 事件只传 `output`/`cost`，前端无法判断成功失败。

**改法**：查 senza `WorkflowEvent` 的 step_finished payload 是否含 `structured`。若已含，前端直接读；若不含，在 `hooks.py` 的 after_step hook 把 `structured` 补进事件 payload。

## 非目标

- 不做多 PDK/工艺库切换（只用 Sky130）
- 不做多 design 支持（只提供 uart 模板，用户可自己加）
- 不做 CI/CD（本地测试通过即可）
- 不做 PyPI 发布（保持 `pip install -e .` 开发安装）
- 不做模型能力自动检测（只文档说明，check 只验证可达性）

## 测试

- `tests/test_cli.py` 加 `init`/`check` 命令测试（mock docker/subprocess）
- `tests/test_judge.py` 已覆盖 render 路由
- 现有 79 tests 保持通过
- 端到端：`eda-studio init uart && eda-studio check && python -m eda_studio run uart` 完整跑通

## 文件变更清单

**新增**：
- `LICENSE`
- `CONTRIBUTING.md`
- `templates/uart/requirement.md`
- `templates/uart/rtl/tb_uart.v`
- `docs/dev-notes.md`
- `eda_studio/check.py`
- `eda_studio/templates/`（包数据）

**修改**：
- `README.md`（重写）
- `CLAUDE.md`（拆分，删开发期笔记）
- `pyproject.toml`（license/authors + templates 打包）
- `__main__.py`（加 init/check 子命令 + CLI 状态表）
- `static/index.html`（失败标记 + 横幅 + render 容错）
- `eda_studio/hooks.py`（step_finished 补 structured，若需要）
- `.gitignore`（确保 templates/ 不被忽略）
