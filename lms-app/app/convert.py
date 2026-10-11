"""PDF をページ画像にする。配置は PDF に書かれたものをそのまま写す。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class ConvertError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def pdf_to_pngs(data: bytes, on_status=None) -> list[bytes]:
    if shutil.which("pdftoppm") is None:
        raise ConvertError("PDF のページ画像化には poppler が必要です")
    if not data.startswith(b"%PDF"):
        raise ConvertError("PDF ではありません")

    def status(text: str) -> None:
        if on_status:
            on_status(text)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "deck.pdf"
        src.write_bytes(data)
        try:
            status("PDF をページごとの画像にしています")
            subprocess.run(
                ["pdftoppm", "-png", str(src), str(root / "page")],
                check=True,
                timeout=180,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise ConvertError("PDF をページ画像にできませんでした") from e
        except subprocess.TimeoutExpired as e:
            raise ConvertError("PDF の変換が時間内に終わりませんでした") from e
        pages = sorted(root.glob("page-*.png"))
        if not pages:
            raise ConvertError("PDF のページ画像ができませんでした")
        status(f"{len(pages)} ページの画像ができました")
        return [page.read_bytes() for page in pages]


def pdf_page_texts(data: bytes) -> list[str]:
    """文字レイヤーのある PDF から、ページごとの本文を取る。画像だけのページは空文字。"""
    if shutil.which("pdftotext") is None:
        raise ConvertError("PDF の文字取り出しには poppler が必要です")
    if not data.startswith(b"%PDF"):
        raise ConvertError("PDF ではありません")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "deck.pdf"
        src.write_bytes(data)
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", str(src), "-"],
                check=True,
                timeout=120,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise ConvertError("PDF から文字を読み取れませんでした") from e
        except subprocess.TimeoutExpired as e:
            raise ConvertError("PDF の文字取り出しが時間内に終わりませんでした") from e
    parts = proc.stdout.decode("utf-8", errors="replace").split("\f")
    if parts and parts[-1] == "":
        parts.pop()
    return [part.strip() for part in parts]
