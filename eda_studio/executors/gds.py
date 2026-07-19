"""klayout 导出 GDSII executor。"""
from pathlib import Path
from ..shell_safety import run_shell, to_container_path, ShellSafetyError


def gds_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]
    def_file = design_dir / "pnr" / "uart_pnr.def"
    gds_dir = design_dir / "gds"
    gds_dir.mkdir(parents=True, exist_ok=True)
    gds_out = gds_dir / "uart.gds"

    # 路径参数转容器内绝对路径
    def_path = to_container_path(def_file, docker_cfg)
    gds_path = to_container_path(gds_out, docker_cfg)
    tcl = f"""
load {def_path}
gds write {gds_path}
exit
"""
    try:
        result = run_shell(["klayout", "-b", "-r", "-cmd", tcl],
                           cwd=gds_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    return {
        "output": report,
        "structured": {"success": result.returncode == 0 and gds_out.exists(),
                       "gds_path": str(gds_out)},
    }
