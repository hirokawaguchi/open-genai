"""共有ゲートウェイでも、接続のホームに他人の記録をコピーしない。"""

import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "hermes" / "acp_gateway.py"


def _load_gateway():
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.WSMsgType = types.SimpleNamespace(TEXT="TEXT", ERROR="ERROR")
    aiohttp.web = types.ModuleType("aiohttp.web")
    acp = types.ModuleType("acp")
    acp.PROTOCOL_VERSION = 1
    acp.RequestError = type("RequestError", (Exception,), {})
    acp.spawn_agent_process = None
    acp_core = types.ModuleType("acp.core")
    acp_core.Client = object
    acp_helpers = types.ModuleType("acp.helpers")
    acp_helpers.text_block = lambda text: text
    acp_schema = types.ModuleType("acp.schema")
    acp_schema.HttpHeader = lambda **kwargs: kwargs
    acp_schema.HttpMcpServer = lambda **kwargs: kwargs
    saved = {}
    for name, module in {
        "aiohttp": aiohttp,
        "acp": acp,
        "acp.core": acp_core,
        "acp.helpers": acp_helpers,
        "acp.schema": acp_schema,
    }.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module
    spec = importlib.util.spec_from_file_location("hermes_acp_gateway_under_test", GATEWAY)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


def test_turn_home_keeps_config_and_drops_prior_records(tmp_path, monkeypatch):
    source = tmp_path / "shared"
    source.mkdir()
    (source / "config.yaml").write_text("model:\n  default: demo\n", encoding="utf-8")
    (source / "SOUL.md").write_text("人格\n", encoding="utf-8")
    (source / "state.db").write_bytes(b"previous-session")
    memories = source / "memories"
    memories.mkdir()
    (memories / "note.txt").write_text("他人の記憶", encoding="utf-8")
    installs = tmp_path / "installs"
    installs.mkdir()
    os.symlink(installs, source / "installs")
    monkeypatch.setenv("HERMES_HOME", str(source))

    gateway = _load_gateway()
    home = gateway._turn_home()
    try:
        assert (home / "config.yaml").read_text(encoding="utf-8").startswith("model:")
        assert (home / "SOUL.md").read_text(encoding="utf-8") == "人格\n"
        assert not (home / "state.db").exists()
        assert not (home / "memories").exists()
        assert (home / "installs").is_symlink()
        assert Path(os.path.realpath(home / "installs")) == installs.resolve()
        assert home.stat().st_uid == os.getuid()
    finally:
        import shutil

        shutil.rmtree(home, ignore_errors=True)
