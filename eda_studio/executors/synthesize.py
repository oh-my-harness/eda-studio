"""yosys 综合 executor。"""
import subprocess

from ..shell_safety import ShellSafetyError, run_shell, to_container_path
from .base import ExecutorContext, find_pdk_files


def synthesize_executor(ctx: dict) -> dict:
    ectx = ExecutorContext.from_ctx(ctx)
    design_dir = ectx.design_dir
    docker_cfg = ectx.docker_config
    shell_cfg = ectx.shell_config
    dcfg = ectx.design
    tb_filename = f"{dcfg.tb_module}.v"
    rtl_files = sorted(f for f in (design_dir / "rtl").glob("*.v") if f.name != tb_filename)
    synth_dir = design_dir / "synth"
    synth_dir.mkdir(parents=True, exist_ok=True)
    json_out = synth_dir / "netlist.json"
    v_out = synth_dir / "netlist.v"

    # 路径参数转容器内绝对路径(run_shell 只转 cwd,不转 cmd 参数)
    rtl_paths = " ".join(to_container_path(f, docker_cfg) for f in rtl_files)
    json_path = to_container_path(json_out, docker_cfg)
    v_path = to_container_path(v_out, docker_cfg)
    # PDK liberty 用于 abc 映射(把 $_NOT_ 等通用门映射成 sky130 cell)
    pdk = find_pdk_files(docker_cfg, ["lib/sky130_fd_sc_hd__tt_025C_1v80.lib"])
    pdk_lib = pdk["lib/sky130_fd_sc_hd__tt_025C_1v80.lib"]
    # script 写文件用 -s 跑,避免 -p "cmd; cmd" 的分号被 denied_args 拦截
    # -noattr -noexpr:openroad read_verilog 不认属性和 reg 声明
    script = (
        f"read_verilog {rtl_paths}\n"
        f"synth -top {dcfg.top_module}\n"
        f"dfflibmap -liberty {pdk_lib}\n"
        f"abc -liberty {pdk_lib}\n"
        f"stat\n"
        f"write_json {json_path}\n"
        f"write_verilog -noattr -noexpr {v_path}\n"
    )
    script_file = synth_dir / "synth.ys"
    script_file.write_text(script)
    script_container = to_container_path(script_file, docker_cfg)
    try:
        result = run_shell(["yosys", "-q", "-s", script_container], cwd=synth_dir,
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
