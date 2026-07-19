"""yosys 综合 executor。"""
from pathlib import Path
from ..shell_safety import run_shell, ShellSafetyError


def synthesize_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]
    rtl_files = sorted(f for f in (design_dir / "rtl").glob("*.v") if f.name != "tb_uart.v")
    synth_dir = design_dir / "synth"
    synth_dir.mkdir(parents=True, exist_ok=True)
    json_out = synth_dir / "netlist.json"
    v_out = synth_dir / "netlist.v"

    script = (
        f"read_verilog {' '.join(str(f.relative_to(design_dir.parent)) for f in rtl_files)}; "
        f"synth -top uart; stat; "
        f"write_json {json_out}; write_verilog {v_out}"
    )
    try:
        result = run_shell(["yosys", "-q", "-p", script], cwd=synth_dir,
                           docker_config=docker_cfg, shell_config=shell_cfg)
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = result.stdout + result.stderr
    (synth_dir / "report.txt").write_text(report)
    return {
        "output": report,
        "structured": {"success": result.returncode == 0 and json_out.exists(),
                       "report_path": str(synth_dir / "report.txt")},
    }
