"""init/check CLI 子命令测试。不依赖真实 EDA 工具和 LLM API。"""
from unittest.mock import patch


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


def test_check_anthropic_pings_messages_endpoint(tmp_path, monkeypatch):
    """provider.type: anthropic 时,_check_api_reachable 走 /v1/messages + x-api-key 路径。
    用不可达 base_url 验证它确实发起了请求(而非跳过)。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "provider:\n"
        "  type: anthropic\n"
        "  api_key: sk-ant-test\n"
        "  base_url: http://127.0.0.1:1\n"  # 不可能达,避免真连 API
        "model: claude-sonnet-4-5\n"
        "pricing:\n"
        "  claude-sonnet-4-5:\n"
        "    input_per_mtok: 3.0\n"
        "    output_per_mtok: 15.0\n"
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
    from eda_studio.cli import _check_api_key, _check_api_reachable
    ok_key, detail_key, hint_key = _check_api_key("config.yaml")
    assert ok_key, f"anthropic key check 应通过: {detail_key}"
    # 用不可达端点,应返回失败(说明确实发起了 ping,而非跳过)
    ok_api, detail_api, hint_api = _check_api_reachable("config.yaml")
    assert not ok_api, f"不可达端点应返回失败: {detail_api}"
    assert "不可达" in detail_api


def test_check_anthropic_empty_key_hints_correct_env(tmp_path, monkeypatch):
    """anthropic key 为空时,提示指向 ANTHROPIC_API_KEY(非 OPENAI_API_KEY)。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "provider:\n"
        "  type: anthropic\n"
        "  api_key: \"\"\n"
        "  base_url: null\n"
        "model: claude-sonnet-4-5\n"
        "pricing:\n"
        "  claude-sonnet-4-5:\n"
        "    input_per_mtok: 3.0\n"
        "    output_per_mtok: 15.0\n"
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
    from eda_studio.cli import _check_api_key
    ok, detail, hint = _check_api_key("config.yaml")
    assert not ok
    assert "ANTHROPIC_API_KEY" in hint
    assert "OPENAI" not in hint


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
    from unittest.mock import MagicMock
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
            assert kwargs["session_base_dir"] == str(tmp_path / "rsessions" / "uart"), \
                f"期望 {tmp_path / 'rsessions' / 'uart'},实际 {kwargs.get('session_base_dir')}"

def test_persist_task_id_writes_file(tmp_path, monkeypatch):
    """Issue #1: _persist_task_id 写入 designs/<name>/.taskstore/task_id。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli import _persist_task_id
    _persist_task_id("uart", "task-abc-123")
    task_id_file = tmp_path / "designs" / "uart" / ".taskstore" / "task_id"
    assert task_id_file.is_file(), f"task_id 文件未创建: {task_id_file}"
    assert task_id_file.read_text() == "task-abc-123"
