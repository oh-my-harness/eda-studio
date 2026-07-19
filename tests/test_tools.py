from pathlib import Path
from eda_studio.tools.file_tools import make_file_tools
from eda_studio.tools.report_tools import make_report_tools

CTX = object()

def test_write_and_read_rtl(tmp_path):
    tools = make_file_tools(tmp_path)
    r = tools["write_rtl"]({"filename": "uart_tx.v", "content": "module uart_tx; endmodule"}, CTX)
    assert "已写入" in r["content"][0]["text"]
    r2 = tools["read_rtl"]({"filename": "uart_tx.v"}, CTX)
    assert "uart_tx" in r2["content"][0]["text"]

def test_read_rtl_missing(tmp_path):
    tools = make_file_tools(tmp_path)
    r = tools["read_rtl"]({"filename": "nope.v"}, CTX)
    assert "不存在" in r["content"][0]["text"]

def test_list_design_files(tmp_path):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "a.v").write_text("x")
    (tmp_path / "rtl" / "b.v").write_text("y")
    tools = make_file_tools(tmp_path)
    r = tools["list_design_files"]({}, CTX)
    text = r["content"][0]["text"]
    assert "rtl/a.v" in text
    assert "rtl/b.v" in text

def test_list_design_files_empty(tmp_path):
    tools = make_file_tools(tmp_path)
    r = tools["list_design_files"]({}, CTX)
    assert "空" in r["content"][0]["text"]

def test_read_write_sdc(tmp_path):
    tools = make_file_tools(tmp_path)
    tools["write_sdc"]({"content": "create_clock -period 20"}, CTX)
    r = tools["read_sdc"]({}, CTX)
    assert "create_clock" in r["content"][0]["text"]

def test_read_sim_report_missing(tmp_path):
    tools = make_report_tools(tmp_path)
    r = tools["read_sim_report"]({}, CTX)
    assert "无仿真报告" in r["content"][0]["text"]

def test_read_sim_report_extracts_errors(tmp_path):
    (tmp_path / "sim").mkdir()
    report = "%Error: uart_tx.v:10: syntax error\nTEST PASSED\nsome other line"
    (tmp_path / "sim" / "report.txt").write_text(report)
    tools = make_report_tools(tmp_path)
    r = tools["read_sim_report"]({}, CTX)
    text = r["content"][0]["text"]
    assert "syntax error" in text
    assert "some other line" not in text

def test_read_drc_report(tmp_path):
    (tmp_path / "pnr").mkdir()
    (tmp_path / "pnr" / "drc.rpt").write_text("ERROR: metal1 spacing 0.1u\n")
    tools = make_report_tools(tmp_path)
    r = tools["read_drc_report"]({}, CTX)
    assert "metal1" in r["content"][0]["text"]
