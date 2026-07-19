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
    with patch("eda_studio.executors.simulate.run_shell", side_effect=[fake_completed(returncode=0), fake_completed(stdout="TEST PASSED", returncode=0)]):
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
    with patch("eda_studio.executors.pnr.run_shell", return_value=fake_completed(returncode=0)):
        r = pnr_executor(make_ctx(d))
    assert r["structured"]["success"] is True

def test_drc_no_violations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "designs" / "uart" / "pnr"
    d.mkdir(parents=True)
    (d / "uart_pnr.def").write_text("x")
    with patch("eda_studio.executors.drc.run_shell", return_value=fake_completed(stdout="0 violations", returncode=0)):
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
    with patch("eda_studio.executors.gds.run_shell", side_effect=fake_run):
        r = gds_executor(make_ctx(d))
    assert r["structured"]["success"] is True
    assert r["structured"]["gds_path"].endswith("uart.gds")
