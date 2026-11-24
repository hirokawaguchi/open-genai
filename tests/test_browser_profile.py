from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from conftest import load_service_module

session = load_service_module("browser-app/app/session.py")


def test_profile_key_hides_the_user_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session, "PROFILE_ROOT", tmp_path)
    home = session.chrome_home_for("user@example.jp")
    assert home.parent == tmp_path
    assert "example.jp" not in home.name
    assert home.name == session.profile_key("user@example.jp")
    assert session.chrome_home_for("user@example.jp") == home
    assert session.chrome_home_for("other") != home
    with pytest.raises(session.BrowserStartError):
        session.profile_key("  ")


def test_chromium_uses_the_saved_profile(tmp_path: Path) -> None:
    args = session._chromium_args(tmp_path, 1280, 800)
    assert f"--user-data-dir={tmp_path / 'chrome'}" in args
    assert f"--disk-cache-size={session.DISK_CACHE_BYTES}" in args


def test_trim_removes_cache_and_keeps_cookies(tmp_path: Path) -> None:
    chrome = tmp_path / "chrome"
    cookies = chrome / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True)
    cookies.write_bytes(b"login")
    cache = chrome / "Default" / "Cache" / "data_0"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"x" * 100)
    assert session.trim_profile_cache(chrome, limit=50) is True
    assert cookies.read_bytes() == b"login"
    assert not cache.exists()


def test_trim_keeps_a_small_cache(tmp_path: Path) -> None:
    cache = tmp_path / "chrome" / "Default" / "Cache"
    cache.mkdir(parents=True)
    (cache / "data_0").write_bytes(b"tiny")
    assert session.trim_profile_cache(tmp_path / "chrome", limit=1000) is False
    assert (cache / "data_0").read_bytes() == b"tiny"


def test_prepare_clears_locks_and_downloads(tmp_path: Path) -> None:
    home = tmp_path / "home"
    chrome = home / "chrome"
    chrome.mkdir(parents=True)
    (chrome / "SingletonLock").symlink_to("host-1")
    kept = chrome / "Default" / "Cookies"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"stay")
    leftover = chrome / "Default" / "Downloads" / "note.txt"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"secret")
    session.prepare_chrome_home(home)
    assert kept.read_bytes() == b"stay"
    assert not (chrome / "SingletonLock").exists()
    assert not leftover.exists()


def test_kill_removes_runtime_and_keeps_cookies(tmp_path: Path) -> None:
    runtime = tmp_path / "run"
    (runtime / "Downloads").mkdir(parents=True)
    chrome_home = tmp_path / "keep"
    cookies = chrome_home / "chrome" / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True)
    cookies.write_bytes(b"stay")
    sess = session.BrowserSession(
        id="abcdefghijklmnop",
        user_id="user-1",
        display=100,
        vnc_port=5900,
        width=1280,
        height=800,
        profile=runtime,
        chrome_home=chrome_home,
    )
    asyncio.run(sess.kill())
    assert not runtime.exists()
    assert cookies.read_bytes() == b"stay"
