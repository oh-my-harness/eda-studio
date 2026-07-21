"""从 designs/<name>/design.yaml 读取 design 配置。

避免在 executor 里硬编码模块名/testbench 名。
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModuleSpec:
    """单个 RTL 模块的设计规格(对应一个 LLM step)。"""
    id: str               # step 后缀(rtl_<id>)
    name: str             # step 显示名
    file: str             # 输出文件名(如 uart_tx.v)
    module_name: str      # Verilog 模块名
    prompt_hint: str      # prompt 提示(模块职责/接口)


@dataclass
class DesignConfig:
    """Design 配置。"""
    top_module: str
    tb_module: str
    modules: list = field(default_factory=list)  # list[ModuleSpec]

    @property
    def rtl_step_ids(self) -> list:
        """rtl step 的完整 id 列表(如 ['rtl_tx', 'rtl_rx', 'rtl_top'])。"""
        return [f"rtl_{m.id}" for m in self.modules]


def load_design_config(design_dir: Path) -> DesignConfig:
    """从 design_dir/design.yaml 读配置。不存在则按目录名推断。"""
    cfg_file = design_dir / "design.yaml"
    if cfg_file.exists():
        raw = yaml.safe_load(cfg_file.read_text())
        modules = [
            ModuleSpec(
                id=m["id"], name=m["name"], file=m["file"],
                module_name=m["module_name"], prompt_hint=m["prompt_hint"],
            )
            for m in raw.get("modules", [])
        ]
        return DesignConfig(
            top_module=raw.get("top_module", design_dir.name),
            tb_module=raw.get("tb_module", f"tb_{design_dir.name}"),
            modules=modules,
        )
    # fallback:按目录名推断(单模块)
    name = design_dir.name
    return DesignConfig(
        top_module=name, tb_module=f"tb_{name}",
        modules=[ModuleSpec(id="top", name=name, file=f"{name}.v",
                            module_name=name, prompt_hint=f"设计 {name} 模块")],
    )
