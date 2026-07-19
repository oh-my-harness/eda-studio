"""magic DRC 检查 executor。

magic 用 tcl 脚本文件(不支持 -cmd),需先 read LEF(tech + macro)再 read DEF。
跟 openroad 一样 PDK 路径用 docker exec 查找。
"""
import subprocess
from pathlib import Path
from ..shell_safety import run_shell, to_container_path, ShellSafetyError, _as_docker_config


def drc_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = _as_docker_config(ctx["context"]["docker_config"])
    shell_cfg = ctx["context"]["shell_config"]
    from ..design_config import load_design_config
    dcfg = load_design_config(design_dir)
    pnr_dir = design_dir / "pnr"
    def_file = pnr_dir / f"{dcfg.top_module}_pnr.def"
    drc_rpt = pnr_dir / "drc.rpt"

    if not def_file.exists():
        return {"output": f"DEF 文件不存在: {def_file}",
                "structured": {"success": False}}

    # PDK 路径(同 pnr executor)
    pdk_glob = "/foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd"
    find = subprocess.run(
        ["docker", "exec", docker_cfg.container, "bash", "-lc",
         f"ls {pdk_glob}/lef/sky130_fd_sc_hd.lef "
         f"{pdk_glob}/techlef/sky130_fd_sc_hd__nom.tlef"],
        capture_output=True, text=True, timeout=30)
    paths = [p for p in find.stdout.strip().split("\n")
             if p and not p.startswith("[INFO")]
    lef_path = next((p for p in paths if p.endswith(".lef")), "")
    tlef_path = next((p for p in paths if p.endswith(".tlef")), "")
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
