"""workflow 集成测试:不依赖真实 LLM/EDA(只测 build_workflow 能构建出 engine)。"""
from eda_studio.config import load_config
from eda_studio.workflow import build_workflow

CFG_YAML = """
provider: {type: openai, api_key: sk-test, base_url: null}
model: gpt-4o
pricing: {gpt-4o: {input_per_mtok: 2.5, output_per_mtok: 10.0}}
budget: {limit: 5.0, exceeded_action: stop}
workflow: {max_steps: 50, max_fix_retries: 3}
shell: {allowed_commands: [verilator], denied_args: [rm]}
docker: {image: img, container: eda-tools, workdir: /work/designs, pdk: sky130A}
"""


def test_build_workflow_returns_engine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(CFG_YAML)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    config = load_config(str(tmp_path / "config.yaml"))
    engine = build_workflow(config, "uart")
    assert hasattr(engine, "run")
    assert hasattr(engine, "current_step")
    assert hasattr(engine, "step_history")
    assert hasattr(engine, "total_cost")


def test_build_workflow_sets_context_variables(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(CFG_YAML)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    config = load_config(str(tmp_path / "config.yaml"))
    engine = build_workflow(config, "uart")
    assert engine is not None
    # 3 个 context variable 已设置;config 不应落盘(防 API key 泄露)
    assert engine.get_context_variable("design_dir") == "designs/uart"
    assert engine.get_context_variable("docker_config") is not None
    assert engine.get_context_variable("shell_config") is not None
