# EDA Studio — Agent Context

## 项目概述

EDA Studio 是基于 [Senza](https://github.com/oh-my-harness/Senza) SDK 的开源 EDA 自动化芯片设计项目，完成 RTL→GDS 全流程。独立仓库，通过 `pip install senza-sdk` 引入依赖。

设计文档：`../Senza/docs/superpowers/specs/2026-07-18-eda-studio-design.md`

## Docker 容器使用方法

### 镜像

`hpretl/iic-osic-tools:latest` — 包含全部 EDA 工具 + Sky130 PDK，ARM64 原生支持。

### 启动容器

```bash
docker run -d --name eda-tools \
  -v $(pwd)/designs:/work/designs \
  -e PDK=sky130A \
  hpretl/iic-osic-tools:latest \
  --skip sleep infinity
```

**注意**：必须用 `--skip sleep infinity`。镜像的 entrypoint 脚本默认启动 VNC/X11 桌面环境，`--skip` 跳过 UI 启动并执行后续命令。直接传 `tail -f /dev/null` 会被 entrypoint 拒绝（报 "Unexpected option"）。

### 调用容器内工具

**必须用 `bash -lc`**（login shell）。entrypoint 脚本通过 login profile 设置 PATH 和环境变量，直接 `docker exec eda-tools verilator` 会报 "executable file not found"。

```bash
# 正确 ✓
docker exec eda-tools bash -lc 'verilator --version'
docker exec eda-tools bash -lc 'yosys -V'
docker exec eda-tools bash -lc 'openroad -version'

# 错误 ✗
docker exec eda-tools verilator --version
```

### 已验证的工具版本

| 工具 | 版本 | 路径 |
|------|------|------|
| verilator | 5.048 | `/foss/tools/bin/verilator` |
| yosys | 0.66 | `/foss/tools/bin/yosys` |
| openroad | 26Q2-2270 | `/foss/tools/bin/openroad` |
| magic | 8.3 rev 664 | `/foss/tools/bin/magic` |
| netgen | 1.5.321 | `/foss/tools/bin/netgen` |
| klayout | 0.30.9 | `/foss/tools/klayout/klayout` |

### Sky130 PDK

- `PDK=sky130A`，`PDKPATH=/foss/pdks/sky130A`
- 标准单元库：`sky130_fd_sc_hd`（在 `/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/`）
- 其他可用库：`sky130_fd_io`、`sky130_fd_pr`、`sky130_fd_sc_hvl`、`sky130_ml_xx_hd`
- **注意**：容器默认 `STD_CELL_LIBRARY` 可能是 `sg13g2_stdcell`（IHP PDK），使用前需在 config 或命令中显式指定 `sky130_fd_sc_hd`

### magic / netgen 特殊参数

这两个工具是 Tcl 解释器，版本检查方式与常规不同：

```bash
# magic — 无 -version 参数，用 -noconsole -dnull 启动后看输出
docker exec eda-tools bash -lc 'magic -noconsole -dnull <<< "exit"' | head -5

# netgen — 需 -noconsole 避免 display 错误
docker exec eda-tools bash -lc 'netgen -noconsole <<< "exit"' | head -5
```

### run_shell() 实现要点

senza 的 `executors/` 中 `run_shell()` 函数封装 docker exec 调用，要点：

1. 用 `bash -lc` 包装命令
2. 宿主机 `designs/` 路径映射到容器 `/work/designs/`，cwd 需转换
3. 设置超时（EDA 工具可能长时间运行）
4. 捕获 stdout/stderr 生成报告

```python
def run_shell(cmd: list[str], cwd: Path, docker_config: DockerConfig) -> subprocess.CompletedProcess:
    container_cwd = str(cwd).replace(str(Path("designs").resolve()), docker_config.workdir)
    docker_cmd = [
        "docker", "exec", "-w", container_cwd,
        docker_config.container,
        "bash", "-lc", " ".join(cmd),
    ]
    return subprocess.run(docker_cmd, capture_output=True, text=True, timeout=600)
```

### 容器管理

```bash
# 停止
docker stop eda-tools

# 启动（已创建）
docker start eda-tools

# 删除重建
docker rm -f eda-tools
docker run -d --name eda-tools -v $(pwd)/designs:/work/designs -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity
```
