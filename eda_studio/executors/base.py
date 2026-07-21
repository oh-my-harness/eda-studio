"""Executor 公共逻辑:context 提取 + PDK 路径查找。

6 个 executor(simulate/synthesize/pnr/drc/gds/render)共享:
1. 从 ctx["context"] 提取 design_dir / docker_config / shell_config + load_design_config
2. synthesize/pnr/drc/gds 都用 docker exec ls 查 Sky130 PDK 标准单元库路径,
   且都要过滤容器 login profile 打印的 [INFO] 行

提取到这里减少重复,业务逻辑(命令构造/report 解析/success 判断)留在各 executor。
"""
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import DockerConfig, ShellConfig
from ..design_config import DesignConfig, load_design_config
from ..shell_safety import _as_docker_config, _as_shell_config


# Sky130 PDK 标准单元库在容器内的基础路径(glob 匹配 versions/* 下唯一版本)
_PDK_LIB_BASE = "/foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd"


@dataclass
class ExecutorContext:
    """从 executor ctx 字典提取的公共字段。

    executor 签名是 fn(ctx: dict) -> dict,ctx["context"] 含 design_dir /
    docker_config / shell_config(set_context_variable 设入,反序列化后是 dict)。
    """
    design_dir: Path
    docker_config: DockerConfig
    shell_config: ShellConfig
    design: DesignConfig

    @classmethod
    def from_ctx(cls, ctx: dict) -> "ExecutorContext":
        """从 executor ctx 提取公共字段并加载 design 配置。"""
        c = ctx["context"]
        design_dir = Path(c["design_dir"])
        docker_config = _as_docker_config(c["docker_config"])
        shell_config = _as_shell_config(c["shell_config"])
        design = load_design_config(design_dir)
        return cls(design_dir, docker_config, shell_config, design)


def filter_info_lines(stdout: str) -> list:
    """过滤容器 login profile 打印的 [INFO] 行,返回非空、非 [INFO] 的行列表。"""
    return [p for p in stdout.strip().split("\n") if p and not p.startswith("[INFO]")]


def find_pdk_files(docker_config: DockerConfig, subpaths: list) -> dict:
    """在 Sky130 PDK 标准单元库下查找文件,返回 {suffix: path}。

    Args:
        docker_config: 容器配置(用 container 名)。
        subpaths: 相对 _PDK_LIB_BASE 的文件子路径列表(如
            ["lib/sky130_fd_sc_hd__tt_025C_1v80.lib",
             "lef/sky130_fd_sc_hd.lef"])。

    Returns:
        {文件后缀(如 ".lib")/完整文件名(如 "sky130_fd_sc_hd.gds"): 容器内绝对路径}。
        未找到的 suffix 对应值为空字符串 ""。
        用后缀匹配;对 .gds 这类唯一文件用 basename 匹配,避免 .lib/.lef 互相误配。
    """
    glob_pattern = " ".join(f"{_PDK_LIB_BASE}/{s}" for s in subpaths)
    find = subprocess.run(
        ["docker", "exec", docker_config.container, "bash", "-lc",
         f"ls {glob_pattern}"],
        capture_output=True, text=True, timeout=30)
    paths = filter_info_lines(find.stdout)
    result = {}
    for s in subpaths:
        basename = Path(s).name
        suffix = Path(s).suffix
        # 先按 basename 精确匹配,再回退到后缀匹配
        match = next((p for p in paths if Path(p).name == basename), "")
        if not match:
            match = next((p for p in paths if p.endswith(suffix)), "")
        result[s] = match
    return result
