"""OpenROAD 布局布线 executor。floorplan 由 initialize_floorplan 生成,不用 read_def。"""
import subprocess
from pathlib import Path
from ..shell_safety import run_shell, to_container_path, ShellSafetyError


def pnr_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]
    netlist = design_dir / "synth" / "netlist.v"
    pnr_dir = design_dir / "pnr"
    pnr_dir.mkdir(parents=True, exist_ok=True)

    # 路径参数转容器内绝对路径
    netlist_path = to_container_path(netlist, docker_cfg)
    def_path = to_container_path(pnr_dir / "uart_pnr.def", docker_cfg)
    tcl = f"""
read_libs sky130A/sky130_fd_sc_hd__tt_025C_1v80.lib
read_lef sky130A/sky130_fd_sc_hd.lef
read_verilog {netlist_path}
link_design uart
initialize_floorplan -utilization 40 -site unithd
place_pins -hor_layers metal2 -ver_layers metal3
global_placement
detailed_placement
global_route
detailed_route
write_def {def_path}
"""
    try:
        result = run_shell(["openroad", "-exit_on_error", "-no_splash", "-cmd", tcl],
                           cwd=pnr_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except subprocess.TimeoutExpired:
        return {"output": "timeout", "structured": {"success": False}}
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    (pnr_dir / "report.txt").write_text(report)
    return {
        "output": report,
        "structured": {"success": result.returncode == 0,
                       "report_path": str(pnr_dir / "report.txt")},
    }
