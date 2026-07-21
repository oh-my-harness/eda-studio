import textwrap
from pathlib import Path

from eda_studio.config import AppConfig, DockerConfig, ShellConfig, WorkflowConfig, load_config


def write_cfg(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return p

def test_load_config_basic(tmp_path):
    cfg = load_config(write_cfg(tmp_path, """
        provider:
          type: openai
          api_key: sk-test
          base_url: null
        model: gpt-4o
        pricing:
          gpt-4o:
            input_per_mtok: 2.5
            output_per_mtok: 10.0
        budget:
          limit: 5.0
          exceeded_action: stop
        workflow:
          max_steps: 50
          max_fix_retries: 3
        shell:
          allowed_commands: [verilator, yosys]
          denied_args: [rm, sudo]
        docker:
          image: hpretl/iic-osic-tools:latest
          container: eda-tools
          workdir: /work/designs
          pdk: sky130A
    """))
    assert isinstance(cfg, AppConfig)
    assert cfg.model == "gpt-4o"
    assert cfg.provider_spec == {"type": "openai", "api_key": "sk-test", "base_url": None}
    assert cfg.pricing_spec == {"gpt-4o": {"input_per_mtok": 2.5, "output_per_mtok": 10.0}}
    assert cfg.budget_limit == 5.0
    assert cfg.budget_exceeded_action == "stop"
    assert cfg.workflow_config == WorkflowConfig(max_steps=50, max_fix_retries=3)
    assert cfg.shell_config == ShellConfig(allowed_commands=["verilator", "yosys"], denied_args=["rm", "sudo"])
    assert cfg.docker_config == DockerConfig(image="hpretl/iic-osic-tools:latest", container="eda-tools", workdir="/work/designs", pdk="sky130A")

def test_load_config_env_var_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    cfg = load_config(write_cfg(tmp_path, """
        provider:
          type: openai
          api_key: ${OPENAI_API_KEY}
          base_url: null
        model: gpt-4o
        pricing: {gpt-4o: {input_per_mtok: 1.0, output_per_mtok: 2.0}}
        budget: {limit: 1.0, exceeded_action: stop}
        workflow: {max_steps: 50, max_fix_retries: 3}
        shell: {allowed_commands: [verilator], denied_args: [rm]}
        docker: {image: img, container: c, workdir: /w, pdk: sky130A}
    """))
    assert cfg.provider_spec["api_key"] == "sk-from-env"

def test_load_config_missing_file(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.yaml"))
