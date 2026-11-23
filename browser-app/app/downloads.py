"""Chromium のダウンロードを、セッションのディレクトリで受け取って渡す。"""

from __future__ import annotations

import json
from pathlib import Path

MAX_BYTES = 50 * 1024 * 1024
MAX_PENDING = 8
_PARTIAL_SUFFIXES = (".crdownload", ".tmp", ".part")


def is_finished_name(name: str) -> bool:
    """途中のファイルや隠しファイルは、まだ渡さない。"""
    if not name or name.startswith("."):
        return False
    lower = name.lower()
    return not lower.endswith(_PARTIAL_SUFFIXES)


def safe_download_name(name: str) -> str | None:
    base = (name or "").replace("\\", "/").split("/")[-1].strip()
    if not base or base in {".", ".."} or len(base) > 180 or "\x00" in base:
        return None
    if not is_finished_name(base):
        return None
    return base


def write_download_prefs(profile: Path, download_dir: Path) -> None:
    """保存先をセッションの中に固定し、保存ダイアログを出さない。"""
    default = profile / "chrome" / "Default"
    default.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = default / "Preferences"
    prefs: dict = {}
    if prefs_path.exists():
        try:
            loaded = json.loads(prefs_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prefs = loaded
        except json.JSONDecodeError:
            prefs = {}
    prefs["download"] = {
        "default_directory": str(download_dir),
        "directory_upgrade": True,
        "prompt_for_download": False,
    }
    prefs["savefile"] = {"default_directory": str(download_dir)}
    prefs_path.write_text(json.dumps(prefs), encoding="utf-8")
    prefs_path.chmod(0o600)


def write_japanese_locale(profile: Path) -> None:
    """メニューとページの言語を日本語にする。"""
    default = profile / "chrome" / "Default"
    default.mkdir(parents=True, exist_ok=True)
    prefs_path = default / "Preferences"
    prefs: dict = {}
    if prefs_path.exists():
        try:
            loaded = json.loads(prefs_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prefs = loaded
        except json.JSONDecodeError:
            prefs = {}
    intl = prefs.get("intl")
    if not isinstance(intl, dict):
        intl = {}
    intl["accept_languages"] = "ja-JP,ja"
    intl["selected_languages"] = "ja-JP,ja"
    prefs["intl"] = intl
    prefs_path.write_text(json.dumps(prefs), encoding="utf-8")
    prefs_path.chmod(0o600)

    local_path = profile / "chrome" / "Local State"
    local: dict = {}
    if local_path.exists():
        try:
            loaded = json.loads(local_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                local = loaded
        except json.JSONDecodeError:
            local = {}
    local_intl = local.get("intl")
    if not isinstance(local_intl, dict):
        local_intl = {}
    local_intl["app_locale"] = "ja"
    local["intl"] = local_intl
    local_path.write_text(json.dumps(local), encoding="utf-8")
    local_path.chmod(0o600)
