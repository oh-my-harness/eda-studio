"""init/check CLI 子命令实现。"""
import shutil
import sys
from pathlib import Path


def _templates_dir() -> Path:
    """定位 eda_studio/templates/ 目录。"""
    import eda_studio
    return Path(eda_studio.__file__).parent / "templates"


def _list_templates() -> list:
    """列出可用模板名。"""
    tdir = _templates_dir()
    if not tdir.is_dir():
        return []
    return [d.name for d in tdir.iterdir() if d.is_dir() and not d.name.startswith("_")]


def cmd_init(name: str) -> int:
    """从 templates/<name>/ 复制 design 输入文件到 designs/<name>/。

    Returns:
        0 成功, 1 失败
    """
    src = _templates_dir() / name
    if not src.is_dir():
        print(f"✗ 未知模板: {name}")
        available = _list_templates()
        if available:
            print(f"  可用模板: {', '.join(available)}")
        return 1

    dst = Path(f"designs/{name}")
    if dst.exists():
        print(f"✗ 目标已存在: {dst}(避免覆盖运行产物)")
        return 1

    shutil.copytree(src, dst)
    print(f"✓ 已初始化 {name} → {dst}")
    print(f"  下一步:")
    print(f"    docker run -d --name eda-tools -v $(pwd)/designs:/work/designs \\")
    print(f"      -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity")
    print(f"    eda-studio check")
    print(f"    python -m eda_studio run {name}")
    return 0


import json
import os
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def _check_config(config_path: str) -> tuple:
    """检查 config.yaml 可解析。返回 (ok, detail, fix_hint)。"""
    try:
        from .config import load_config
        load_config(config_path)
        return (True, "config.yaml 可解析", None)
    except FileNotFoundError:
        return (False, "config.yaml 不存在", "cp config.example.yaml config.yaml")
    except Exception as e:
        return (False, f"config.yaml 解析失败: {e}", "检查 YAML 语法")


def _check_api_key(config_path: str) -> tuple:
    """检查 API key 非空。"""
    try:
        from .config import load_config
        cfg = load_config(config_path)
        key = cfg.provider_spec.get("api_key", "")
        if not key:
            return (False, "API key 为空", "export OPENAI_API_KEY=... 并在 config.yaml 用 ${OPENAI_API_KEY}")
        return (True, f"API key 已设置({key[:4]}...{key[-4:]})", None)
    except Exception as e:
        return (False, f"读取 config 失败: {e}", None)


def _check_api_reachable(config_path: str) -> tuple:
    """检查 API 端点可达 + 模型可用。"""
    try:
        from .config import load_config
        cfg = load_config(config_path)
        key = cfg.provider_spec.get("api_key", "")
        base_url = cfg.provider_spec.get("base_url") or "https://api.openai.com/v1"
        model = cfg.model
        url = base_url.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        })
        import time
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            elapsed = (time.monotonic() - t0) * 1000
            choices = data.get("choices", [])
            if choices:
                return (True, f"API 端点可达({base_url}, {elapsed:.0f}ms), 模型 {model} 可用", None)
            return (False, f"API 响应无 choices: {data}", "检查 model 名是否正确")
    except Exception as e:
        return (False, f"API 不可达: {e}", "检查 base_url / api_key / 网络")


def _check_docker() -> tuple:
    """检查 docker 可用。"""
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return (True, "docker 可用", None)
        return (False, "docker 不可用", "启动 Docker Desktop")
    except FileNotFoundError:
        return (False, "docker 命令不存在", "安装 Docker")
    except subprocess.TimeoutExpired:
        return (False, "docker info 超时", None)


def _check_container() -> tuple:
    """检查 eda-tools 容器在跑。"""
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", "name=eda-tools", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=5)
        if "eda-tools" in r.stdout:
            return (True, "eda-tools 容器在运行", None)
        return (False, "eda-tools 容器未运行",
                "docker run -d --name eda-tools -v $(pwd)/designs:/work/designs "
                "-e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity")
    except Exception as e:
        return (False, f"检查容器失败: {e}", None)


def _check_eda_tools() -> list:
    """检查容器内 EDA 工具可用,返回 [(tool, ok, detail), ...]。"""
    tools = ["verilator", "yosys", "openroad", "magic", "klayout"]
    results = []
    for tool in tools:
        try:
            if tool == "magic":
                cmd = ["docker", "exec", "eda-tools", "bash", "-lc", "magic -noconsole -dnull <<< 'exit'"]
            else:
                cmd = ["docker", "exec", "eda-tools", "bash", "-lc", f"{tool} --version"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            output = "\n".join(l for l in (r.stdout + r.stderr).split("\n") if not l.startswith("[INFO]"))
            ok = r.returncode == 0 or (tool == "magic" and "Magic 8" in output)
            results.append((tool, ok, output.strip()[:60] if ok else f"exit {r.returncode}"))
        except subprocess.TimeoutExpired:
            results.append((tool, False, "timeout"))
        except Exception as e:
            results.append((tool, False, str(e)[:60]))
    return results


def _check_pdk() -> tuple:
    """检查 Sky130 PDK 存在。"""
    try:
        r = subprocess.run(
            ["docker", "exec", "eda-tools", "bash", "-lc",
             "ls /foss/pdks/ciel/sky130/versions/*/sky130A/libs.ref/sky130_fd_sc_hd/lib/"],
            capture_output=True, text=True, timeout=10)
        output = "\n".join(l for l in r.stdout.split("\n") if not l.startswith("[INFO]"))
        if r.returncode == 0 and output.strip():
            return (True, "Sky130 PDK 存在", None)
        return (False, "PDK 未找到", "检查容器 PDK 安装")
    except Exception as e:
        return (False, f"PDK 检查失败: {e}", None)


def cmd_check(config_path: str = "config.yaml") -> int:
    """预检环境:config / API / docker / 容器 / EDA 工具 / PDK。

    Returns:
        0 全部通过, 1 有失败项
    """
    checks = []

    ok_cfg, detail, hint = _check_config(config_path)
    checks.append(("config", ok_cfg, detail, hint))
    if ok_cfg:
        ok_key, detail, hint = _check_api_key(config_path)
        checks.append(("api_key", ok_key, detail, hint))
        if ok_key:
            ok_api, detail, hint = _check_api_reachable(config_path)
            checks.append(("api", ok_api, detail, hint))

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_docker = pool.submit(_check_docker)
        f_container = pool.submit(_check_container)
        f_pdk = pool.submit(_check_pdk)
        f_tools = pool.submit(_check_eda_tools)

        ok_d, detail, hint = f_docker.result()
        checks.append(("docker", ok_d, detail, hint))

        ok_c, detail, hint = f_container.result()
        checks.append(("container", ok_c, detail, hint))

        if ok_c:
            tool_results = f_tools.result()
            for tool, ok, detail in tool_results:
                checks.append((f"tool:{tool}", ok, detail, None if ok else f"容器内 {tool} 不可用"))

            ok_pdk, detail, hint = f_pdk.result()
            checks.append(("pdk", ok_pdk, detail, hint))

    all_ok = True
    for name, ok, detail, hint in checks:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {detail}")
        if not ok and hint:
            print(f"    → {hint}")
            all_ok = False
        elif not ok:
            all_ok = False

    print()
    if all_ok:
        print("✓ 环境检查通过,可以运行 eda-studio run <design>")
        return 0
    print("✗ 环境检查未通过,请修复上述问题")
    return 1
