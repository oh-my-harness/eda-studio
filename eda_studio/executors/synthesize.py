"""yosys 综合 executor。"""
import subprocess
from pathlib import Path
from ..shell_safety import run_shell, to_container_path, ShellSafetyError


def synthesize_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]
    rtl_files = sorted(f for f in (design_dir / "rtl").glob("*.v") if f.name != "tb_uart.v")
    synth_dir = design_dir / "synth"
    synth_dir.mkdir(parents=True, exist_ok=True)
    json_out = synth_dir / "netlist.json"
    v_out = synth_dir / "netlist.v"

    # 路径参数转容器内绝对路径(run_shell 只转 cwd,不转 cmd 参数)
    rtl_paths = " ".join(to_container_path(f, docker_cfg) for f in rtl_files)
    json_path = to_container_path(json_out, docker_cfg)
    v_path = to_container_path(v_out, docker_cfg)
    script = (
        f"read_verilog {rtl_paths}; "
        f"synth -top uart; stat; "
        f"write_json {json_path}; write_verilog {v_path}"
    )
    try:
        result = run_shell(["yosys", "-q", "-p", script], cwd=synth_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except subprocess.TimeoutExpired:
        return {"output": "timeout", "structured": {"success": False}}
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    (synth_dir / "report.txt").write_text(report)
    return {
        "output": report,
        "structured": {"success": result.returncode == 0 and json_out.exists(),
                       "report_path": str(synth_dir / "report.txt")},
    }
