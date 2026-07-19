"""klayout 导出 GDSII executor。

klayout 用 ruby 脚本(-r),RBA::Layout API 先读 std cell GDS 再读 DEF,写 GDS。
必须先读 std cell GDS,否则 DEF 引用的 cell 会被当成 dummy macro(空方框)。
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

    # PDK 路径:标准单元 GDS(包含每个 cell 的真实版图)。
    # 必须先于 DEF 读取,DEF 的 component 按 cell 名引用 GDS 中已加载的 cell。
    pdk_glob = "/foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd"
    find = subprocess.run(
        ["docker", "exec", docker_cfg.container, "bash", "-lc",
         f"ls {pdk_glob}/gds/sky130_fd_sc_hd.gds"],
        capture_output=True, text=True, timeout=30)
    paths = [p for p in find.stdout.strip().split("\n")
             if p and not p.startswith("[INFO")]
    gds_lib_path = paths[0] if paths else ""
    if not gds_lib_path:
        return {"output": "PDK std cell GDS 未找到",
                "structured": {"success": False}}

    def_path = to_container_path(def_file, docker_cfg)
    gds_path = to_container_path(gds_out, docker_cfg)
    # klayout ruby 脚本:先读 std cell GDS,再读 DEF。
    # DEF 的 component 按 cell 名引用 GDS 中已加载的 cell,从而得到真实版图;
    # 若不先读 GDS,klayout 会为每个 cell 创建 dummy macro(空方框)。
    rb = f"""\
ly = RBA::Layout.new
ly.read("{gds_lib_path}")
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
