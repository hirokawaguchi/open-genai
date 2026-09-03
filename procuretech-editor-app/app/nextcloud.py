"""Nextcloud（WebDAV）連携（任意）。

外部 Word 変換 API は成功時に変換結果を Nextcloud 上のフォルダ（`nextcloud_path`）へ
出力する契約のため、そのフォルダを再帰ダウンロードして取得する。参照実装
（procureTechMarkdownEditor の `nextcloud_sync.py`）の download 系のみを、ローカル
ファイルを介さないメモリ版として httpx で移植する。

環境変数（`NEXTCLOUD_URL` / `NEXTCLOUD_USERNAME` / `NEXTCLOUD_PASSWORD`）が未設定の
場合は無効（`is_configured()` が False）。DAV ルートは `NEXTCLOUD_DAV_ROOT`
（既定 `remote.php/dav/files/sync`）で切り替え可能。
"""

from __future__ import annotations

import os
from urllib.parse import quote, unquote
from xml.etree import ElementTree

import httpx

NEXTCLOUD_URL = os.environ.get("NEXTCLOUD_URL", "").rstrip("/")
NEXTCLOUD_USERNAME = os.environ.get("NEXTCLOUD_USERNAME", "")
NEXTCLOUD_PASSWORD = os.environ.get("NEXTCLOUD_PASSWORD", "")
DAV_ROOT = os.environ.get("NEXTCLOUD_DAV_ROOT", "remote.php/dav/files/sync").strip("/")
TIMEOUT = float(os.environ.get("NEXTCLOUD_TIMEOUT", "60"))


def is_configured() -> bool:
    return bool(NEXTCLOUD_URL and NEXTCLOUD_USERNAME and NEXTCLOUD_PASSWORD)


def _base_url() -> str:
    return f"{NEXTCLOUD_URL}/{DAV_ROOT}"


def _normalize_remote_path(path: str) -> str:
    path = unquote(path or "").strip("/").replace("\\", "/")
    if path.startswith(f"{DAV_ROOT}/"):
        path = path[len(DAV_ROOT) + 1 :]
    while "//" in path:
        path = path.replace("//", "/")
    return path


def _client() -> httpx.Client:
    return httpx.Client(
        auth=(NEXTCLOUD_USERNAME, NEXTCLOUD_PASSWORD),
        headers={"OCS-APIRequest": "true"},
        timeout=TIMEOUT,
    )


def _url_for(path: str) -> str:
    return f"{_base_url()}/{quote(_normalize_remote_path(path))}"


def _download_recursive(
    client: httpx.Client, remote_path: str, base_name: str, out: dict[str, bytes]
) -> None:
    remote_path = _normalize_remote_path(remote_path)
    res = client.request(
        "PROPFIND", _url_for(remote_path), headers={"Depth": "1"}
    )
    if res.status_code not in (207, 200):
        return
    tree = ElementTree.fromstring(res.content)
    items = tree.findall(".//{DAV:}response")
    for item in items[1:]:  # 先頭はフォルダ自身
        href_el = item.find(".//{DAV:}href")
        if href_el is None or not href_el.text:
            continue
        item_path = _normalize_remote_path(href_el.text)
        rt = item.find(".//{DAV:}resourcetype")
        is_dir = rt is not None and rt.find(".//{DAV:}collection") is not None
        if base_name not in item_path:
            continue
        rel = item_path.split(base_name, 1)[1].lstrip("/")
        if is_dir:
            _download_recursive(client, item_path, base_name, out)
        elif rel:
            g = client.get(_url_for(item_path))
            if g.status_code == 200:
                out[rel] = g.content


def download_tree(remote_path: str) -> dict[str, bytes]:
    """Nextcloud のフォルダを再帰ダウンロードし {相対パス: bytes} を返す。

    失敗・未設定時は空 dict。相対パスはフォルダ名（basename）以降の部分。
    """
    if not is_configured():
        return {}
    out: dict[str, bytes] = {}
    base_name = os.path.basename(_normalize_remote_path(remote_path))
    try:
        with _client() as client:
            _download_recursive(client, remote_path, base_name, out)
    except Exception as e:  # noqa: BLE001
        print(f"[editor-nextcloud] download 失敗 {remote_path}: {e}")
    return out
