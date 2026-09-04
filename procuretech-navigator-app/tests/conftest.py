import sys
from pathlib import Path

# procuretech-navigator-app をパッケージ探索パスへ（app.* を import 可能にする）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
