from __future__ import annotations

import importlib.util
import itertools
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
BACKEND = ROOT / "backend"

# ROOT: `from shared.mynumber`
# SHARED: `import docextract` / `import ssrfguard`
# BACKEND: `from app import ngwords`
for path in (ROOT, SHARED, BACKEND):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

_LOAD_SEQ = itertools.count()


def load_service_module(relative_path: str):
    """サービス配下の app/*.py を import パス衝突なく読み込む。

    `from .sibling import ...` のような相対 import も、一時パッケージとして
    解決する。呼び出しごとに一意なパッケージ名を使うため、環境変数を
    差し替えて再読込するテストも干渉しない。
    """
    path = ROOT / relative_path
    # 同一ディレクトリの兄弟モジュール（例: rag-app/app/textnorm.py）を
    # パッケージなしのフォールバック import で解決できるようにする。
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    seq = next(_LOAD_SEQ)
    pkg_name = f"testmod_{path.parent.parent.name.replace('-', '_')}_{seq}"
    module_name = f"{pkg_name}.{path.stem}"

    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [parent]
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = pkg_name
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
