# 贡献指南

感谢对 EDA Studio 的贡献!本文档说明如何扩展项目。

## 开发环境

```bash
git clone <repo>
cd eda-studio
pip install -e .
eda-studio init uart        # 复制示例 design
docker run -d --name eda-tools -v $(pwd)/designs:/work/designs \
  -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity
eda-studio check            # 预检
pytest tests/               # 跑测试(不依赖真实 EDA 工具和 LLM)
```

## 加 Executor

Executor 是 Python 回调,签名为 `fn(ctx: dict) -> dict`。

1. 在 `eda_studio/executors/` 新建文件,实现 executor 函数
2. 返回 `{"output": str, "structured": {"success": bool, ...}}`
3. 在 `eda_studio/executors/__init__.py` 导出
4. 在 `eda_studio/workflow.py` 的 `_register_engine` 中用 `.with_executor(step_id, create_executor(fn))` 注册(build_workflow 和 cmd_restore 共用)
5. 在 `eda_studio/judge.py` 加该 step 的路由逻辑
6. 在 `eda_studio/workflow.py` 的 `workflow_dict.edges` 加路由边

参考 `eda_studio/executors/simulate.py`。

## 加 Design

1. 在 `eda_studio/templates/<name>/` 新建目录
2. 写 `requirement.md`(设计需求)
3. 如需 testbench,放 `rtl/tb_<name>.v`
4. 用户 `eda-studio init <name>` 复制到 `designs/<name>/`

## 加 LLM Step

1. 在 `eda_studio/prompts.py` 加 prompt 模板
2. 在 `eda_studio/workflow.py` 的 `workflow_dict.steps` 加 step(`id`/`name`/`prompt`/`allowed_tools`)
3. 在 `workflow_dict.edges` 加路由边
4. 在 `eda_studio/judge.py` 加该 step 的路由逻辑

## 测试

- 所有测试不依赖真实 EDA 工具和 LLM API
- executor 测试 monkeypatch `run_shell`/`subprocess`
- 运行:`pytest tests/ -q`

## 提交

- 遵循现有 commit message 风格(`feat:`/`fix:`/`docs:`/`chore:`)
- 确保所有测试通过
