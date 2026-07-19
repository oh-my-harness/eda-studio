from eda_studio.prompts import RTL_MODULE_PROMPT, DEBUG_FIX_PROMPT, DRC_FIX_PROMPT, load_requirement, build_prompts
from eda_studio.design_config import ModuleSpec


def _make_modules():
    return [
        ModuleSpec(id="tx", name="发送器", file="uart_tx.v", module_name="uart_tx", prompt_hint="设计发送器"),
        ModuleSpec(id="rx", name="接收器", file="uart_rx.v", module_name="uart_rx", prompt_hint="设计接收器"),
        ModuleSpec(id="top", name="顶层", file="uart.v", module_name="uart", prompt_hint="设计顶层"),
    ]


def test_rtl_module_prompt_has_requirement_placeholder():
    assert "{requirement}" in RTL_MODULE_PROMPT


def test_debug_fix_prompt_no_duplicate_requirement():
    assert "{requirement}" not in DEBUG_FIX_PROMPT


def test_build_prompts_injects_requirement():
    modules = _make_modules()
    prompts = build_prompts("UART 9600 baud", modules)
    assert "UART 9600 baud" in prompts["rtl_tx"]
    assert "UART 9600 baud" in prompts["rtl_rx"]
    assert "UART 9600 baud" in prompts["rtl_top"]
    assert "{requirement}" not in prompts["rtl_tx"]
    assert prompts["debug_fix"] == DEBUG_FIX_PROMPT
    assert prompts["drc_fix"] == DRC_FIX_PROMPT


def test_build_prompts_uses_module_spec():
    modules = _make_modules()
    prompts = build_prompts("req", modules)
    assert "uart_tx" in prompts["rtl_tx"]
    assert "uart_rx" in prompts["rtl_rx"]
    assert "uart.v" in prompts["rtl_top"]


def test_load_requirement_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_requirement("nonexistent") == ""


def test_load_requirement_reads_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    (tmp_path / "designs" / "uart" / "requirement.md").write_text("# UART\n波特率 115200")
    assert "115200" in load_requirement("uart")
