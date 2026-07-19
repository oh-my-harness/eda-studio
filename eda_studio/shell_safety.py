"""EDA 工具命令执行:白名单检查 + docker exec 包装。"""
import subprocess
from pathlib import Path
from .config import ShellConfig, DockerConfig


class ShellSafetyError(Exception):
    """命令未通过白名单检查。"""


def run_shell(cmd: list, cwd: Path, docker_config: DockerConfig,
              shell_config: ShellConfig) -> subprocess.CompletedProcess:
    """在 Docker 容器内执行 EDA 工具命令,执行前做白名单检查。

    - cmd[0] 必须在 shell_config.allowed_commands 里
    - cmd 拼接后不能含 shell_config.denied_args 里的危险字符
    - 用 bash -lc 包装(容器 entrypoint 通过 login profile 设 PATH)
    - 本地 designs/ 目录挂载到容器 /work/designs/,cwd 显式前缀剥离转换
    """
    if not cmd:
        raise ShellSafetyError("空命令")
    tool = cmd[0]
    if tool not in shell_config.allowed_commands:
        raise ShellSafetyError(f"工具 {tool!r} 不在白名单 {shell_config.allowed_commands}")

    cmdline = " ".join(cmd)
    for danger in shell_config.denied_args:
        if danger in cmdline:
            raise ShellSafetyError(f"命令含危险字符 {danger!r}: {cmdline}")

def to_container_cwd(cwd: Path, docker_config: DockerConfig) -> str:
    """host designs/ 下的 cwd → 容器内工作目录路径。

    与 run_shell 的路径映射一致:host 仓库根 designs/ 挂载到容器 workdir/。
    cwd 必须在 designs/ 子树内,否则抛 ShellSafetyError(避免容器访问挂载外路径)。
    """
    host_designs = Path("designs").resolve()
    try:
        rel = cwd.relative_to(host_designs)
    except ValueError:
        raise ShellSafetyError(f"cwd {cwd} 不在 designs/ 下")
    return f"{docker_config.workdir}/{rel}"


def to_container_path(host_path: Path, docker_config: DockerConfig) -> str:
    """host designs/ 下的任意路径 → 容器内绝对路径。

    供 EDA 工具命令里的文件路径参数用(run_shell 只转 cwd,不转 cmd 参数)。
    host_path 必须在 designs/ 子树内,否则抛 ShellSafetyError。
    """
    host_designs = Path("designs").resolve()
    try:
        rel = host_path.resolve().relative_to(host_designs)
    except ValueError:
        raise ShellSafetyError(f"路径 {host_path} 不在 designs/ 下")
    return f"{docker_config.workdir}/{rel}"


def run_shell(cmd: list, cwd: Path, docker_config: DockerConfig,
              shell_config: ShellConfig) -> subprocess.CompletedProcess:
    """在 Docker 容器内执行 EDA 工具命令,执行前做白名单检查。

    - cmd[0] 必须在 shell_config.allowed_commands 里
    - cmd 拼接后不能含 shell_config.denied_args 里的危险字符
    - 用 bash -lc 包装(容器 entrypoint 通过 login profile 设 PATH)
    - 本地 designs/ 目录挂载到容器 workdir/,cwd 经 to_container_cwd 转换
    - 注意:cmd 里的文件路径参数需调用方自行用 to_container_path 转容器路径
    """
    if not cmd:
        raise ShellSafetyError("空命令")
    tool = cmd[0]
    if tool not in shell_config.allowed_commands:
        raise ShellSafetyError(f"工具 {tool!r} 不在白名单 {shell_config.allowed_commands}")

    cmdline = " ".join(cmd)
    for danger in shell_config.denied_args:
        if danger in cmdline:
            raise ShellSafetyError(f"命令含危险字符 {danger!r}: {cmdline}")

    container_cwd = to_container_cwd(cwd, docker_config)

    docker_cmd = [
        "docker", "exec", "-w", container_cwd,
        docker_config.container,
        "bash", "-lc", cmdline,
    ]
    return subprocess.run(docker_cmd, capture_output=True, text=True, timeout=600)
