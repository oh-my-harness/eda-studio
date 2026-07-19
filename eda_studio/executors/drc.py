"""magic DRC 检查 executor。"""
from pathlib import Path
from ..shell_safety import run_shell, ShellSafetyError


def drc_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]
    pnr_dir = design_dir / "pnr"
    def_file = pnr_dir / "uart_pnr.def"

    tcl = f"""
drc {def_file} {pnr_dir / 'drc.rpt'}
exit
"""
    try:
        result = run_shell(["magic", "-noconsole", "-dnull", "-cmd", tcl],
                           cwd=pnr_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    drc_report = pnr_dir / "drc.rpt"
    if drc_report.exists():
        report += "\n--- DRC violations ---\n" + drc_report.read_text()
    (pnr_dir / "report.txt").write_text(report)
    lower = report.lower()
    return {
        "output": report,
        "structured": {"success": "0 violations" in lower or "violation" not in lower,
                       "report_path": str(pnr_dir / "report.txt")},
    }
