"""magic DRC 检查 executor。"""
from pathlib import Path
from ..shell_safety import run_shell, to_container_path, ShellSafetyError


def drc_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]
    pnr_dir = design_dir / "pnr"
    def_file = pnr_dir / "uart_pnr.def"
    drc_rpt = pnr_dir / "drc.rpt"

    # 路径参数转容器内绝对路径
    def_path = to_container_path(def_file, docker_cfg)
    rpt_path = to_container_path(drc_rpt, docker_cfg)
    tcl = f"""
drc {def_path} {rpt_path}
exit
"""
    try:
        result = run_shell(["magic", "-noconsole", "-dnull", "-cmd", tcl],
                           cwd=pnr_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    if drc_rpt.exists():
        report += "\n--- DRC violations ---\n" + drc_rpt.read_text()
    (pnr_dir / "report.txt").write_text(report)
    # 成功判定:工具正常退出(returncode==0)且无违规
    lower = report.lower()
    no_violations = "0 violations" in lower or "violation" not in lower
    return {
        "output": report,
        "structured": {"success": result.returncode == 0 and no_violations,
                       "report_path": str(pnr_dir / "report.txt")},
    }
