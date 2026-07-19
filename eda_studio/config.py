"""配置加载:yaml → dataclass。不 import senza(便于测试)。"""
import os
import re
from dataclasses import dataclass
from pathlib import Path
import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

@dataclass
class WorkflowConfig:
    max_steps: int
    max_fix_retries: int

@dataclass
class ShellConfig:
    allowed_commands: list
    denied_args: list

@dataclass
class DockerConfig:
    image: str
    container: str
    workdir: str
    pdk: str

@dataclass
class AppConfig:
    provider_spec: dict       # raw yaml: {type, api_key, base_url}
    model: str
    pricing_spec: dict        # raw yaml: {model: {input_per_mtok, output_per_mtok}}
    budget_limit: float
    budget_exceeded_action: str  # "stop" | "continue"
    workflow_config: WorkflowConfig
    shell_config: ShellConfig
    docker_config: DockerConfig


def _expand_env(value):
    """递归展开 ${ENV_VAR}。"""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: str) -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    raw = yaml.safe_load(p.read_text())
    raw = _expand_env(raw)
    return AppConfig(
        provider_spec=raw["provider"],
        model=raw["model"],
        pricing_spec=raw["pricing"],
        budget_limit=float(raw["budget"]["limit"]),
        budget_exceeded_action=raw["budget"]["exceeded_action"],
        workflow_config=WorkflowConfig(**raw["workflow"]),
        shell_config=ShellConfig(**raw["shell"]),
        docker_config=DockerConfig(**raw["docker"]),
    )
