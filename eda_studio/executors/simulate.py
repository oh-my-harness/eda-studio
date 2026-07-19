"""verilator 仿真 executor。"""
import subprocess
from pathlib import Path
from ..shell_safety import run_shell, to_container_cwd, ShellSafetyError


def _parse_verilator_output(stderr: str, stdout: str) -> str:
    return f"--- stderr ---\n{stderr}\n--- stdout ---\n{stdout}"


def simulate_executor(ctx: dict) -> dict:
    """verilator 仿真。tb_uart.v 是预置 fixture,rtl_files 排除它。

    两步:
    1. verilator --binary 编译走 run_shell(白名单校验),产出 sim_out 二进制。
    2. 运行 sim_out:它是 verilator 的编译产物(不是 shell 工具),不应进
       run_shell 的 allowed_commands 白名单。直接构造 docker exec 在容器内跑。
    """
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = ctx["context"]["docker_config"]
    shell_cfg = ctx["context"]["shell_config"]

    rtl_files = [f for f in (design_dir / "rtl").glob("*.v") if f.name != "tb_uart.v"]
    tb_file = design_dir / "rtl" / "tb_uart.v"
    if not tb_file.exists():
        return {"output": "testbench 缺失: tb_uart.v", "structured": {"success": False}}

    cmd = [
        "verilator", "--binary", "--timing",
        "-Wall",
        "--top-module", "tb_uart",
        *[str(f) for f in rtl_files], str(tb_file),
        "-o", "sim_out",
    ]
    sim_dir = design_dir / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run_shell(cmd, cwd=sim_dir, docker_config=docker_cfg, shell_config=shell_cfg)
        # sim_out 是编译产物不是工具,直接 docker exec 跑,绕过白名单
        container_cwd = to_container_cwd(sim_dir, docker_cfg)
        run_docker_cmd = [
            "docker", "exec", "-w", container_cwd,
            docker_cfg.container,
            "bash", "-lc", "./sim_out",
        ]
        run_result = subprocess.run(run_docker_cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"output": "timeout", "structured": {"success": False}}
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = _parse_verilator_output(result.stderr, run_result.stdout)
    (sim_dir / "report.txt").write_text(report)

    return {
        "output": report,
        "structured": {"success": run_result.returncode == 0,
                       "report_path": str(sim_dir / "report.txt")},
    }
