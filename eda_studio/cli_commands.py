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
