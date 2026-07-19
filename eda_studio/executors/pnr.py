"""OpenROAD 布局布线 executor。floorplan 由 initialize_floorplan 生成,不用 read_def。"""
import subprocess
from pathlib import Path
from ..shell_safety import run_shell, to_container_path, to_container_cwd, ShellSafetyError, _as_docker_config


def pnr_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = _as_docker_config(ctx["context"]["docker_config"])
    shell_cfg = ctx["context"]["shell_config"]
    netlist = design_dir / "synth" / "netlist.v"
    pnr_dir = design_dir / "pnr"
    pnr_dir.mkdir(parents=True, exist_ok=True)

    # 路径参数转容器内绝对路径
    netlist_path = to_container_path(netlist, docker_cfg)
    def_path = to_container_path(pnr_dir / "uart_pnr.def", docker_cfg)
    # PDK 路径:容器内 /foss/pdks 下查找 sky130A(lib/lef 用绝对路径)
    pdk_glob = "/foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd"
    import glob as _glob
    lib_candidates = _glob.glob(pdk_glob + "/lib/sky130_fd_sc_hd__tt_025C_1v80.lib")
    lef_candidates = _glob.glob(pdk_glob + "/lef/sky130_fd_sc_hd.lef")
    # glob 在 host 跑,但容器挂载 /foss/pdks 可能不在 host。用 docker exec 查。
    if not lib_candidates or not lef_candidates:
        find = subprocess.run(
            ["docker", "exec", docker_cfg.container, "bash", "-lc",
             f"ls {pdk_glob}/lib/sky130_fd_sc_hd__tt_025C_1v80.lib {pdk_glob}/lef/sky130_fd_sc_hd.lef"],
            capture_output=True, text=True, timeout=30)
        paths = find.stdout.strip().split("\n")
        lib_path = next((p for p in paths if p.endswith(".lib")), "")
        lef_path = next((p for p in paths if p.endswith(".lef")), "")
    else:
        lib_path = lib_candidates[0]
        lef_path = lef_candidates[0]
    if not lib_path or not lef_path:
        return {"output": "PDK lib/lef 未找到", "structured": {"success": False}}
    tcl = f"""\
read_liberty {lib_path}
read_lef {lef_path}
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
