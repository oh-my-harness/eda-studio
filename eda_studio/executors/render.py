"""渲染 GDS → PNG executor。

用 gdstk 读 GDS + matplotlib 渲染。klayout 的 LayoutView.save_image 在
-b 批处理模式下只写白图(无 GUI 渲染上下文),无法用于 headless 渲染;
gdstk+matplotlib 不依赖 X11,在容器内直接出图。

脚本在容器内用 python3 运行(gdstk/matplotlib 蚀装在容器镜像里)。
"""
import subprocess
import textwrap
from pathlib import Path
from ..shell_safety import run_shell, to_container_path, ShellSafetyError, _as_docker_config


# sky130 常用 layer/datatype → 颜色映射(近似 KLayout sky130A.lyp)。
# 未列出的 layer 用默认灰色。
_LAYER_COLORS = {
    (68, 20): "#888888", (68, 44): "#888888", (68, 16): "#888888",   # li1
    (69, 20): "#a52a2a", (69, 44): "#a52a2a",                          # met1
    (70, 20): "#2266ff", (70, 44): "#2266ff",                          # met2
    (71, 20): "#22cc22", (71, 44): "#22cc22",                          # met3
    (72, 20): "#ff8800",                                               # met4
    (81, 4): "#cc44cc", (81, 23): "#cc44cc",                           # via
    (64, 16): "#d040d0", (64, 20): "#d040d0", (64, 59): "#d040d0",    # nwell
    (65, 20): "#40d0d0",                                               # tap
    (66, 20): "#ff6666", (66, 44): "#ff6666", (66, 15): "#ff6666",    # diff
    (67, 16): "#66ff66", (67, 20): "#66ff66", (67, 44): "#66ff66",    # poly
    (78, 44): "#ff44ff", (93, 44): "#44dddd",
    (94, 20): "#dd44dd", (95, 20): "#dddd44",
    (122, 16): "#44dddd", (236, 0): "#dddddd",
    (8, 2): "#ffaaaa", (15, 0): "#eeeeee",                             # outline/label
}


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
    colors_repr = repr(_LAYER_COLORS)
    # 容器内跑的 python 脚本:gdstk 读 GDS,flatten 后按 layer 上色,matplotlib 出图。
    script = f'''\
import gdstk, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection
import numpy as np

lib = gdstk.read_gds("{gds_path}")
top = lib.top_level()[0]
top.flatten()
polys = top.get_polygons()

by_layer = {{}}
for p in polys:
    by_layer.setdefault((p.layer, p.datatype), []).append(p.points)

colors = {colors_repr}
fig, ax = plt.subplots(figsize=(16, 12), dpi=100)
ax.set_facecolor("white")

all_x, all_y = [], []
for key, patches in by_layer.items():
    color = colors.get(key, "#cccccc")
    pc = PatchCollection([MplPolygon(p, closed=True) for p in patches],
                         facecolor=color, edgecolor=color, linewidth=0.05, alpha=0.9)
    ax.add_collection(pc)
    for p in patches:
        all_x.append(p[:, 0]); all_y.append(p[:, 1])

all_x = np.concatenate(all_x); all_y = np.concatenate(all_y)
ax.set_xlim(all_x.min(), all_x.max()); ax.set_ylim(all_y.min(), all_y.max())
ax.set_aspect("equal"); ax.set_title("GDS Layout", fontsize=14)
plt.tight_layout()
plt.savefig("{png_path}", dpi=100, facecolor="white")
print(f"polygons={{len(polys)}} layers={{len(by_layer)}}")
'''
    script_file = gds_dir / "render.py"
    script_file.write_text(textwrap.dedent(script))
    script_container = to_container_path(script_file, docker_cfg)
    try:
        result = run_shell(["python3", script_container],
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
