"""AI アプリ実行履歴向けの入力整形。

backend/app/main.py から切り離し、回帰テストが FastAPI 無しで読めるようにする。
"""

from __future__ import annotations

from typing import Any


def history_inputs(inputs: Any) -> Any:
    """履歴用に inputs.files の本文(base64)を落とす。ファイル名は残す。"""
    if not isinstance(inputs, dict):
        return inputs
    files = inputs.get("files")
    if not isinstance(files, list):
        return inputs
    slim_files: list[Any] = []
    for entry in files:
        if not isinstance(entry, dict):
            slim_files.append(entry)
            continue
        inner = []
        for f in entry.get("files") or []:
            if isinstance(f, dict):
                inner.append({"filename": f.get("filename", "file"), "content": ""})
            else:
                inner.append(f)
        slim_files.append({**entry, "files": inner})
    return {**inputs, "files": slim_files}
