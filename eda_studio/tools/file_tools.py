"""文件读写 tools。闭包捕获 design_dir。"""
from pathlib import Path


def make_file_tools(design_dir: Path):
    """工厂函数:闭包捕获 design_dir,返回所有文件操作 tools。"""
    def write_rtl_fn(args: dict, ctx) -> dict:
        filename = args["filename"]
        content = args["content"]
        path = design_dir / "rtl" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return {"content": [{"type": "text", "text": f"已写入 {path}"}], "terminate": False}

    def read_rtl_fn(args: dict, ctx) -> dict:
        filename = args["filename"]
        path = design_dir / "rtl" / filename
        if not path.exists():
            return {"content": [{"type": "text", "text": f"文件不存在: {filename}"}], "terminate": False}
        return {"content": [{"type": "text", "text": path.read_text()}], "terminate": False}

    def list_design_files_fn(args: dict, ctx) -> dict:
        lines = []
        for sub in ["rtl", "sim", "synth", "pnr", "gds"]:
            d = design_dir / sub
            if d.exists():
                for f in sorted(d.iterdir()):
                    lines.append(f"{sub}/{f.name}")
        return {"content": [{"type": "text", "text": "\n".join(lines) or "(空)"}], "terminate": False}

    def read_sdc_fn(args: dict, ctx) -> dict:
        path = design_dir / "pnr" / "uart.sdc"
        if not path.exists():
            return {"content": [{"type": "text", "text": "无 SDC 约束文件"}], "terminate": False}
        return {"content": [{"type": "text", "text": path.read_text()}], "terminate": False}

    def write_sdc_fn(args: dict, ctx) -> dict:
        content = args["content"]
        path = design_dir / "pnr" / "uart.sdc"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return {"content": [{"type": "text", "text": f"已写入 {path}"}], "terminate": False}

    return {
        "write_rtl": write_rtl_fn, "read_rtl": read_rtl_fn,
        "list_design_files": list_design_files_fn,
        "read_sdc": read_sdc_fn, "write_sdc": write_sdc_fn,
    }
