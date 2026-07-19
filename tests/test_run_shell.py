import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from eda_studio.shell_safety import run_shell, ShellSafetyError
from eda_studio.config import ShellConfig, DockerConfig

SHELL = ShellConfig(allowed_commands=["verilator", "yosys", "echo"], denied_args=["rm", "sudo", ";", "|"])
DOCKER = DockerConfig(image="img", container="eda-tools", workdir="/work/designs", pdk="sky130A")

def test_empty_command_rejected(tmp_path):
    with pytest.raises(ShellSafetyError, match="空命令"):
        run_shell([], tmp_path, DOCKER, SHELL)

def test_tool_not_in_whitelist(tmp_path):
    with pytest.raises(ShellSafetyError, match="不在白名单"):
        run_shell(["rm", "-rf", "/"], tmp_path, DOCKER, SHELL)

def test_denied_arg_in_commandline(tmp_path):
    with pytest.raises(ShellSafetyError, match="危险字符"):
        run_shell(["verilator", "--rm"], tmp_path, DOCKER, SHELL)

def test_cwd_outside_designs(tmp_path):
    with pytest.raises(ShellSafetyError, match="不在 designs/ 下"):
        run_shell(["echo", "hi"], tmp_path, DOCKER, SHELL)

def test_path_mapping_and_docker_exec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart" / "sim").mkdir(parents=True)
    cwd = tmp_path / "designs" / "uart" / "sim"
    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        r = MagicMock()
        r.stdout = "ok"
        r.stderr = ""
        r.returncode = 0
        return r
    with patch("eda_studio.shell_safety.subprocess.run", side_effect=fake_run):
        result = run_shell(["echo", "hello"], cwd, DOCKER, SHELL)
    assert result.returncode == 0
    assert captured["cmd"][0] == "docker"
    assert "exec" in captured["cmd"]
    assert "-w" in captured["cmd"]
    w_idx = captured["cmd"].index("-w")
    assert captured["cmd"][w_idx + 1] == "/work/designs/uart/sim"
    assert "bash" in captured["cmd"]
    assert "-lc" in captured["cmd"]
    assert "echo hello" in captured["cmd"][-1]

def test_relative_cwd_works(tmp_path, monkeypatch):
    """P0 #1: to_container_cwd 对相对路径不崩溃(cwd.resolve() 后再 relative_to)。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart" / "sim").mkdir(parents=True)
    # 相对路径 cwd(不是 absolute Path)
    cwd = Path("designs/uart/sim")
    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        r = MagicMock()
        r.stdout = "ok"
        r.stderr = ""
        r.returncode = 0
        return r
    with patch("eda_studio.shell_safety.subprocess.run", side_effect=fake_run):
        result = run_shell(["echo", "hi"], cwd, DOCKER, SHELL)
    assert result.returncode == 0
    w_idx = captured["cmd"].index("-w")
    assert captured["cmd"][w_idx + 1] == "/work/designs/uart/sim"


def test_denied_semicolon_not_in_default(tmp_path):
    """P0 #2: synthesize yosys 脚本含 ';',默认 config 不应再 deny ';'。"""
    from eda_studio.config import load_config
    import shutil
    repo_cfg = Path(__file__).resolve().parents[1] / "config.example.yaml"
    cfg = load_config(str(repo_cfg))
    assert ";" not in cfg.shell_config.denied_args
