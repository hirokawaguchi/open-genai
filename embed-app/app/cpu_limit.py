"""埋め込み推論がホストの全コアを使わないようにする。

sentence-transformers / PyTorch は既定でオンラインの CPU 数だけスレッドを立てる。
ナレッジ登録はチャンクの数だけこれを繰り返すため、チャットの CPU 推論と同時に
マシンが埋まる。スレッド数は EMBED_NUM_THREADS（既定 2）に抑える。
"""

from __future__ import annotations

import os

DEFAULT_THREADS = 2

_BLAS_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def embed_num_threads(default: int = DEFAULT_THREADS) -> int:
    raw = os.environ.get("EMBED_NUM_THREADS", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < 1:
        return default
    return value


def apply_blas_env(threads: int) -> None:
    """torch を import する前に呼ぶ。既に指定された値は上書きしない。"""
    for name in _BLAS_VARS:
        os.environ.setdefault(name, str(threads))
