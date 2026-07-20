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

def test_append_rtl_creates_if_missing(tmp_path):
    tools = make_file_tools(tmp_path)
    r = tools["append_rtl"]({"filename": "uart_tx.v", "content": "module uart_tx; endmodule"}, CTX)
    assert "已追加" in r["content"][0]["text"]
    assert "1 行" in r["content"][0]["text"]
    assert (tmp_path / "rtl" / "uart_tx.v").read_text() == "module uart_tx; endmodule"

def test_append_rtl_appends_to_existing(tmp_path):
    tools = make_file_tools(tmp_path)
    tools["write_rtl"]({"filename": "m.v", "content": "line1\n"}, CTX)
    r = tools["append_rtl"]({"filename": "m.v", "content": "line2\n"}, CTX)
    assert "2 行" in r["content"][0]["text"]
    assert (tmp_path / "rtl" / "m.v").read_text() == "line1\nline2\n"

def test_edit_rtl_replaces_code(tmp_path):
    tools = make_file_tools(tmp_path)
    tools["write_rtl"]({"filename": "m.v", "content": "assign a = b;\nassign c = d;\n"}, CTX)
    r = tools["edit_rtl"]({"filename": "m.v", "old_code": "assign a = b;", "new_code": "assign a = c;"}, CTX)
    assert "已替换" in r["content"][0]["text"]
    assert (tmp_path / "rtl" / "m.v").read_text() == "assign a = c;\nassign c = d;\n"

def test_edit_rtl_not_found(tmp_path):
    tools = make_file_tools(tmp_path)
    tools["write_rtl"]({"filename": "m.v", "content": "assign a = b;\n"}, CTX)
    r = tools["edit_rtl"]({"filename": "m.v", "old_code": "nonexistent", "new_code": "x"}, CTX)
    assert "未找到" in r["content"][0]["text"]

def test_edit_rtl_ambiguous(tmp_path):
    tools = make_file_tools(tmp_path)
    tools["write_rtl"]({"filename": "m.v", "content": "assign a = b;\nassign a = b;\n"}, CTX)
    r = tools["edit_rtl"]({"filename": "m.v", "old_code": "assign a = b;", "new_code": "x"}, CTX)
    assert "2 处" in r["content"][0]["text"]

def test_edit_rtl_file_missing(tmp_path):
    tools = make_file_tools(tmp_path)
    r = tools["edit_rtl"]({"filename": "nope.v", "old_code": "x", "new_code": "y"}, CTX)
    assert "不存在" in r["content"][0]["text"]

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
