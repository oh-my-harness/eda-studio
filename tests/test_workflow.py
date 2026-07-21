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


def test_build_workflow_with_pricing_does_not_error(tmp_path, monkeypatch):
    """build_workflow 挂载 with_pricing 后应正常构造 engine(不报错)。

    真实计价需 LLM 调用,单测只验证挂载成功。with_pricing 通过共享
    customize_builder 闭包注入,与 with_thinking_level 同链。
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(CFG_YAML)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    config = load_config(str(tmp_path / "config.yaml"))
    engine = build_workflow(config, "uart")
    assert engine is not None
    assert hasattr(engine, "total_cost")


def test_build_providers_returns_pricing():
    """build_providers 应返回非 None 的 pricing(PricingProvider)。

    build_providers 只读 config 对象的 provider_spec/pricing_spec,
    不触碰文件系统,故无需 chdir / 写 config.yaml / mkdir。
    """
    import yaml

    from eda_studio.config import AppConfig
    raw = yaml.safe_load(CFG_YAML)
    config = AppConfig(
        provider_spec=raw["provider"],
        model=raw["model"],
        pricing_spec=raw["pricing"],
        budget_limit=float(raw["budget"]["limit"]),
        budget_exceeded_action=raw["budget"]["exceeded_action"],
        workflow_config=None,
        shell_config=None,
        docker_config=None,
    )
    from eda_studio.workflow import build_providers
    provider, pricing = build_providers(config)
    assert provider is not None
    assert pricing is not None


def test_session_base_dir_default(monkeypatch):
    """未设环境变量时返回默认 'sessions'。"""
    monkeypatch.delenv("EDA_STUDIO_SESSION_DIR", raising=False)
    from eda_studio.workflow import _session_base_dir
    assert _session_base_dir() == "sessions"


def test_session_base_dir_env_override(monkeypatch):
    """环境变量覆盖生效。"""
    monkeypatch.setenv("EDA_STUDIO_SESSION_DIR", "/tmp/foo")
    from eda_studio.workflow import _session_base_dir
    assert _session_base_dir() == "/tmp/foo"


def test_session_base_dir_empty_env_falls_back(monkeypatch):
    """环境变量设为空字符串时回退到默认值(空字符串视为未设)。"""
    monkeypatch.setenv("EDA_STUDIO_SESSION_DIR", "")
    from eda_studio.workflow import _session_base_dir
    assert _session_base_dir() == "sessions"

def test_session_base_dir_design_scoped(monkeypatch):
    """传 design_name 时返回 sessions/<design_name>,按 design 分目录。"""
    monkeypatch.delenv("EDA_STUDIO_SESSION_DIR", raising=False)
    from eda_studio.workflow import _session_base_dir
    assert _session_base_dir("uart") == "sessions/uart"
    assert _session_base_dir("i2c") == "sessions/i2c"


def test_session_base_dir_env_override_with_design(monkeypatch):
    """环境变量 + design_name 同时存在时,返回 <env>/<design_name>。"""
    monkeypatch.setenv("EDA_STUDIO_SESSION_DIR", "/tmp/foo")
    from eda_studio.workflow import _session_base_dir
    assert _session_base_dir("uart") == "/tmp/foo/uart"


def test_build_workflow_with_custom_session_dir(tmp_path, monkeypatch):
    """环境变量设自定义 session 根目录时,build_workflow 仍能正常构造。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EDA_STUDIO_SESSION_DIR", str(tmp_path / "custom_sessions"))
    (tmp_path / "config.yaml").write_text(CFG_YAML)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    config = load_config(str(tmp_path / "config.yaml"))
    engine = build_workflow(config, "uart")
    assert engine is not None
    assert hasattr(engine, "run")
