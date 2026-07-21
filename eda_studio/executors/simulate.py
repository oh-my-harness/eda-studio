"""verilator 仿真 executor。"""
import subprocess

from ..shell_safety import ShellSafetyError, run_shell, to_container_cwd, to_container_path
from .base import ExecutorContext


def _parse_verilator_output(stderr: str, stdout: str) -> str:
    return f"--- stderr ---\n{stderr}\n--- stdout ---\n{stdout}"


def simulate_executor(ctx: dict) -> dict:
    """verilator 仿真。tb_<top>.v 是预置 fixture,rtl_files 排除它。

    两步:
    1. verilator --binary 编译走 run_shell(白名单校验),产出 sim_out 二进制。
    2. 运行 sim_out:它是 verilator 的编译产物(不是 shell 工具),不应进
       run_shell 的 allowed_commands 白名单。直接构造 docker exec 在容器内跑。
    """
    ectx = ExecutorContext.from_ctx(ctx)
    design_dir = ectx.design_dir
    docker_cfg = ectx.docker_config
    shell_cfg = ectx.shell_config
    dcfg = ectx.design

    tb_filename = f"{dcfg.tb_module}.v"
    rtl_files = [f for f in (design_dir / "rtl").glob("*.v") if f.name != tb_filename]
    tb_file = design_dir / "rtl" / tb_filename
    if not tb_file.exists():
        return {"output": f"testbench 缺失: {tb_filename}", "structured": {"success": False}}

    cmd = [
        "verilator", "--binary", "--timing",
        "-Wno-fatal",  # warning 不当 error(timescale/unused signal 等不影响功能)
        "--top-module", dcfg.tb_module,
        *[to_container_path(f, docker_cfg) for f in rtl_files],
        to_container_path(tb_file, docker_cfg),
        "-o", "sim_out",
    ]
    sim_dir = design_dir / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run_shell(cmd, cwd=sim_dir, docker_config=docker_cfg, shell_config=shell_cfg)
        # sim_out 是编译产物不是工具,直接 docker exec 跑,绕过白名单。
        # verilator --binary -o sim_out 把二进制放在 obj_dir/sim_out 下,
        # 不是 sim_dir/sim_out。
        container_cwd = to_container_cwd(sim_dir, docker_cfg)
        run_docker_cmd = [
            "docker", "exec", "-w", container_cwd,
            docker_cfg.container,
            "bash", "-lc", "./obj_dir/sim_out",
        ]
        run_result = subprocess.run(run_docker_cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"output": "timeout", "structured": {"success": False}}
    except ShellSafetyError as e:
        return {"output": str(e), "structured": {"success": False, "safety_error": True}}

    report = _parse_verilator_output(result.stderr, run_result.stdout)
    (sim_dir / "report.txt").write_text(report)

    # success 不能只看 returncode:testbench 用 $finish 退出时 returncode=0,
    # 无论 TEST PASSED 还是 TEST FAILED。必须解析 stdout 里的测试结果。
    stdout = run_result.stdout or ""
    test_passed = "TEST PASSED" in stdout
    test_failed = "TEST FAILED" in stdout or "TEST FAILED: timeout" in stdout
    success = run_result.returncode == 0 and test_passed and not test_failed

    return {
        "output": report,
        "structured": {"success": success,
                       "report_path": str(sim_dir / "report.txt")},
    }
