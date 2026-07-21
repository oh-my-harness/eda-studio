"""klayout 导出 GDSII executor。

klayout 用 ruby 脚本(-r),RBA::Layout API 通过 LEFDEFReaderConfiguration
读取 tech LEF + macro LEF + 标准单元 GDS + DEF,导出含真实版图的 GDS。

必须用 LEFDEFReaderConfiguration,否则 DEF 的 component 不会被解析为
instance,标准单元会变成独立 top cell(空方框,无真实版图)。
"""
import subprocess

from ..shell_safety import ShellSafetyError, run_shell, to_container_path
from .base import ExecutorContext, find_pdk_files


def gds_executor(ctx: dict) -> dict:
    ectx = ExecutorContext.from_ctx(ctx)
    design_dir = ectx.design_dir
    docker_cfg = ectx.docker_config
    shell_cfg = ectx.shell_config
    dcfg = ectx.design
    def_file = design_dir / "pnr" / f"{dcfg.top_module}_pnr.def"
    gds_dir = design_dir / "gds"
    gds_dir.mkdir(parents=True, exist_ok=True)
    gds_out = gds_dir / f"{dcfg.top_module}.gds"
    if not def_file.exists():
        return {"output": f"DEF 文件不存在: {def_file}",
                "structured": {"success": False}}

    # PDK 路径:tech LEF + macro LEF + 标准单元 GDS。
    # LEFDEF reader 需要 LEF 把 DEF component 解析为 instance,
    # macro_layout_files(GDS) 提供每个 cell 的真实版图。
    pdk = find_pdk_files(docker_cfg, [
        "techlef/sky130_fd_sc_hd__nom.tlef",
        "lef/sky130_fd_sc_hd.lef",
        "gds/sky130_fd_sc_hd.gds",
    ])
    tlef_path = pdk["techlef/sky130_fd_sc_hd__nom.tlef"]
    lef_path = pdk["lef/sky130_fd_sc_hd.lef"]
    gds_lib_path = pdk["gds/sky130_fd_sc_hd.gds"]
    if not tlef_path or not lef_path or not gds_lib_path:
        return {"output": f"PDK 未找到: tlef={tlef_path} lef={lef_path} gds={gds_lib_path}",
                "structured": {"success": False}}

    def_path = to_container_path(def_file, docker_cfg)
    gds_path = to_container_path(gds_out, docker_cfg)
    # LEFDEFReaderConfiguration: 配置 LEF 文件 + macro GDS,
    # read_lef_with_def=true 让 read(DEF) 时一并加载 LEF。
    # LoadLayoutOptions.lefdef_config= 绑定到 Layout.read(def, opts)。
    rb = f"""\
ly = RBA::Layout.new
cfg = RBA::LEFDEFReaderConfiguration.new
cfg.lef_files = ["{tlef_path}", "{lef_path}"]
cfg.macro_layout_files = ["{gds_lib_path}"]
cfg.read_lef_with_def = true
opts = RBA::LoadLayoutOptions.new
opts.lefdef_config = cfg
ly.read("{def_path}", opts)
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
