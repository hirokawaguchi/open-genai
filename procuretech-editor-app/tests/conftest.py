import os
import sys
from pathlib import Path

# procuretech-editor-app をパッケージ探索パスへ（app.* を import 可能にする）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 開発時: 署名検証をスキップ（HMAC 未設定）。
os.environ.setdefault("INTERNAL_SIGNING_SECRET", "")
os.environ.setdefault("EDITOR_DB_PATH", "/tmp/pte_test.db")
