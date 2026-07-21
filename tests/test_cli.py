"""CLI 测试:验证 argparse 路由(不真跑 engine,只 mock cmd_run/cmd_restore)。"""
from unittest.mock import patch

from eda_studio.cli import main

CFG = (
    "provider: {type: openai, api_key: sk-x, base_url: null}\n"
    "model: gpt-4o\n"
    "pricing: {gpt-4o: {input_per_mtok: 1.0, output_per_mtok: 2.0}}\n"
    "budget: {limit: 5.0, exceeded_action: stop}\n"
    "workflow: {max_steps: 50, max_fix_retries: 3}\n"
    "shell: {allowed_commands: [verilator], denied_args: [rm]}\n"
    "docker: {image: i, container: c, workdir: /w, pdk: sky130A}\n"
)

def test_cli_run_calls_cmd_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(CFG)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    with patch("eda_studio.cli.cmd_run") as mock_run:
        main(["run", "uart", "--config", "config.yaml"])
    mock_run.assert_called_once()

def test_cli_restore_calls_cmd_restore(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(CFG)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    with patch("eda_studio.cli.cmd_restore") as mock_restore:
        main(["restore", "uart", "--config", "config.yaml"])
    mock_restore.assert_called_once()

def test_cli_serve_calls_cmd_serve(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(CFG)
    monkeypatch.chdir(tmp_path)
    with patch("eda_studio.cli.cmd_serve") as mock_serve:
        main(["serve", "--config", "config.yaml", "--port", "3000"])
    mock_serve.assert_called_once()
