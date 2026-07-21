"""cmd_run 最终状态表测试。"""
import json


def _make_taskstore(tmp_path, design, step_history):
    """在 tmp_path 下造一个 taskstore。"""
    store = tmp_path / "designs" / design / ".taskstore" / "task-fake"
    store.mkdir(parents=True)
    (store / "workflow.json").write_text(json.dumps({
        "status": "succeeded",
        "step_history": step_history,
    }))
    (tmp_path / "designs" / design / ".taskstore" / "task_id").write_text("task-fake")


def test_print_run_summary(tmp_path, monkeypatch, capsys):
    """状态表正确显示每个 step 的 ✓/✗。"""
    _make_taskstore(tmp_path, "uart", [
        {"step_id": "rtl_tx", "result": {"output": "", "structured": None,
          "cost": {"total_input_tokens": 100, "total_output_tokens": 50, "total_cost": 0.01}},
         "transition": {"to": "rtl_rx"}},
        {"step_id": "simulate", "result": {"output": "ok", "structured": {"success": True},
          "cost": {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost": 0.0}},
         "transition": {"to": "synthesize"}},
        {"step_id": "render", "result": {"output": "ERROR: NoMethodError",
          "structured": {"success": False}, "cost": {}},
         "transition": {"abort": {"reason": "done"}}},
    ])
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli import _print_run_summary
    _print_run_summary("uart")
    out = capsys.readouterr().out
    assert "rtl_tx" in out and "✓" in out
    assert "simulate" in out
    assert "render" in out and "✗" in out
    assert "NoMethodError" in out


def test_print_run_summary_no_taskstore(tmp_path, monkeypatch, capsys):
    """taskstore 不存在时不报错。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli import _print_run_summary
    _print_run_summary("uart")
    out = capsys.readouterr().out
    assert "未找到" in out or "taskstore" in out
