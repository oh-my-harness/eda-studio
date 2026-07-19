"""klayout 导出 GDSII executor。

klayout 用 ruby 脚本(-r),RBA::Layout API 读 LEF+DEF 写 GDS。
tech LEF(.tlef) klayout 不认,只读 macro LEF(有 dummy macro warning 但能产出)。
"""
import subprocess
from pathlib import Path
from ..shell_safety import run_shell, to_container_path, ShellSafetyError, _as_docker_config


def gds_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = _as_docker_config(ctx["context"]["docker_config"])
    shell_cfg = ctx["context"]["shell_config"]
    def_file = design_dir / "pnr" / "uart_pnr.def"
    gds_dir = design_dir / "gds"
    gds_dir.mkdir(parents=True, exist_ok=True)
    gds_out = gds_dir / "uart.gds"

    if not def_file.exists():
        return {"output": f"DEF 文件不存在: {def_file}",
                "structured": {"success": False}}

    # PDK LEF 路径(同 pnr/drc executor)
    pdk_glob = "/foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd"
    find = subprocess.run(
        ["docker", "exec", docker_cfg.container, "bash", "-lc",
         f"ls {pdk_glob}/lef/sky130_fd_sc_hd.lef"],
        capture_output=True, text=True, timeout=30)
    paths = [p for p in find.stdout.strip().split("\n")
             if p and not p.startswith("[INFO")]
    lef_path = paths[0] if paths else ""
    if not lef_path:
        return {"output": "PDK LEF 未找到", "structured": {"success": False}}

    def_path = to_container_path(def_file, docker_cfg)
    gds_path = to_container_path(gds_out, docker_cfg)
    # klayout ruby 脚本:RBA::Layout 读 LEF + DEF,写 GDS
    rb = f"""\
ly = RBA::Layout.new
ly.read("{lef_path}")
ly.read("{def_path}")
ly.write("{gds_path}")
"""
    rb_file = gds_dir / "stream.rb"
    rb_file.write_text(rb)
    rb_container = to_container_path(rb_file, docker_cfg)
    try:
        result = run_shell(["klayout", "-b", "-r", rb_container],
                           cwd=gds_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except subprocess.TimeoutExpired:
        return {"output": "timeout", "structured": {"success": False}}
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    (gds_dir / "report.txt").write_text(report)
    return {
        "output": report,
        "structured": {"success": result.returncode == 0 and gds_out.exists(),
                       "gds_path": str(gds_out)},
    }
