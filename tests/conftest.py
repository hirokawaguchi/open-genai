from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
BACKEND = ROOT / "backend"

for path in (SHARED, BACKEND):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def load_service_module(relative_path: str):
    """サービス配下の app/*.py を import パス衝突なく読み込む。"""
    path = ROOT / relative_path
    module_name = f"testmod_{path.parent.parent.name.replace('-', '_')}_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
