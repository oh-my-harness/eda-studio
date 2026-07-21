"""OpenROAD 布局布线 executor。floorplan 由 initialize_floorplan 生成,不用 read_def。"""
import subprocess

from ..shell_safety import ShellSafetyError, run_shell, to_container_path
from .base import ExecutorContext, find_pdk_files


def pnr_executor(ctx: dict) -> dict:
    ectx = ExecutorContext.from_ctx(ctx)
    design_dir = ectx.design_dir
    docker_cfg = ectx.docker_config
    shell_cfg = ectx.shell_config
    dcfg = ectx.design
    netlist = design_dir / "synth" / "netlist.v"
    pnr_dir = design_dir / "pnr"
    pnr_dir.mkdir(parents=True, exist_ok=True)

    # 路径参数转容器内绝对路径
    netlist_path = to_container_path(netlist, docker_cfg)
    def_path = to_container_path(pnr_dir / f"{dcfg.top_module}_pnr.def", docker_cfg)
    # PDK 路径:容器内 /foss/pdks 下查找 sky130A(lib/lef/tlef 用绝对路径)。
    # tech LEF(.tlef) 含 LAYER/SITE 定义,必须先于 macro LEF 读取。
    pdk = find_pdk_files(docker_cfg, [
        "lib/sky130_fd_sc_hd__tt_025C_1v80.lib",
        "lef/sky130_fd_sc_hd.lef",
        "techlef/sky130_fd_sc_hd__nom.tlef",
    ])
    lib_path = pdk["lib/sky130_fd_sc_hd__tt_025C_1v80.lib"]
    lef_path = pdk["lef/sky130_fd_sc_hd.lef"]
    tlef_path = pdk["techlef/sky130_fd_sc_hd__nom.tlef"]
    if not lib_path or not lef_path or not tlef_path:
        return {"output": f"PDK 未找到: lib={lib_path} lef={lef_path} tlef={tlef_path}",
                "structured": {"success": False}}
    tcl = f"""\
read_liberty {lib_path}
read_lef {tlef_path}
read_lef {lef_path}
read_verilog {netlist_path}
link_design {dcfg.top_module}
initialize_floorplan -utilization 40 -site unithd -core_space 2
make_tracks
place_pins -hor_layers met3 -ver_layers met2
global_placement
detailed_placement
global_route
write_def {def_path}
"""
    tcl_file = pnr_dir / "pnr.tcl"
    tcl_file.write_text(tcl)
    tcl_container = to_container_path(tcl_file, docker_cfg)
    try:
        result = run_shell(["openroad", "-no_splash", "-exit", tcl_container],
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
