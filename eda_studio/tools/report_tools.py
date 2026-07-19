"""报告读取 tools。闭包捕获 design_dir。"""
import re
from pathlib import Path


def _extract_sim_errors(report: str) -> str:
    """从仿真报告中提取错误/警告/结论行。无匹配时返回原文。"""
    lines = []
    for line in report.splitlines():
        if re.search(r"%Error|%Warning|TEST (PASSED|FAILED)|Assertion|Error:", line):
            lines.append(line)
    return "\n".join(lines) if lines else report


def _extract_drc_violations(report: str) -> str:
    """从 DRC 报告中提取违规行。无匹配时返回原文。"""
    lines = []
    for line in report.splitlines():
        if re.search(r"ERROR|violation|spacing|width|short|open|spelling", line, re.I):
            lines.append(line)
    return "\n".join(lines) if lines else report


def make_report_tools(design_dir: Path):
    """工厂函数:闭包捕获 design_dir,返回报告读取 tools。"""
    def read_sim_report_fn(args: dict, ctx) -> dict:
        path = design_dir / "sim" / "report.txt"
        if not path.exists():
            return {"content": [{"type": "text", "text": "无仿真报告"}], "terminate": False}
        report = path.read_text()
        summary = _extract_sim_errors(report)
        return {"content": [{"type": "text", "text": summary}], "terminate": False}

    def read_drc_report_fn(args: dict, ctx) -> dict:
        path = design_dir / "pnr" / "drc.rpt"
        if not path.exists():
            return {"content": [{"type": "text", "text": "无 DRC 报告"}], "terminate": False}
        report = path.read_text()
        summary = _extract_drc_violations(report)
        return {"content": [{"type": "text", "text": summary}], "terminate": False}

    return {"read_sim_report": read_sim_report_fn, "read_drc_report": read_drc_report_fn}
