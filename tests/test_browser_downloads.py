from __future__ import annotations

import asyncio
from pathlib import Path

from conftest import load_service_module

downloads = load_service_module("browser-app/app/downloads.py")
session = load_service_module("browser-app/app/session.py")


def test_finished_names_skip_partials_and_hidden_files() -> None:
    assert downloads.is_finished_name("report.pdf") is True
    assert downloads.is_finished_name("report.pdf.crdownload") is False
    assert downloads.is_finished_name("report.tmp") is False
    assert downloads.is_finished_name(".ready-abc") is False
    assert downloads.safe_download_name("../report.pdf") == "report.pdf"
    assert downloads.safe_download_name("a/../../etc/passwd") == "passwd"
    assert downloads.safe_download_name("") is None
    assert downloads.safe_download_name("..") is None


def test_japanese_locale_is_written_before_launch(tmp_path: Path) -> None:
    downloads.write_japanese_locale(tmp_path)
    prefs = (tmp_path / "chrome" / "Default" / "Preferences").read_text(encoding="utf-8")
    local = (tmp_path / "chrome" / "Local State").read_text(encoding="utf-8")
    assert "ja-JP,ja" in prefs
    assert '"app_locale": "ja"' in local


def test_download_prefs_pin_the_session_directory(tmp_path: Path) -> None:
    target = tmp_path / "Downloads"
    downloads.write_download_prefs(tmp_path, target)
    text = (tmp_path / "chrome" / "Default" / "Preferences").read_text(encoding="utf-8")
    assert str(target) in text
    assert '"prompt_for_download": false' in text


def test_collect_moves_a_stable_file_and_drops_oversized(tmp_path: Path) -> None:
    directory = tmp_path / "Downloads"
    directory.mkdir()
    (directory / "note.txt").write_bytes(b"hello")
    (directory / "big.bin.crdownload").write_bytes(b"still-writing")
    (directory / "huge.bin").write_bytes(b"too-big")
    session.downloads.MAX_BYTES = 5

    async def collect() -> session.BrowserSession:
        sess = session.BrowserSession(
            id="abcdefghijklmnop",
            user_id="user-1",
            display=100,
            vnc_port=5900,
            width=1280,
            height=800,
            profile=tmp_path,
        )
        await session._collect_downloads(sess, directory)
        return sess

    sess = asyncio.run(collect())

    assert len(sess.downloads) == 1
    name, path = next(iter(sess.downloads.values()))
    assert name == "note.txt"
    assert path.read_bytes() == b"hello"
    assert path.name.startswith(".ready-")
    assert not (directory / "note.txt").exists()
    assert (directory / "big.bin.crdownload").exists()
    assert not (directory / "huge.bin").exists()
    assert any("大きすぎる" in note for note in sess.download_notes)
