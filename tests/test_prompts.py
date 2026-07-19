from eda_studio.prompts import RTL_TX_PROMPT, RTL_RX_PROMPT, RTL_TOP_PROMPT, DEBUG_FIX_PROMPT, DRC_FIX_PROMPT, load_requirement, build_prompts

def test_rtl_prompts_have_requirement_placeholder():
    assert "{requirement}" in RTL_TX_PROMPT
    assert "{requirement}" in RTL_RX_PROMPT
    assert "{requirement}" in RTL_TOP_PROMPT

def test_debug_fix_prompt_no_duplicate_requirement():
    assert "{requirement}" not in DEBUG_FIX_PROMPT

def test_build_prompts_injects_requirement():
    prompts = build_prompts("UART 9600 baud")
    assert "UART 9600 baud" in prompts["rtl_tx"]
    assert "UART 9600 baud" in prompts["rtl_rx"]
    assert "UART 9600 baud" in prompts["rtl_top"]
    assert "{requirement}" not in prompts["rtl_tx"]
    assert prompts["debug_fix"] == DEBUG_FIX_PROMPT
    assert prompts["drc_fix"] == DRC_FIX_PROMPT

def test_load_requirement_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_requirement("nonexistent") == ""

def test_load_requirement_reads_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    (tmp_path / "designs" / "uart" / "requirement.md").write_text("# UART\n波特率 115200")
    assert "115200" in load_requirement("uart")
