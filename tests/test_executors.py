import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from eda_studio.executors.simulate import simulate_executor
from eda_studio.executors.synthesize import synthesize_executor
from eda_studio.executors.pnr import pnr_executor
from eda_studio.executors.drc import drc_executor
from eda_studio.executors.gds import gds_executor
from eda_studio.shell_safety import ShellSafetyError
from eda_studio.config import ShellConfig, DockerConfig

SHELL = ShellConfig(allowed_commands=["verilator", "yosys", "openroad", "magic", "klayout"], denied_args=["rm"])
DOCKER = DockerConfig(image="img", container="eda-tools", workdir="/work/designs", pdk="sky130A")

def make_ctx(design_dir):
    return {"context": {"design_dir": str(design_dir), "docker_config": DOCKER, "shell_config": SHELL}}

def fake_completed(stdout="", stderr="", returncode=0):
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r

def fake_pdk_find(*args, **kwargs):
    """Mock subprocess.run 返回假 PDK 路径(pnr/drc/gds 用 docker exec ls 查 PDK)。
    pnr 一次 ls 查 3 个文件(.lib/.lef/.tlef),按扩展名拆分。"""
    r = MagicMock()
    r.stdout = "/fake/pdk/sky130_fd_sc_hd__tt_025C_1v80.lib\n" \
               "/fake/pdk/sky130_fd_sc_hd.lef\n" \
               "/fake/pdk/sky130_fd_sc_hd__nom.tlef\n" \
               "/fake/pdk/sky130_fd_sc_hd.gds\n"
    r.stderr = ""
    r.returncode = 0
    return r

def test_simulate_missing_tb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart" / "rtl").mkdir(parents=True)
    d = tmp_path / "designs" / "uart"
    r = simulate_executor(make_ctx(d))
    assert r["structured"]["success"] is False
    assert "tb_uart.v" in r["output"]

def test_simulate_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rtl = tmp_path / "designs" / "uart" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "uart.v").write_text("module uart; endmodule")
    (rtl / "tb_uart.v").write_text("`timescale 1ns/1ps module tb_uart; endmodule")
    d = tmp_path / "designs" / "uart"
    # 编译走 run_shell(白名单),sim_out 直接 subprocess.run(产物非工具,绕过白名单)
    with patch("eda_studio.executors.simulate.run_shell",
               return_value=fake_completed(returncode=0)), \
         patch("eda_studio.executors.simulate.subprocess.run",
               return_value=fake_completed(stdout="TEST PASSED", returncode=0)):
        r = simulate_executor(make_ctx(d))
    assert r["structured"]["success"] is True
    assert (d / "sim" / "report.txt").exists()

def test_simulate_safety_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rtl = tmp_path / "designs" / "uart" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "uart.v").write_text("x")
    (rtl / "tb_uart.v").write_text("x")
    d = tmp_path / "designs" / "uart"
    with patch("eda_studio.executors.simulate.run_shell", side_effect=ShellSafetyError("bad")):
        r = simulate_executor(make_ctx(d))
    assert r["structured"]["success"] is False
    assert r["structured"].get("safety_error") is True

def test_synthesize_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rtl = tmp_path / "designs" / "uart" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "uart.v").write_text("module uart; endmodule")
    d = tmp_path / "designs" / "uart"
    def fake_run(cmd, **kw):
        (d / "synth").mkdir(exist_ok=True)
        (d / "synth" / "netlist.json").write_text("{}")
        return fake_completed(returncode=0)
    with patch("eda_studio.executors.synthesize.run_shell", side_effect=fake_run):
        r = synthesize_executor(make_ctx(d))
    assert r["structured"]["success"] is True

def test_pnr_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart"
    (d / "synth").mkdir(parents=True)
    (d / "synth" / "netlist.v").write_text("module uart; endmodule")
    with patch("eda_studio.executors.pnr.run_shell", return_value=fake_completed(returncode=0)), \
         patch("eda_studio.executors.pnr.subprocess.run", side_effect=fake_pdk_find):
        r = pnr_executor(make_ctx(d))
    assert r["structured"]["success"] is True

def test_drc_no_violations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart" / "pnr"
    d.mkdir(parents=True)
    (d / "uart_pnr.def").write_text("x")
    with patch("eda_studio.executors.drc.run_shell", return_value=fake_completed(stdout="0 violations", returncode=0)), \
         patch("eda_studio.executors.drc.subprocess.run", side_effect=fake_pdk_find):
        r = drc_executor({"context": {"design_dir": str(d.parent), "docker_config": DOCKER, "shell_config": SHELL}})
    assert r["structured"]["success"] is True

def test_drc_has_violations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart" / "pnr"
    d.mkdir(parents=True)
    (d / "uart_pnr.def").write_text("x")
    (d / "drc.rpt").write_text("ERROR: metal1 spacing violation")
    with patch("eda_studio.executors.drc.run_shell", return_value=fake_completed(stdout="violation found", returncode=0)):
        r = drc_executor({"context": {"design_dir": str(d.parent), "docker_config": DOCKER, "shell_config": SHELL}})
    assert r["structured"]["success"] is False

def test_gds_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart"
    (d / "pnr").mkdir(parents=True)
    (d / "pnr" / "uart_pnr.def").write_text("x")
    def fake_run(cmd, **kw):
        (d / "gds").mkdir(exist_ok=True)
        (d / "gds" / "uart.gds").write_text("GDSII")
        return fake_completed(returncode=0)
    with patch("eda_studio.executors.gds.run_shell", side_effect=fake_run), \
         patch("eda_studio.executors.gds.subprocess.run", side_effect=fake_pdk_find):
        r = gds_executor(make_ctx(d))
    assert r["structured"]["success"] is True
    assert r["structured"]["gds_path"].endswith("uart.gds")

def test_simulate_sim_out_not_whitelisted(tmp_path, monkeypatch):
    """P1: sim_out 是 verilator 产物,不走 run_shell 白名单,直接 subprocess.run。"""
    monkeypatch.chdir(tmp_path)
    rtl = tmp_path / "designs" / "uart" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "uart.v").write_text("module uart; endmodule")
    (rtl / "tb_uart.v").write_text("x")
    d = tmp_path / "designs" / "uart"
    run_calls = []
    def fake_run_shell(cmd, **kw):
        run_calls.append(cmd[0])
        return fake_completed(returncode=0)
    with patch("eda_studio.executors.simulate.run_shell", side_effect=fake_run_shell), \
         patch("eda_studio.executors.simulate.subprocess.run",
               return_value=fake_completed(stdout="TEST PASSED", returncode=0)) as sp_run:
        r = simulate_executor(make_ctx(d))
    # run_shell 只被调用一次(编译),不包含 sim_out
    assert run_calls == ["verilator"]
    # subprocess.run 被调用一次跑 sim_out
    assert sp_run.call_count == 1
    docker_cmd = sp_run.call_args[0][0]
    assert docker_cmd[0] == "docker" and "exec" in docker_cmd
    assert docker_cmd[-1] == "./obj_dir/sim_out"
    assert r["structured"]["success"] is True

def test_drc_nonzero_returncode_fails(tmp_path, monkeypatch):
    """P3: 工具异常退出(returncode!=0)即使无 violation 字样也判失败。"""
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart" / "pnr"
    d.mkdir(parents=True)
    (d / "uart_pnr.def").write_text("x")
    with patch("eda_studio.executors.drc.run_shell",
               return_value=fake_completed(stdout="magic crashed", returncode=1)):
        r = drc_executor({"context": {"design_dir": str(d.parent), "docker_config": DOCKER, "shell_config": SHELL}})
    assert r["structured"]["success"] is False

def test_synthesize_timeout_returns_failure(tmp_path, monkeypatch):
    """P2 #5: run_shell 抛 TimeoutExpired 时 synthesize 返回 success=False。"""
    import subprocess
    monkeypatch.chdir(tmp_path)
    rtl = tmp_path / "designs" / "uart" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "uart.v").write_text("module uart; endmodule")
    d = tmp_path / "designs" / "uart"
    with patch("eda_studio.executors.synthesize.run_shell",
               side_effect=subprocess.TimeoutExpired(cmd=["yosys"], timeout=600)):
        r = synthesize_executor(make_ctx(d))
    assert r["structured"]["success"] is False
    assert r["output"] == "timeout"

def test_simulate_timeout_returns_failure(tmp_path, monkeypatch):
    """P2 #5: 直接 subprocess.run 抛 TimeoutExpired 时 simulate 返回 success=False。"""
    import subprocess
    monkeypatch.chdir(tmp_path)
    rtl = tmp_path / "designs" / "uart" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "uart.v").write_text("module uart; endmodule")
    (rtl / "tb_uart.v").write_text("x")
    d = tmp_path / "designs" / "uart"
    # run_shell 正常返回,但 sim_out 的 subprocess.run 超时
    with patch("eda_studio.executors.simulate.run_shell",
               return_value=fake_completed(returncode=0)), \
         patch("eda_studio.executors.simulate.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd=["docker"], timeout=600)):
        r = simulate_executor(make_ctx(d))
    assert r["structured"]["success"] is False
    assert r["output"] == "timeout"

def test_pnr_timeout_returns_failure(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart"
    (d / "synth").mkdir(parents=True)
    (d / "synth" / "netlist.v").write_text("x")
    with patch("eda_studio.executors.pnr.run_shell",
               side_effect=subprocess.TimeoutExpired(cmd=["openroad"], timeout=600)), \
         patch("eda_studio.executors.pnr.subprocess.run", side_effect=fake_pdk_find):
        r = pnr_executor(make_ctx(d))
    assert r["structured"]["success"] is False
    assert r["output"] == "timeout"

def test_drc_timeout_returns_failure(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart" / "pnr"
    d.mkdir(parents=True)
    (d / "uart_pnr.def").write_text("x")
    with patch("eda_studio.executors.drc.run_shell",
               side_effect=subprocess.TimeoutExpired(cmd=["magic"], timeout=600)), \
         patch("eda_studio.executors.drc.subprocess.run", side_effect=fake_pdk_find):
        r = drc_executor({"context": {"design_dir": str(d.parent), "docker_config": DOCKER, "shell_config": SHELL}})
    assert r["structured"]["success"] is False
    assert r["output"] == "timeout"

def test_gds_timeout_returns_failure(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart"
    (d / "pnr").mkdir(parents=True)
    (d / "pnr" / "uart_pnr.def").write_text("x")
    with patch("eda_studio.executors.gds.run_shell",
               side_effect=subprocess.TimeoutExpired(cmd=["klayout"], timeout=600)), \
         patch("eda_studio.executors.gds.subprocess.run", side_effect=fake_pdk_find):
        r = gds_executor(make_ctx(d))
    assert r["structured"]["success"] is False
    assert r["output"] == "timeout"
