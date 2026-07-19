"""klayout 批处理渲染 GDS → PNG。

klayout -b -r 用 ruby 脚本:RBA::Layout 读 GDS,RBA::LayoutView save_image 导 PNG。
容器内 headless 运行,无需 X11。
"""
import subprocess
from pathlib import Path
from ..shell_safety import run_shell, to_container_path, ShellSafetyError, _as_docker_config


def render_executor(ctx: dict) -> dict:
    design_dir = Path(ctx["context"]["design_dir"])
    docker_cfg = _as_docker_config(ctx["context"]["docker_config"])
    shell_cfg = ctx["context"]["shell_config"]
    gds_file = design_dir / "gds" / "uart.gds"
    gds_dir = design_dir / "gds"
    gds_dir.mkdir(parents=True, exist_ok=True)
    png_out = gds_dir / "uart.png"

    if not gds_file.exists():
        return {"output": f"GDS 文件不存在: {gds_file}",
                "structured": {"success": False}}

    gds_path = to_container_path(gds_file, docker_cfg)
    png_path = to_container_path(png_out, docker_cfg)
    # ruby 脚本:读 GDS,创建 view,save_image 导 PNG
    rb = f"""\
ly = RBA::Layout.new
ly.read("{gds_path}")
view = RBA::LayoutView.new
view.set_config("background-color", "#FFFFFF")
view.show_layout(ly, false)
view.set_active_layer(ly.layer(0, 0))
view.zoom_fit
view.save_image("{png_path}", 1600, 1200)
"""
    rb_file = gds_dir / "render.rb"
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
    success = result.returncode == 0 and png_out.exists()
    return {
        "output": report,
        "structured": {"success": success,
                       "png_path": str(png_out)},
    }
