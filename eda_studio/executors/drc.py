"""magic DRC 检查 executor。

magic 用 tcl 脚本文件(不支持 -cmd),需先 read LEF(tech + macro)再 read DEF。
跟 openroad 一样 PDK 路径用 docker exec 查找。
"""
import subprocess
from pathlib import Path
from ..shell_safety import run_shell, to_container_path, ShellSafetyError
from .base import ExecutorContext, find_pdk_files


def drc_executor(ctx: dict) -> dict:
    ectx = ExecutorContext.from_ctx(ctx)
    design_dir = ectx.design_dir
    docker_cfg = ectx.docker_config
    shell_cfg = ectx.shell_config
    dcfg = ectx.design
    pnr_dir = design_dir / "pnr"
    def_file = pnr_dir / f"{dcfg.top_module}_pnr.def"
    drc_rpt = pnr_dir / "drc.rpt"

    if not def_file.exists():
        return {"output": f"DEF 文件不存在: {def_file}",
                "structured": {"success": False}}

    # PDK 路径(同 pnr executor,只需 lef + tlef)
    pdk = find_pdk_files(docker_cfg, [
        "lef/sky130_fd_sc_hd.lef",
        "techlef/sky130_fd_sc_hd__nom.tlef",
    ])
    lef_path = pdk["lef/sky130_fd_sc_hd.lef"]
    tlef_path = pdk["techlef/sky130_fd_sc_hd__nom.tlef"]
    if not lef_path or not tlef_path:
        return {"output": f"PDK LEF 未找到: lef={lef_path} tlef={tlef_path}",
                "structured": {"success": False}}

    def_path = to_container_path(def_file, docker_cfg)
    rpt_path = to_container_path(drc_rpt, docker_cfg)
    tcl = f"""\
lef read {tlef_path}
lef read {lef_path}
def read {def_path}
drc check
drc catchup
drc count total
exit
"""
    tcl_file = pnr_dir / "drc.tcl"
    tcl_file.write_text(tcl)
    tcl_container = to_container_path(tcl_file, docker_cfg)
    try:
        result = run_shell(["magic", "-noconsole", "-dnull", tcl_container],
                           cwd=pnr_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except subprocess.TimeoutExpired:
        return {"output": "timeout", "structured": {"success": False}}
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    if drc_rpt.exists():
        report += "\n--- DRC violations ---\n" + drc_rpt.read_text()
    (pnr_dir / "report.txt").write_text(report)
    # 成功判定:工具正常退出(returncode==0)且无违规
    lower = report.lower()
    no_violations = "0 violations" in lower or "0 drc" in lower or "total drc errors found: 0" in lower
    return {
        "output": report,
        "structured": {"success": result.returncode == 0 and no_violations,
                       "report_path": str(pnr_dir / "report.txt")},
    }
