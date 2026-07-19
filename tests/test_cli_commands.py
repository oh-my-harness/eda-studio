"""init/check CLI 子命令测试。不依赖真实 EDA 工具和 LLM API。"""
import sys
from pathlib import Path
from unittest.mock import patch
import pytest


def test_init_copies_template(tmp_path, monkeypatch):
    """init uart 复制 templates/uart/ 到 designs/uart/。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli_commands import cmd_init
    rc = cmd_init("uart")
    assert rc == 0
    req = tmp_path / "designs" / "uart" / "requirement.md"
    tb = tmp_path / "designs" / "uart" / "rtl" / "tb_uart.v"
    assert req.is_file(), f"requirement.md not found at {req}"
    assert tb.is_file(), f"tb_uart.v not found at {tb}"
    assert req.read_text().startswith("# UART")


def test_init_refuses_existing(tmp_path, monkeypatch):
    """designs/uart/ 已存在时 init 报错退出。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    from eda_studio.cli_commands import cmd_init
    rc = cmd_init("uart")
    assert rc == 1


def test_init_unknown_template(tmp_path, monkeypatch):
    """未知模板名报错并列出可用模板。"""
    monkeypatch.chdir(tmp_path)
    from eda_studio.cli_commands import cmd_init
    rc = cmd_init("nonexistent")
    assert rc == 1
