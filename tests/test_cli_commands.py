"""init/check CLI 子命令测试。不依赖真实 EDA 工具和 LLM API。"""
import sys
from pathlib import Path
from unittest.mock import patch
import pytest


def test_init_copies_template(tmp_path, monkeypatch):
    """init uart 复制 templates/uart/ 到 designs/uart/。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli import cmd_init
    rc = cmd_init("uart")
    assert rc == 0
    req = tmp_path / "designs" / "uart" / "requirement.md"
    tb = tmp_path / "designs" / "uart" / "rtl" / "tb_uart.v"
    assert req.is_file(), f"requirement.md not found at {req}"
    assert tb.is_file(), f"tb_uart.v not found at {tb}"
    assert req.read_text().startswith("# UART")


def test_init_refuses_existing(tmp_path, monkeypatch):
    """designs/uart/ 已存在时 init 报错退出。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    from eda_studio.cli import cmd_init
    rc = cmd_init("uart")
    assert rc == 1


def test_init_unknown_template(tmp_path, monkeypatch):
    """未知模板名报错并列出可用模板。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli import cmd_init
    rc = cmd_init("nonexistent")
    assert rc == 1


def test_check_config_missing(tmp_path, monkeypatch):
    """config.yaml 不存在时 check 报错。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli import cmd_check
    rc = cmd_check("nonexistent.yaml")
    assert rc == 1


def test_check_config_ok(tmp_path, monkeypatch):
    """config 存在但 API/容器不可达时,check 报告各项状态。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "provider:\n"
        "  type: openai\n"
        "  api_key: test-key\n"
        "  base_url: http://127.0.0.1:1\n"  # 不可能达,避免真连 API
        "model: gpt-4o\n"
        "    input_per_mtok: 2.5\n"
        "    output_per_mtok: 10.0\n"
        "budget:\n"
        "  limit: 5.0\n"
        "  exceeded_action: stop\n"
        "workflow:\n"
        "  max_steps: 50\n"
        "  max_fix_retries: 3\n"
        "shell:\n"
        "  allowed_commands: [\"verilator\"]\n"
        "  denied_args: [\"rm\"]\n"
        "docker:\n"
        "  image: hpretl/iic-osic-tools:latest\n"
        "  container: eda-tools\n"
        "  workdir: /work/designs\n"
        "  pdk: sky130A\n"
    )
    from eda_studio.cli import cmd_check
    rc = cmd_check("config.yaml")
    assert rc == 1


def test_cmd_restore_passes_session_base_dir(tmp_path, monkeypatch):
    """cmd_restore 构造 engine 时传了 session_base_dir(通过环境变量覆盖验证)。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EDA_STUDIO_SESSION_DIR", str(tmp_path / "rsessions"))
    (tmp_path / "config.yaml").write_text(
        "provider:\n"
        "  type: openai\n"
        "  api_key: sk-test\n"
        "  base_url: http://127.0.0.1:1\n"
        "model: gpt-4o\n"
        "pricing:\n"
        "  gpt-4o:\n"
        "    input_per_mtok: 2.5\n"
        "    output_per_mtok: 10.0\n"
        "budget:\n"
        "  limit: 5.0\n"
        "  exceeded_action: stop\n"
        "workflow:\n"
        "  max_steps: 50\n"
        "  max_fix_retries: 3\n"
        "shell:\n"
        "  allowed_commands: [\"verilator\"]\n"
        "  denied_args: [\"rm\"]\n"
        "docker:\n"
        "  image: img\n"
        "  container: eda-tools\n"
        "  workdir: /work/designs\n"
        "  pdk: sky130A\n"
    )
    # 造一个 uart design 目录 + taskstore task_id
    uart_dir = tmp_path / "designs" / "uart"
    uart_dir.mkdir(parents=True)
    store_dir = uart_dir / ".taskstore"
    store_dir.mkdir()
    (store_dir / "task_id").write_text("task-test-id-1234")
    # mock WorkflowEngine.restore,验证 session_base_dir 传入
    from unittest.mock import patch, MagicMock
    with patch("eda_studio.cli.WorkflowEngine") as MockEngine:
        mock_engine = MagicMock()
        mock_engine.current_step.return_value = "rtl_tx"
        mock_engine.step_history.return_value = []
        mock_engine.state.return_value = "paused"
        MockEngine.restore.return_value = mock_engine
        with patch("eda_studio.cli._re_register", side_effect=lambda eng, *a, **k: eng):
            try:
                from eda_studio.cli import cmd_restore
                cmd_restore("uart", str(tmp_path / "config.yaml"))
            except SystemExit:
                pass
            except Exception:
                pass
            assert MockEngine.restore.called, "WorkflowEngine.restore 未被调用"
            _, kwargs = MockEngine.restore.call_args
            assert "session_base_dir" in kwargs, "session_base_dir 未传"
            assert kwargs["session_base_dir"] == str(tmp_path / "rsessions"), \
                f"期望 {tmp_path / 'rsessions'},实际 {kwargs.get('session_base_dir')}"
