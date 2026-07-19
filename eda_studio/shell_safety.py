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

    host_designs = Path("designs").resolve()
    try:
        rel = cwd.relative_to(host_designs)
        container_cwd = f"{docker_config.workdir}/{rel}"
    except ValueError:
        raise ShellSafetyError(f"cwd {cwd} 不在 designs/ 下")


    docker_cmd = [
        "docker", "exec", "-w", container_cwd,
        docker_config.container,
        "bash", "-lc", cmdline,
    ]
    return subprocess.run(docker_cmd, capture_output=True, text=True, timeout=600)
