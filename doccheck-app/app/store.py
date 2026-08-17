"""書類領域分割チェックの SQLite 永続化。"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from . import consensus, ocr

DB_PATH = os.environ.get("DOCCHECK_DB_PATH", "/data/doccheck.db")
PUBLIC_ENDPOINT = (os.environ.get("DOCCHECK_PUBLIC_ENDPOINT") or "").rstrip("/")
DATA_DIR = Path(os.environ.get("DOCCHECK_DATA_DIR", "/data"))
# バッチ（本番想定）の既定割当人数: 庁内1 + 外部2
DEFAULT_ASSIGNEES = int(os.environ.get("DOCCHECK_ASSIGNEES", "3"))
MIN_AGREE = int(os.environ.get("DOCCHECK_MIN_AGREE", "2"))
# 単件読み取りテスト／デモ向けのソロ割当
SINGLE_ASSIGNEES = int(os.environ.get("DOCCHECK_SINGLE_ASSIGNEES", "1"))
DEMO_ASSIGNEES = int(os.environ.get("DOCCHECK_DEMO_ASSIGNEES", str(SINGLE_ASSIGNEES)))
TRAP_RATIO = float(os.environ.get("DOCCHECK_TRAP_RATIO", "0.1"))
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
DEMO_FORM_PATH = SAMPLES_DIR / "demo-form.png"
DEMO_TEMPLATE_ID = "demo-template"

_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _db = conn
    return conn


def init_db() -> None:
    ocr.ensure_dirs()
    db = connect()
    with _lock:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS form_templates (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              description TEXT,
              sample_image_path TEXT,
              ocr_mode TEXT NOT NULL DEFAULT 'fallback',
              created_by TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS region_templates (
              id TEXT PRIMARY KEY,
              template_id TEXT NOT NULL,
              name TEXT NOT NULL,
              page_index INTEGER NOT NULL DEFAULT 0,
              x REAL NOT NULL,
              y REAL NOT NULL,
              w REAL NOT NULL,
              h REAL NOT NULL,
              field_type TEXT NOT NULL DEFAULT 'text',
              is_handwriting INTEGER NOT NULL DEFAULT 1,
              is_trap INTEGER NOT NULL DEFAULT 0,
              trap_answer TEXT,
              sort_order INTEGER NOT NULL DEFAULT 0,
              group_id TEXT,
              group_name TEXT,
              line_index INTEGER NOT NULL DEFAULT 0,
              part_index INTEGER NOT NULL DEFAULT 0,
              choice_options TEXT,
              FOREIGN KEY (template_id) REFERENCES form_templates(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS batches (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              template_id TEXT NOT NULL,
              status TEXT NOT NULL,
              pages_per_document INTEGER NOT NULL DEFAULT 1,
              auto_dispatch INTEGER NOT NULL DEFAULT 1,
              assignees INTEGER,
              dpi INTEGER,
              total_images INTEGER NOT NULL DEFAULT 0,
              total_documents INTEGER NOT NULL DEFAULT 0,
              processed_documents INTEGER NOT NULL DEFAULT 0,
              error_count INTEGER NOT NULL DEFAULT 0,
              last_error TEXT,
              created_by TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (template_id) REFERENCES form_templates(id)
            );
            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY,
              template_id TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              batch_id TEXT,
              source_name TEXT,
              created_by TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (template_id) REFERENCES form_templates(id),
              FOREIGN KEY (batch_id) REFERENCES batches(id)
            );
            CREATE TABLE IF NOT EXISTS pages (
              id TEXT PRIMARY KEY,
              document_id TEXT NOT NULL,
              page_index INTEGER NOT NULL,
              image_path TEXT NOT NULL,
              dpi INTEGER,
              FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
              UNIQUE(document_id, page_index)
            );
            CREATE TABLE IF NOT EXISTS region_instances (
              id TEXT PRIMARY KEY,
              document_id TEXT NOT NULL,
              region_template_id TEXT,
              name TEXT NOT NULL,
              page_index INTEGER NOT NULL DEFAULT 0,
              crop_path TEXT NOT NULL,
              ocr_text TEXT,
              ocr_confidence REAL DEFAULT 0,
              ocr_vision_text TEXT,
              ocr_vision_confidence REAL DEFAULT 0,
              field_type TEXT NOT NULL DEFAULT 'text',
              is_trap INTEGER NOT NULL DEFAULT 0,
              trap_answer TEXT,
              status TEXT NOT NULL DEFAULT 'pending',
              adopted_text TEXT,
              group_id TEXT,
              group_name TEXT,
              line_index INTEGER NOT NULL DEFAULT 0,
              part_index INTEGER NOT NULL DEFAULT 0,
              choice_options TEXT,
              FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS check_tasks (
              id TEXT PRIMARY KEY,
              region_instance_id TEXT NOT NULL,
              token TEXT NOT NULL UNIQUE,
              tier TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              assignee_user_id TEXT,
              locked_at TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (region_instance_id) REFERENCES region_instances(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS check_answers (
              id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL UNIQUE,
              region_instance_id TEXT NOT NULL,
              answer_text TEXT NOT NULL,
              tier TEXT NOT NULL,
              checker_user_id TEXT,
              checker_label TEXT,
              is_unreadable INTEGER NOT NULL DEFAULT 0,
              is_blank INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              FOREIGN KEY (task_id) REFERENCES check_tasks(id) ON DELETE CASCADE,
              FOREIGN KEY (region_instance_id) REFERENCES region_instances(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS user_scores (
              user_id TEXT PRIMARY KEY,
              display_name TEXT,
              points INTEGER NOT NULL DEFAULT 0,
              checks_count INTEGER NOT NULL DEFAULT 0,
              adopted_count INTEGER NOT NULL DEFAULT 0,
              trap_correct INTEGER NOT NULL DEFAULT 0,
              trap_wrong INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_region_tmpl_template
              ON region_templates(template_id);
            CREATE INDEX IF NOT EXISTS idx_region_inst_doc
              ON region_instances(document_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_status_tier
              ON check_tasks(status, tier);
            CREATE INDEX IF NOT EXISTS idx_answers_region
              ON check_answers(region_instance_id);
            CREATE INDEX IF NOT EXISTS idx_batches_created
              ON batches(created_at);
            """
        )
        # 既存 DB 向けマイグレーション（CREATE IF NOT EXISTS では列は増えない）
        cols = {
            r["name"]
            for r in db.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "batch_id" not in cols:
            db.execute("ALTER TABLE documents ADD COLUMN batch_id TEXT")
        if "source_name" not in cols:
            db.execute("ALTER TABLE documents ADD COLUMN source_name TEXT")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_batch ON documents(batch_id)"
        )
        tmpl_cols = {
            r["name"]
            for r in db.execute("PRAGMA table_info(form_templates)").fetchall()
        }
        if "ocr_mode" not in tmpl_cols:
            db.execute(
                "ALTER TABLE form_templates ADD COLUMN ocr_mode TEXT NOT NULL "
                "DEFAULT 'fallback'"
            )
        rt_cols = {
            r["name"]
            for r in db.execute("PRAGMA table_info(region_templates)").fetchall()
        }
        for col, decl in (
            ("group_id", "TEXT"),
            ("group_name", "TEXT"),
            ("line_index", "INTEGER NOT NULL DEFAULT 0"),
            ("part_index", "INTEGER NOT NULL DEFAULT 0"),
            ("choice_options", "TEXT"),
        ):
            if col not in rt_cols:
                db.execute(f"ALTER TABLE region_templates ADD COLUMN {col} {decl}")
        ri_cols = {
            r["name"]
            for r in db.execute("PRAGMA table_info(region_instances)").fetchall()
        }
        for col, decl in (
            ("group_id", "TEXT"),
            ("group_name", "TEXT"),
            ("line_index", "INTEGER NOT NULL DEFAULT 0"),
            ("part_index", "INTEGER NOT NULL DEFAULT 0"),
            ("choice_options", "TEXT"),
            ("ocr_vision_text", "TEXT"),
            ("ocr_vision_confidence", "REAL DEFAULT 0"),
        ):
            if col not in ri_cols:
                db.execute(f"ALTER TABLE region_instances ADD COLUMN {col} {decl}")
        ca_cols = {
            r["name"]
            for r in db.execute("PRAGMA table_info(check_answers)").fetchall()
        }
        if "is_blank" not in ca_cols:
            db.execute(
                "ALTER TABLE check_answers ADD COLUMN is_blank INTEGER NOT NULL DEFAULT 0"
            )
        db.commit()
    _ensure_demo_template()


def _ensure_demo_template() -> None:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT id FROM form_templates WHERE id = ?", ("demo-template",)
        ).fetchone()
        if not row:
            now = _now_iso()
            db.execute(
                "INSERT INTO form_templates (id, name, description, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "demo-template",
                    "デモ申請書",
                    "PoC 用のサンプル帳票テンプレート（座標は正規化 0–1）",
                    "system",
                    now,
                ),
            )
            regions = [
                ("氏名（姓）", 0.10, 0.12, 0.28, 0.06),
                ("氏名（名）", 0.40, 0.12, 0.28, 0.06),
                ("生年月日", 0.10, 0.22, 0.35, 0.06),
                ("電話番号", 0.50, 0.22, 0.35, 0.06),
                ("住所1", 0.10, 0.32, 0.75, 0.08),
                ("申請日", 0.10, 0.80, 0.30, 0.06),
            ]
            for i, (name, x, y, w, h) in enumerate(regions):
                db.execute(
                    "INSERT INTO region_templates "
                    "(id, template_id, name, page_index, x, y, w, h, field_type, "
                    "is_handwriting, is_trap, trap_answer, sort_order) "
                    "VALUES (?, ?, ?, 0, ?, ?, ?, ?, 'text', 1, 0, NULL, ?)",
                    (str(uuid.uuid4()), "demo-template", name, x, y, w, h, i),
                )
            # トラップ（既知正解）
            db.execute(
                "INSERT INTO region_templates "
                "(id, template_id, name, page_index, x, y, w, h, field_type, "
                "is_handwriting, is_trap, trap_answer, sort_order) "
                "VALUES (?, ?, ?, 0, ?, ?, ?, ?, 'text', 0, 1, ?, ?)",
                (
                    str(uuid.uuid4()),
                    "demo-template",
                    "【トラップ】確認コード",
                    0.70,
                    0.80,
                    0.20,
                    0.06,
                    "OPEN-OK",
                    len(regions),
                ),
            )
            db.commit()
    # デモ見本画像（未設定なら同梱画像を登録）
    try:
        if DEMO_FORM_PATH.is_file():
            tmpl = get_template("demo-template")
            if tmpl and not tmpl.get("sample_image_path"):
                b64 = "data:image/png;base64," + base64.b64encode(
                    DEMO_FORM_PATH.read_bytes()
                ).decode("ascii")
                set_sample_image("demo-template", b64)
    except Exception:  # noqa: BLE001
        pass


def public_url_for(token: str) -> str:
    if not PUBLIC_ENDPOINT:
        return f"/public/c/{token}"
    return f"{PUBLIC_ENDPOINT}/public/c/{token}"


# ----- templates -----


def list_templates() -> list[dict[str, Any]]:
    db = connect()
    rows = db.execute(
        "SELECT id, name, description, ocr_mode, created_by, created_at FROM form_templates "
        "ORDER BY created_at DESC"
    ).fetchall()
    out = []
    for r in rows:
        regions = list_region_templates(r["id"])
        out.append(
            {
                **dict(r),
                "ocr_mode": normalize_ocr_mode(r["ocr_mode"]),
                "region_count": len(regions),
                "regions": regions,
            }
        )
    return out


MAX_REGIONS = int(os.environ.get("DOCCHECK_MAX_REGIONS", "50"))


def get_template(
    template_id: str, *, include_sample: bool = False
) -> dict[str, Any] | None:
    db = connect()
    row = db.execute(
        "SELECT id, name, description, sample_image_path, ocr_mode, created_by, created_at "
        "FROM form_templates WHERE id = ?",
        (template_id,),
    ).fetchone()
    if not row:
        return None
    out: dict[str, Any] = {
        **dict(row),
        "ocr_mode": normalize_ocr_mode(row["ocr_mode"]),
        "regions": list_region_templates(template_id),
        "max_regions": MAX_REGIONS,
        "has_sample_image": bool(row["sample_image_path"]),
    }
    if include_sample and row["sample_image_path"]:
        path = Path(row["sample_image_path"])
        if path.is_file():
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            out["sample_image_data_url"] = f"data:image/png;base64,{b64}"
    return out


def create_template(
    *,
    name: str,
    description: str | None,
    created_by: str,
    regions: list[dict[str, Any]] | None = None,
    ocr_mode: str | None = None,
) -> dict[str, Any]:
    tid = str(uuid.uuid4())
    now = _now_iso()
    regs = list(regions or [])
    if len(regs) > MAX_REGIONS:
        raise ValueError(f"領域は最大 {MAX_REGIONS} 件までです")
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO form_templates "
            "(id, name, description, ocr_mode, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tid, name, description or "", normalize_ocr_mode(ocr_mode), created_by, now),
        )
        for i, reg in enumerate(regs):
            _insert_region_template(db, tid, reg, i)
        db.commit()
    return get_template(tid)  # type: ignore[return-value]


def update_template_meta(
    template_id: str, *, ocr_mode: str | None = None
) -> dict[str, Any] | None:
    """テンプレのメタ情報（OCR モードなど）を更新する。"""
    if not get_template(template_id):
        return None
    db = connect()
    with _lock:
        if ocr_mode is not None:
            db.execute(
                "UPDATE form_templates SET ocr_mode = ? WHERE id = ?",
                (normalize_ocr_mode(ocr_mode), template_id),
            )
        db.commit()
    return get_template(template_id)


def replace_regions(template_id: str, regions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not get_template(template_id):
        return None
    if len(regions) > MAX_REGIONS:
        raise ValueError(f"領域は最大 {MAX_REGIONS} 件までです")
    for i, reg in enumerate(regions):
        try:
            x, y, w, h = float(reg["x"]), float(reg["y"]), float(reg["w"]), float(reg["h"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"領域{i + 1}: 座標が不正です") from e
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.001 or y + h > 1.001:
            raise ValueError(f"領域{i + 1}: 正規化座標は 0–1 の範囲で w,h > 0 にしてください")
    db = connect()
    with _lock:
        db.execute("DELETE FROM region_templates WHERE template_id = ?", (template_id,))
        for i, reg in enumerate(regions):
            _insert_region_template(db, template_id, reg, i)
        db.commit()
    return get_template(template_id, include_sample=False)


def set_sample_image(template_id: str, image_b64: str) -> dict[str, Any]:
    """帳票見本画像を保存する（領域編集の下絵）。"""
    tmpl = get_template(template_id)
    if not tmpl:
        raise ValueError("テンプレートが見つかりません")
    raw = ocr.decode_image_bytes(image_b64)
    ocr.ensure_dirs()
    templates_dir = DATA_DIR / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    out = templates_dir / f"{template_id}_sample.png"
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.save(out, format="PNG")
    db = connect()
    with _lock:
        db.execute(
            "UPDATE form_templates SET sample_image_path = ? WHERE id = ?",
            (str(out), template_id),
        )
        db.commit()
    return get_template(template_id, include_sample=True)  # type: ignore[return-value]


def delete_template(template_id: str) -> dict[str, Any]:
    """帳票テンプレートを削除する（参照中は拒否）。"""
    if template_id == DEMO_TEMPLATE_ID:
        raise ValueError("デモテンプレートは削除できません")
    tmpl = get_template(template_id)
    if not tmpl:
        raise ValueError("テンプレートが見つかりません")
    db = connect()
    doc_count = int(
        db.execute(
            "SELECT COUNT(*) AS c FROM documents WHERE template_id = ?",
            (template_id,),
        ).fetchone()["c"]
    )
    batch_count = int(
        db.execute(
            "SELECT COUNT(*) AS c FROM batches WHERE template_id = ?",
            (template_id,),
        ).fetchone()["c"]
    )
    if doc_count or batch_count:
        raise ValueError(
            f"書類 {doc_count} 件・バッチ {batch_count} 件が参照しているため削除できません。"
            "先に書類／バッチを削除してください。"
        )
    sample_path = tmpl.get("sample_image_path")
    with _lock:
        db.execute("DELETE FROM form_templates WHERE id = ?", (template_id,))
        db.commit()
    if sample_path:
        try:
            Path(sample_path).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    return {
        "ok": True,
        "deleted_template_id": template_id,
        "name": tmpl.get("name"),
    }


OCR_MODES = {"ppocr", "fallback", "always"}


def normalize_ocr_mode(value: str | None) -> str:
    """テンプレの OCR モードを正規化する（不正値は fallback）。"""
    v = (value or "").strip().lower()
    return v if v in OCR_MODES else "fallback"


FIELD_TYPES = {
    "text_single",
    "text_multi",
    "date",
    "number",
    "choice",
    "choice_multi",
}


def normalize_field_type(value: str | None) -> str:
    """種別を新しい語彙に正規化する（旧 'text' → 'text_single'）。"""
    v = (value or "").strip()
    if v in ("", "text"):
        return "text_single"
    if v in FIELD_TYPES:
        return v
    return "text_single"


def _dump_choice_options(value: Any) -> str | None:
    """選択肢を JSON 配列文字列に。空なら None。"""
    if not value:
        return None
    if isinstance(value, str):
        items = [s.strip() for s in value.splitlines()]
    elif isinstance(value, (list, tuple)):
        items = [str(s).strip() for s in value]
    else:
        return None
    items = [s for s in items if s]
    if not items:
        return None
    return json.dumps(items, ensure_ascii=False)


def _load_choice_options(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(s) for s in raw if str(s).strip()]
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(data, list):
        return [str(s) for s in data if str(s).strip()]
    return []


def _insert_region_template(
    db: sqlite3.Connection, template_id: str, reg: dict[str, Any], order: int
) -> None:
    db.execute(
        "INSERT INTO region_templates "
        "(id, template_id, name, page_index, x, y, w, h, field_type, "
        "is_handwriting, is_trap, trap_answer, sort_order, "
        "group_id, group_name, line_index, part_index, choice_options) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            reg.get("id") or str(uuid.uuid4()),
            template_id,
            reg.get("name") or f"領域{order + 1}",
            int(reg.get("page_index") or 0),
            float(reg["x"]),
            float(reg["y"]),
            float(reg["w"]),
            float(reg["h"]),
            normalize_field_type(reg.get("field_type")),
            1 if reg.get("is_handwriting", True) else 0,
            1 if reg.get("is_trap") else 0,
            reg.get("trap_answer"),
            int(reg.get("sort_order", order)),
            (reg.get("group_id") or None) or None,
            (str(reg.get("group_name")).strip() if reg.get("group_name") else None),
            int(reg.get("line_index") or 0),
            int(reg.get("part_index") or 0),
            _dump_choice_options(reg.get("choice_options")),
        ),
    )


def list_region_templates(template_id: str) -> list[dict[str, Any]]:
    db = connect()
    rows = db.execute(
        "SELECT id, template_id, name, page_index, x, y, w, h, field_type, "
        "is_handwriting, is_trap, trap_answer, sort_order, "
        "group_id, group_name, line_index, part_index, choice_options "
        "FROM region_templates WHERE template_id = ? ORDER BY sort_order, name",
        (template_id,),
    ).fetchall()
    return [
        {
            **dict(r),
            "x": float(r["x"]),
            "y": float(r["y"]),
            "w": float(r["w"]),
            "h": float(r["h"]),
            "field_type": normalize_field_type(r["field_type"]),
            "is_handwriting": bool(r["is_handwriting"]),
            "is_trap": bool(r["is_trap"]),
            "line_index": int(r["line_index"] or 0),
            "part_index": int(r["part_index"] or 0),
            "choice_options": _load_choice_options(r["choice_options"]),
        }
        for r in rows
    ]


# ----- documents -----


def list_documents(*, batch_id: str | None = None) -> list[dict[str, Any]]:
    db = connect()
    if batch_id:
        rows = db.execute(
            "SELECT d.id, d.template_id, d.title, d.status, d.batch_id, d.source_name, "
            "d.created_by, d.created_at, t.name AS template_name "
            "FROM documents d JOIN form_templates t ON t.id = d.template_id "
            "WHERE d.batch_id = ? ORDER BY d.created_at ASC",
            (batch_id,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT d.id, d.template_id, d.title, d.status, d.batch_id, d.source_name, "
            "d.created_by, d.created_at, t.name AS template_name "
            "FROM documents d JOIN form_templates t ON t.id = d.template_id "
            "ORDER BY d.created_at DESC LIMIT 200"
        ).fetchall()
    return [dict(r) for r in rows]


def get_document(doc_id: str) -> dict[str, Any] | None:
    db = connect()
    row = db.execute(
        "SELECT d.id, d.template_id, d.title, d.status, d.batch_id, d.source_name, "
        "d.created_by, d.created_at, t.name AS template_name "
        "FROM documents d JOIN form_templates t ON t.id = d.template_id "
        "WHERE d.id = ?",
        (doc_id,),
    ).fetchone()
    if not row:
        return None
    pages = db.execute(
        "SELECT id, page_index, image_path, dpi FROM pages "
        "WHERE document_id = ? ORDER BY page_index",
        (doc_id,),
    ).fetchall()
    regions = db.execute(
        "SELECT id, name, page_index, crop_path, ocr_text, ocr_confidence, "
        "ocr_vision_text, ocr_vision_confidence, "
        "field_type, is_trap, status, adopted_text, "
        "group_id, group_name, line_index, part_index, choice_options "
        "FROM region_instances WHERE document_id = ? "
        "ORDER BY COALESCE(group_name, name), line_index, part_index, name",
        (doc_id,),
    ).fetchall()
    tasks = db.execute(
        "SELECT t.id, t.region_instance_id, t.token, t.tier, t.status, t.assignee_user_id "
        "FROM check_tasks t "
        "JOIN region_instances r ON r.id = t.region_instance_id "
        "WHERE r.document_id = ?",
        (doc_id,),
    ).fetchall()
    return {
        **dict(row),
        "pages": [dict(p) for p in pages],
        "regions": [
            {
                **dict(r),
                "field_type": normalize_field_type(r["field_type"]),
                "is_trap": bool(r["is_trap"]),
                "ocr_confidence": r["ocr_confidence"] or 0,
                "ocr_vision_text": r["ocr_vision_text"] or "",
                "ocr_vision_confidence": r["ocr_vision_confidence"] or 0,
                "choice_options": _load_choice_options(r["choice_options"]),
            }
            for r in regions
        ],
        "tasks": [
            {
                **dict(t),
                "public_url": public_url_for(t["token"]),
            }
            for t in tasks
        ],
    }


def delete_document(doc_id: str) -> dict[str, Any]:
    """書類と関連タスク・画像ファイルを削除する。"""
    doc = get_document(doc_id)
    if not doc:
        raise ValueError("書類が見つかりません")

    paths: list[Path] = []
    for p in doc.get("pages") or []:
        if p.get("image_path"):
            paths.append(Path(p["image_path"]))
    for r in doc.get("regions") or []:
        if r.get("crop_path"):
            paths.append(Path(r["crop_path"]))
    # 命名規則の取り残し（page / crop）
    images_dir = DATA_DIR / "images"
    if images_dir.is_dir():
        paths.extend(images_dir.glob(f"{doc_id}_*"))

    db = connect()
    with _lock:
        db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        db.commit()

    removed = 0
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
                removed += 1
        except Exception:  # noqa: BLE001
            pass

    return {
        "ok": True,
        "deleted_document_id": doc_id,
        "title": doc.get("title"),
        "files_removed": removed,
    }


def delete_batch(batch_id: str) -> dict[str, Any]:
    """バッチと配下の全書類を削除する。"""
    batch = get_batch(batch_id)
    if not batch:
        raise ValueError("バッチが見つかりません")

    docs = list(batch.get("documents") or [])
    deleted_docs = 0
    files_removed = 0
    for d in docs:
        try:
            res = delete_document(d["id"])
            deleted_docs += 1
            files_removed += int(res.get("files_removed") or 0)
        except ValueError:
            continue

    # ステージング残骸
    staging = DATA_DIR / "batch_staging" / batch_id
    if staging.is_dir():
        try:
            for p in staging.glob("*"):
                p.unlink(missing_ok=True)
            staging.rmdir()
        except Exception:  # noqa: BLE001
            pass

    db = connect()
    with _lock:
        db.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
        db.commit()

    return {
        "ok": True,
        "deleted_batch_id": batch_id,
        "deleted_documents": deleted_docs,
        "files_removed": files_removed,
        "name": batch.get("name"),
    }


def create_document_from_images(
    *,
    template_id: str,
    title: str,
    created_by: str,
    pages_b64: list[str],
    dpi: int | None = 300,
    batch_id: str | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    tmpl = get_template(template_id)
    if not tmpl:
        raise ValueError("テンプレートが見つかりません")
    ocr_mode = normalize_ocr_mode(tmpl.get("ocr_mode"))
    if not pages_b64:
        raise ValueError("ページ画像が必要です")
    if len(tmpl["regions"]) == 0:
        raise ValueError("テンプレートに領域がありません")

    doc_id = str(uuid.uuid4())
    now = _now_iso()
    db = connect()

    page_paths: list[Path] = []
    with _lock:
        db.execute(
            "INSERT INTO documents "
            "(id, template_id, title, status, batch_id, source_name, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_id,
                template_id,
                title,
                "processing",
                batch_id,
                source_name,
                created_by,
                now,
            ),
        )
        for i, b64 in enumerate(pages_b64):
            raw = ocr.decode_image_bytes(b64)
            path, stored_dpi = ocr.save_page_image(doc_id, i, raw)
            page_paths.append(path)
            db.execute(
                "INSERT INTO pages (id, document_id, page_index, image_path, dpi) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), doc_id, i, str(path), stored_dpi or dpi or 300),
            )
        db.commit()

    # 領域クロップ + OCR（ロック外で実行）
    for reg in tmpl["regions"]:
        page_index = int(reg["page_index"] or 0)
        if page_index >= len(page_paths):
            continue
        rid = str(uuid.uuid4())
        crop_path = DATA_DIR / "images" / f"{doc_id}_{rid}.png"
        ocr.crop_region(
            page_paths[page_index],
            x=float(reg["x"]),
            y=float(reg["y"]),
            w=float(reg["w"]),
            h=float(reg["h"]),
            out_path=crop_path,
        )
        reg_field_type = normalize_field_type(reg.get("field_type"))
        # 選択種別・トラップは Vision を呼ばない（OCR は参考のみ／コスト節約）
        skip_vision = reg_field_type in ("choice", "choice_multi") or bool(
            reg.get("is_trap")
        )
        ocr_res = ocr.run_ocr_ex(
            crop_path,
            field_type=reg_field_type,
            is_handwriting=bool(reg.get("is_handwriting", True)),
            ocr_mode=ocr_mode,
            skip_vision=skip_vision,
        )
        with _lock:
            db.execute(
                "INSERT INTO region_instances "
                "(id, document_id, region_template_id, name, page_index, crop_path, "
                "ocr_text, ocr_confidence, ocr_vision_text, ocr_vision_confidence, "
                "field_type, is_trap, trap_answer, status, "
                "group_id, group_name, line_index, part_index, choice_options) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?)",
                (
                    rid,
                    doc_id,
                    reg["id"],
                    reg["name"],
                    page_index,
                    str(crop_path),
                    ocr_res["text"],
                    ocr_res["confidence"],
                    ocr_res.get("vision_text") or None,
                    ocr_res.get("vision_confidence") or 0,
                    reg_field_type,
                    1 if reg.get("is_trap") else 0,
                    reg.get("trap_answer"),
                    reg.get("group_id"),
                    (str(reg.get("group_name")).strip() if reg.get("group_name") else None),
                    int(reg.get("line_index") or 0),
                    int(reg.get("part_index") or 0),
                    _dump_choice_options(reg.get("choice_options")),
                ),
            )
            db.commit()

    with _lock:
        db.execute(
            "UPDATE documents SET status = ? WHERE id = ?", ("ready", doc_id)
        )
        db.commit()
    return get_document(doc_id)  # type: ignore[return-value]


def dispatch_document(doc_id: str, *, assignees: int | None = None) -> dict[str, Any]:
    doc = get_document(doc_id)
    if not doc:
        raise ValueError("書類が見つかりません")
    n = assignees if assignees is not None else DEFAULT_ASSIGNEES
    n = max(1, int(n))
    db = connect()
    now = _now_iso()
    created = 0
    with _lock:
        # 既存タスクがあれば再作成しない
        existing = db.execute(
            "SELECT COUNT(*) AS c FROM check_tasks t "
            "JOIN region_instances r ON r.id = t.region_instance_id "
            "WHERE r.document_id = ?",
            (doc_id,),
        ).fetchone()["c"]
        if existing:
            raise ValueError("すでに配信済みです")

        regions = db.execute(
            "SELECT id FROM region_instances WHERE document_id = ? AND is_trap = 0",
            (doc_id,),
        ).fetchall()
        traps = db.execute(
            "SELECT id FROM region_instances WHERE document_id = ? AND is_trap = 1",
            (doc_id,),
        ).fetchall()

        # ティア割当: n=1 は internal のみ。n>=2 は internal×1 + external×(n-1)
        if n == 1:
            tiers = ["internal"]
        else:
            tiers = ["internal"] + ["external"] * (n - 1)

        for r in regions:
            for tier in tiers:
                db.execute(
                    "INSERT INTO check_tasks "
                    "(id, region_instance_id, token, tier, status, created_at) "
                    "VALUES (?, ?, ?, ?, 'pending', ?)",
                    (str(uuid.uuid4()), r["id"], secrets.token_urlsafe(16), tier, now),
                )
                created += 1
            db.execute(
                "UPDATE region_instances SET status = 'checking' WHERE id = ?",
                (r["id"],),
            )

        # トラップは external（ソロ時は internal）へ 1 件
        trap_tier = "external" if n >= 2 else "internal"
        for t in traps:
            db.execute(
                "INSERT INTO check_tasks "
                "(id, region_instance_id, token, tier, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (str(uuid.uuid4()), t["id"], secrets.token_urlsafe(16), trap_tier, now),
            )
            created += 1
            db.execute(
                "UPDATE region_instances SET status = 'checking' WHERE id = ?",
                (t["id"],),
            )

        db.execute("UPDATE documents SET status = ? WHERE id = ?", ("dispatched", doc_id))
        db.commit()
    result = get_document(doc_id)
    assert result is not None
    result["tasks_created"] = created
    result["assignees"] = n
    return result


# ----- queue / answers -----


def _guest_label(checker_key: str | None) -> str | None:
    key = (checker_key or "").strip()
    if not key:
        return None
    return f"guest:{key}"


def _region_answered_by_clause(
    *, user_id: str | None = None, checker_key: str | None = None
) -> tuple[str, list[Any]]:
    """同一人物が既に回答した領域を除外する SQL 断片。"""
    clauses: list[str] = []
    params: list[Any] = []
    if user_id:
        clauses.append("a.checker_user_id = ?")
        params.append(user_id)
    label = _guest_label(checker_key)
    if label:
        clauses.append("a.checker_label = ?")
        params.append(label)
    if not clauses:
        return "", []
    return (
        " AND t.region_instance_id NOT IN ("
        "SELECT a.region_instance_id FROM check_answers a WHERE "
        + " OR ".join(clauses)
        + ")",
        params,
    )


def claim_internal_task(user_id: str) -> dict[str, Any] | None:
    db = connect()
    now = _now_iso()
    excl_sql, excl_params = _region_answered_by_clause(user_id=user_id)
    with _lock:
        row = db.execute(
            "SELECT t.id, t.token, t.region_instance_id, t.tier "
            "FROM check_tasks t "
            "WHERE t.status = 'pending' AND t.tier = 'internal' "
            f"{excl_sql} "
            "ORDER BY t.created_at LIMIT 1",
            excl_params,
        ).fetchone()
        if not row:
            # フォールバック: external 未消化も庁内が拾える（未回答領域のみ）
            row = db.execute(
                "SELECT t.id, t.token, t.region_instance_id, t.tier "
                "FROM check_tasks t "
                "WHERE t.status = 'pending' "
                f"{excl_sql} "
                "ORDER BY t.created_at LIMIT 1",
                excl_params,
            ).fetchone()
        if not row:
            return None
        db.execute(
            "UPDATE check_tasks SET status = 'locked', assignee_user_id = ?, locked_at = ? "
            "WHERE id = ?",
            (user_id, now, row["id"]),
        )
        db.commit()
    return get_task_payload(row["token"], include_internal=True)


def claim_public_task(*, checker_key: str | None = None) -> dict[str, Any] | None:
    db = connect()
    now = _now_iso()
    excl_sql, excl_params = _region_answered_by_clause(checker_key=checker_key)
    with _lock:
        row = db.execute(
            "SELECT t.id, t.token FROM check_tasks t "
            "WHERE t.status = 'pending' AND t.tier = 'external' "
            f"{excl_sql} "
            "ORDER BY RANDOM() LIMIT 1",
            excl_params,
        ).fetchone()
        if not row:
            return None
        db.execute(
            "UPDATE check_tasks SET status = 'locked', locked_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        db.commit()
        token = row["token"]
    return get_task_payload(token, include_internal=False)


def _field_key_expr() -> str:
    """項目キー（複数行・横分割で共通の出力項目名 or 領域名）。"""
    return "COALESCE(NULLIF(r.group_name, ''), r.name)"


def suggestions_for_region(
    region_instance_id: str, *, limit: int = 12
) -> list[str]:
    """同一テンプレ・同一項目キーの過去補正値を頻度順に返す。

    - 採用済み（region_instances.adopted_text）と手入力（check_answers.answer_text）を集計
    - トラップ・判読不能・空は除外、自領域は除外
    - 正規化キーで重複をまとめ、頻度降順・同数は新しい順
    """
    db = connect()
    base = db.execute(
        "SELECT r.field_type AS field_type, "
        f"{_field_key_expr()} AS field_key, d.template_id AS template_id "
        "FROM region_instances r "
        "JOIN documents d ON d.id = r.document_id "
        "WHERE r.id = ?",
        (region_instance_id,),
    ).fetchone()
    if not base:
        return []
    field_type = normalize_field_type(base["field_type"])
    field_key = base["field_key"]
    template_id = base["template_id"]
    if not field_key:
        return []

    rows: list[tuple[str, str]] = []
    for r in db.execute(
        "SELECT r.adopted_text AS val, MAX(r.rowid) AS ord "
        "FROM region_instances r "
        "JOIN documents d ON d.id = r.document_id "
        f"WHERE d.template_id = ? AND {_field_key_expr()} = ? "
        "AND r.id != ? AND r.is_trap = 0 AND r.status = 'adopted' "
        "AND r.adopted_text IS NOT NULL AND TRIM(r.adopted_text) != '' "
        "GROUP BY r.adopted_text",
        (template_id, field_key, region_instance_id),
    ).fetchall():
        rows.append((str(r["val"]), str(r["ord"] or "")))
    for r in db.execute(
        "SELECT a.answer_text AS val, MAX(a.created_at) AS ord "
        "FROM check_answers a "
        "JOIN region_instances r ON r.id = a.region_instance_id "
        "JOIN documents d ON d.id = r.document_id "
        f"WHERE d.template_id = ? AND {_field_key_expr()} = ? "
        "AND a.region_instance_id != ? AND r.is_trap = 0 "
        "AND a.is_unreadable = 0 AND TRIM(a.answer_text) != '' "
        "GROUP BY a.answer_text",
        (template_id, field_key, region_instance_id),
    ).fetchall():
        rows.append((str(r["val"]), str(r["ord"] or "")))

    # 正規化キーで集計（表示は最頻の生値）
    agg: dict[str, dict[str, Any]] = {}
    for raw, ordv in rows:
        val = raw.strip()
        if not val:
            continue
        norm = consensus.normalize_text(val, field_type=field_type)
        if not norm:
            continue
        entry = agg.setdefault(
            norm, {"count": 0, "last": "", "variants": {}}
        )
        entry["count"] += 1
        if ordv > entry["last"]:
            entry["last"] = ordv
        entry["variants"][val] = entry["variants"].get(val, 0) + 1

    ordered = sorted(
        agg.values(), key=lambda e: (e["count"], e["last"]), reverse=True
    )
    out: list[str] = []
    for e in ordered:
        best = max(e["variants"].items(), key=lambda kv: kv[1])[0]
        out.append(best)
        if len(out) >= limit:
            break
    return out


def get_task_payload(token: str, *, include_internal: bool) -> dict[str, Any] | None:
    import base64

    db = connect()
    row = db.execute(
        "SELECT t.id AS task_id, t.token, t.tier, t.status, t.assignee_user_id, "
        "r.id AS region_id, r.name, r.ocr_text, r.ocr_confidence, "
        "r.ocr_vision_text, r.ocr_vision_confidence, r.field_type, "
        "r.crop_path, r.is_trap, r.document_id, r.status AS region_status, "
        "r.group_name, r.line_index, r.part_index, r.choice_options "
        "FROM check_tasks t "
        "JOIN region_instances r ON r.id = t.region_instance_id "
        "WHERE t.token = ?",
        (token,),
    ).fetchone()
    if not row:
        return None
    if row["status"] == "done":
        return {
            "task_id": row["task_id"],
            "token": token,
            "status": "done",
            "message": "このタスクは回答済みです",
        }
    field_type = normalize_field_type(row["field_type"])
    ocr_text = row["ocr_text"] or ""
    suggestions = [
        s
        for s in suggestions_for_region(row["region_id"])
        if consensus.normalize_text(s, field_type=field_type)
        != consensus.normalize_text(ocr_text, field_type=field_type)
    ]
    payload = {
        "task_id": row["task_id"],
        "token": token,
        "tier": row["tier"],
        "status": row["status"],
        "name": row["name"],
        "ocr_text": ocr_text,
        "ocr_confidence": row["ocr_confidence"] or 0,
        "ocr_vision_text": row["ocr_vision_text"] or "",
        "ocr_vision_confidence": row["ocr_vision_confidence"] or 0,
        "field_type": field_type,
        "choice_options": _load_choice_options(row["choice_options"]),
        "group_name": row["group_name"] or None,
        "line_index": int(row["line_index"] or 0),
        "part_index": int(row["part_index"] or 0),
        "suggestions": suggestions,
        "image_url": f"/public/api/image/{token}",
        "region_id": row["region_id"],
    }
    if include_internal:
        payload["document_id"] = row["document_id"]
        payload["is_trap"] = bool(row["is_trap"])
        # 庁内 UI は backend の JSON プロキシ経由のため、画像を data URL で同梱する
        path = Path(row["crop_path"])
        if path.is_file():
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            payload["image_data_url"] = f"data:image/png;base64,{b64}"
    return payload


def crop_bytes_for_token(token: str) -> bytes | None:
    db = connect()
    row = db.execute(
        "SELECT r.crop_path FROM check_tasks t "
        "JOIN region_instances r ON r.id = t.region_instance_id "
        "WHERE t.token = ?",
        (token,),
    ).fetchone()
    if not row:
        return None
    path = Path(row["crop_path"])
    if not path.is_file():
        return None
    return path.read_bytes()


def crop_bytes_for_region(region_id: str) -> bytes | None:
    db = connect()
    row = db.execute(
        "SELECT crop_path FROM region_instances WHERE id = ?", (region_id,)
    ).fetchone()
    if not row:
        return None
    path = Path(row["crop_path"])
    if not path.is_file():
        return None
    return path.read_bytes()


def submit_answer(
    token: str,
    *,
    answer_text: str,
    tier: str,
    checker_user_id: str | None,
    checker_label: str | None = None,
    checker_key: str | None = None,
    is_unreadable: bool = False,
    is_blank: bool = False,
) -> dict[str, Any]:
    db = connect()
    now = _now_iso()
    label = checker_label
    if not checker_user_id:
        label = _guest_label(checker_key) or (checker_label or "guest")
    with _lock:
        task = db.execute(
            "SELECT t.id, t.status, t.region_instance_id, t.tier, "
            "r.field_type, r.is_trap, r.trap_answer, r.document_id "
            "FROM check_tasks t "
            "JOIN region_instances r ON r.id = t.region_instance_id "
            "WHERE t.token = ?",
            (token,),
        ).fetchone()
        if not task:
            raise ValueError("タスクが見つかりません")
        if task["status"] in ("done", "cancelled"):
            raise ValueError("すでに回答済み、または取り消されたタスクです")

        # 同一人物による同一領域の二重回答を禁止
        if checker_user_id:
            dup = db.execute(
                "SELECT id FROM check_answers "
                "WHERE region_instance_id = ? AND checker_user_id = ? LIMIT 1",
                (task["region_instance_id"], checker_user_id),
            ).fetchone()
            if dup:
                raise ValueError(
                    "この項目はすでにチェック済みです（同一アカウントでの重複回答はできません）"
                )
        if label and label.startswith("guest:"):
            dup = db.execute(
                "SELECT id FROM check_answers "
                "WHERE region_instance_id = ? AND checker_label = ? LIMIT 1",
                (task["region_instance_id"], label),
            ).fetchone()
            if dup:
                raise ValueError(
                    "この項目はすでにチェック済みです（同一端末での重複回答はできません）"
                )

        # 空欄（記入なし）は判読不能より優先し、確定した空文字として扱う
        if is_blank:
            is_unreadable = False
        text = "" if (is_unreadable or is_blank) else (answer_text or "").strip()
        if not is_unreadable and not is_blank and not text:
            raise ValueError("回答テキストが必要です")

        aid = str(uuid.uuid4())
        db.execute(
            "INSERT INTO check_answers "
            "(id, task_id, region_instance_id, answer_text, tier, checker_user_id, "
            "checker_label, is_unreadable, is_blank, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                aid,
                task["id"],
                task["region_instance_id"],
                text,
                task["tier"] if tier not in ("internal", "external") else tier,
                checker_user_id,
                label,
                1 if is_unreadable else 0,
                1 if is_blank else 0,
                now,
            ),
        )
        db.execute(
            "UPDATE check_tasks SET status = 'done', assignee_user_id = COALESCE(assignee_user_id, ?) "
            "WHERE id = ?",
            (checker_user_id, task["id"]),
        )

        # トラップ評価
        trap_ok: bool | None = None
        if task["is_trap"] and task["trap_answer"] is not None:
            norm = consensus.normalize_text(text)
            expected = consensus.normalize_text(task["trap_answer"])
            trap_ok = norm == expected and not is_unreadable and not is_blank
            if checker_user_id:
                _bump_score(
                    db,
                    checker_user_id,
                    points=1 if trap_ok else -1,
                    checks=1,
                    trap_correct=1 if trap_ok else 0,
                    trap_wrong=0 if trap_ok else 1,
                )
            db.execute(
                "UPDATE region_instances SET status = ?, adopted_text = ? WHERE id = ?",
                (
                    "adopted" if trap_ok else "rejected",
                    task["trap_answer"] if trap_ok else None,
                    task["region_instance_id"],
                ),
            )
            _cancel_open_tasks(db, task["region_instance_id"])
            db.commit()
            return {
                "ok": True,
                "trap": True,
                "trap_correct": trap_ok,
                "region_status": "adopted" if trap_ok else "rejected",
            }

        assignee_count = db.execute(
            "SELECT COUNT(*) AS c FROM check_tasks WHERE region_instance_id = ?",
            (task["region_instance_id"],),
        ).fetchone()["c"]
        # cancelled を除いた当初割当数に近い値（done+pending+locked+cancelled）
        # cancelled 後でも元の件数を使うため、上は全タスク数で OK

        answers = _answers_for_region(db, task["region_instance_id"])
        result = consensus.evaluate_consensus(
            answers,
            field_type=task["field_type"] or "text",
            min_agree=MIN_AGREE,
            assignee_count=assignee_count,
        )
        region_status = result["status"]
        if region_status == "adopted":
            db.execute(
                "UPDATE region_instances SET status = 'adopted', adopted_text = ? WHERE id = ?",
                (result["adopted_text"], task["region_instance_id"]),
            )
            _cancel_open_tasks(db, task["region_instance_id"])
            adopted_norm = consensus.normalize_text(
                result["adopted_text"], field_type=task["field_type"] or "text"
            )
            for a in answers:
                if (
                    a.get("checker_user_id")
                    and consensus.normalize_text(
                        a.get("answer_text"), field_type=task["field_type"] or "text"
                    )
                    == adopted_norm
                ):
                    _bump_score(
                        db,
                        a["checker_user_id"],
                        points=1,
                        checks=1,
                        adopted=1,
                    )
            if checker_user_id:
                mine = consensus.normalize_text(
                    text, field_type=task["field_type"] or "text"
                )
                if mine != adopted_norm:
                    _bump_score(db, checker_user_id, points=0, checks=1)
        elif region_status == "needs_arbitration":
            db.execute(
                "UPDATE region_instances SET status = 'needs_arbitration' WHERE id = ?",
                (task["region_instance_id"],),
            )
            if checker_user_id:
                _bump_score(db, checker_user_id, points=0, checks=1)
        else:
            if checker_user_id:
                _bump_score(db, checker_user_id, points=0, checks=1)

        _refresh_document_status(db, task["document_id"])
        db.commit()

    return {
        "ok": True,
        "trap": False,
        "region_status": region_status,
        "consensus": result,
    }


def _cancel_open_tasks(db: sqlite3.Connection, region_id: str) -> None:
    db.execute(
        "UPDATE check_tasks SET status = 'cancelled' "
        "WHERE region_instance_id = ? AND status IN ('pending', 'locked')",
        (region_id,),
    )


def _answers_for_region(db: sqlite3.Connection, region_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT id AS answer_id, task_id, answer_text, tier, checker_user_id, "
        "checker_label, is_unreadable, is_blank "
        "FROM check_answers WHERE region_instance_id = ? AND is_unreadable = 0",
        (region_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        label = d.get("checker_label") or ""
        if label.startswith("guest:"):
            d["checker_key"] = label.split(":", 1)[1]
        out.append(d)
    return out


def _bump_score(
    db: sqlite3.Connection,
    user_id: str,
    *,
    points: int = 0,
    checks: int = 0,
    adopted: int = 0,
    trap_correct: int = 0,
    trap_wrong: int = 0,
    display_name: str | None = None,
) -> None:
    now = _now_iso()
    row = db.execute(
        "SELECT user_id FROM user_scores WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not row:
        db.execute(
            "INSERT INTO user_scores "
            "(user_id, display_name, points, checks_count, adopted_count, "
            "trap_correct, trap_wrong, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                display_name or user_id,
                max(0, points),
                checks,
                adopted,
                trap_correct,
                trap_wrong,
                now,
            ),
        )
        return
    db.execute(
        "UPDATE user_scores SET "
        "points = MAX(0, points + ?), "
        "checks_count = checks_count + ?, "
        "adopted_count = adopted_count + ?, "
        "trap_correct = trap_correct + ?, "
        "trap_wrong = trap_wrong + ?, "
        "updated_at = ? "
        "WHERE user_id = ?",
        (points, checks, adopted, trap_correct, trap_wrong, now, user_id),
    )


def list_arbitration() -> list[dict[str, Any]]:
    db = connect()
    rows = db.execute(
        "SELECT r.id, r.document_id, r.name, r.ocr_text, r.field_type, r.crop_path, "
        "d.title AS document_title "
        "FROM region_instances r "
        "JOIN documents d ON d.id = r.document_id "
        "WHERE r.status = 'needs_arbitration' AND r.is_trap = 0 "
        "ORDER BY r.name"
    ).fetchall()
    out = []
    for r in rows:
        answers = _answers_for_region(db, r["id"])
        out.append({**dict(r), "answers": answers})
    return out


def arbitrate(
    region_id: str, *, adopted_text: str, arbiter_user_id: str
) -> dict[str, Any]:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT id, document_id, status FROM region_instances WHERE id = ?",
            (region_id,),
        ).fetchone()
        if not row:
            raise ValueError("領域が見つかりません")
        db.execute(
            "UPDATE region_instances SET status = 'adopted', adopted_text = ? WHERE id = ?",
            (adopted_text.strip(), region_id),
        )
        _bump_score(db, arbiter_user_id, points=1, checks=0, adopted=1)
        _refresh_document_status(db, row["document_id"])
        db.commit()
    return {"ok": True, "region_id": region_id, "adopted_text": adopted_text.strip()}


def _refresh_document_status(db: sqlite3.Connection, doc_id: str) -> None:
    rows = db.execute(
        "SELECT status FROM region_instances WHERE document_id = ? AND is_trap = 0",
        (doc_id,),
    ).fetchall()
    if not rows:
        return
    statuses = {r["status"] for r in rows}
    if statuses <= {"adopted", "rejected"}:
        new_status = "completed"
    elif "needs_arbitration" in statuses:
        new_status = "needs_arbitration"
    else:
        new_status = "dispatched"
    db.execute("UPDATE documents SET status = ? WHERE id = ?", (new_status, doc_id))


def export_document(doc_id: str) -> dict[str, Any]:
    doc = get_document(doc_id)
    if not doc:
        raise ValueError("書類が見つかりません")
    fields = consensus.merge_export_fields(doc.get("regions") or [])
    return {
        "document_id": doc_id,
        "title": doc["title"],
        "template_name": doc.get("template_name"),
        "status": doc["status"],
        "fields": fields,
        "exported_at": _now_iso(),
    }


def get_score(user_id: str) -> dict[str, Any]:
    db = connect()
    row = db.execute(
        "SELECT user_id, display_name, points, checks_count, adopted_count, "
        "trap_correct, trap_wrong, updated_at FROM user_scores WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return {
            "user_id": user_id,
            "points": 0,
            "checks_count": 0,
            "adopted_count": 0,
            "trap_correct": 0,
            "trap_wrong": 0,
        }
    return dict(row)


def leaderboard(limit: int = 20) -> list[dict[str, Any]]:
    db = connect()
    rows = db.execute(
        "SELECT user_id, display_name, points, checks_count, adopted_count "
        "FROM user_scores ORDER BY points DESC, checks_count DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict[str, Any]:
    db = connect()
    docs = db.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
    pending_tasks = db.execute(
        "SELECT COUNT(*) AS c FROM check_tasks WHERE status IN ('pending', 'locked')"
    ).fetchone()["c"]
    arbitration = db.execute(
        "SELECT COUNT(*) AS c FROM region_instances WHERE status = 'needs_arbitration'"
    ).fetchone()["c"]
    return {
        "documents": docs,
        "pending_tasks": pending_tasks,
        "arbitration_count": arbitration,
        "ocr_engine": ocr.ENGINE,
        "public_endpoint": PUBLIC_ENDPOINT,
        "assignees_default": DEFAULT_ASSIGNEES,
        "batch_assignees_default": DEFAULT_ASSIGNEES,
        "single_assignees_default": SINGLE_ASSIGNEES,
        "demo_assignees": DEMO_ASSIGNEES,
        "ocr_normalize": ocr.OCR_NORMALIZE,
        "ocr_target_dpi": ocr.OCR_TARGET_DPI,
        "ocr_long_edge": ocr.OCR_LONG_EDGE,
        "min_agree": MIN_AGREE,
        "trap_ratio": TRAP_RATIO,
        "demo_sample_available": DEMO_FORM_PATH.is_file(),
        **ocr.ocr_status(),
    }


def seed_demo_document(
    *, created_by: str, dispatch: bool = True, assignees: int | None = None
) -> dict[str, Any]:
    """同梱のデモ帳票画像を投入し、任意で配信まで行う。

    既定の割当は 1 人（ソロ検証向け）。本番想定の複数人割当は assignees を指定。
    """
    if not DEMO_FORM_PATH.is_file():
        raise ValueError(
            f"デモ画像がありません: {DEMO_FORM_PATH}。"
            "イメージを再ビルドしてください（samples/demo-form.png）。"
        )
    if not get_template(DEMO_TEMPLATE_ID):
        _ensure_demo_template()
    raw = DEMO_FORM_PATH.read_bytes()
    b64 = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    title = f"デモ申請書 {_now_iso()[:16].replace('T', ' ')}"
    doc = create_document_from_images(
        template_id=DEMO_TEMPLATE_ID,
        title=title,
        created_by=created_by,
        pages_b64=[b64],
        dpi=300,
    )
    if dispatch:
        n = DEMO_ASSIGNEES if assignees is None else assignees
        doc = dispatch_document(doc["id"], assignees=n)
    # テスト用の期待値ヒント（原本には出さない。庁内詳細でのみ参考）
    doc["demo_expected"] = {
        "氏名（姓）": "山田",
        "氏名（名）": "太郎",
        "生年月日": "平成2年4月1日",
        "電話番号": "090-1234-5678",
        "住所1": "○○県△△市1-2-3",
        "申請日": "2026-08-11",
        "【トラップ】確認コード": "OPEN-OK",
    }
    doc["note"] = (
        f"デモは割当 {doc.get('assignees', DEMO_ASSIGNEES)} 人です。"
        "同じ人が同一項目を複数回チェックする必要はありません。"
    )
    return doc


# ----- batches（連続スキャン投入・一括出力） -----


def list_batches(limit: int = 50) -> list[dict[str, Any]]:
    db = connect()
    rows = db.execute(
        "SELECT b.id, b.name, b.template_id, b.status, b.pages_per_document, "
        "b.auto_dispatch, b.assignees, b.dpi, b.total_images, b.total_documents, "
        "b.processed_documents, b.error_count, b.last_error, b.created_by, b.created_at, "
        "t.name AS template_name "
        "FROM batches b JOIN form_templates t ON t.id = b.template_id "
        "ORDER BY b.created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["auto_dispatch"] = bool(item.get("auto_dispatch"))
        item["progress"] = _batch_progress(item["id"])
        out.append(item)
    return out


def get_batch(batch_id: str) -> dict[str, Any] | None:
    db = connect()
    row = db.execute(
        "SELECT b.id, b.name, b.template_id, b.status, b.pages_per_document, "
        "b.auto_dispatch, b.assignees, b.dpi, b.total_images, b.total_documents, "
        "b.processed_documents, b.error_count, b.last_error, b.created_by, b.created_at, "
        "t.name AS template_name "
        "FROM batches b JOIN form_templates t ON t.id = b.template_id "
        "WHERE b.id = ?",
        (batch_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["auto_dispatch"] = bool(item.get("auto_dispatch"))
    item["progress"] = _batch_progress(batch_id)
    item["documents"] = list_documents(batch_id=batch_id)
    return item


def _batch_progress(batch_id: str) -> dict[str, Any]:
    db = connect()
    rows = db.execute(
        "SELECT status, COUNT(*) AS c FROM documents WHERE batch_id = ? GROUP BY status",
        (batch_id,),
    ).fetchall()
    by_status = {r["status"]: r["c"] for r in rows}
    total = sum(by_status.values())
    completed = by_status.get("completed", 0)
    arbitration = by_status.get("needs_arbitration", 0)
    dispatched = by_status.get("dispatched", 0)
    ready = by_status.get("ready", 0)
    processing = by_status.get("processing", 0) + by_status.get("error", 0)
    return {
        "total": total,
        "completed": completed,
        "needs_arbitration": arbitration,
        "dispatched": dispatched,
        "ready": ready,
        "processing": processing,
        "by_status": by_status,
        "completion_ratio": (completed / total) if total else 0.0,
    }


def create_batch(
    *,
    name: str,
    template_id: str,
    created_by: str,
    images: list[dict[str, Any]],
    pages_per_document: int = 1,
    auto_dispatch: bool = True,
    assignees: int | None = None,
    dpi: int = 300,
) -> dict[str, Any]:
    """連続スキャン画像をバッチ投入する（バックグラウンド処理）。

    images: [{ "data": "<base64 or data-url>", "name": "scan_001.png" }, ...]
    pages_per_document: 1 なら画像1枚＝申請1件。複数ページ帳票なら 2 など。
    """
    tmpl = get_template(template_id)
    if not tmpl:
        raise ValueError("テンプレートが見つかりません")
    if not images:
        raise ValueError("画像が必要です")
    ppd = max(1, int(pages_per_document))
    if len(images) % ppd != 0:
        raise ValueError(
            f"画像枚数 ({len(images)}) が pages_per_document ({ppd}) で割り切れません"
        )

    batch_id = str(uuid.uuid4())
    now = _now_iso()
    total_docs = len(images) // ppd
    # バッチは本番想定の既定割当（環境変数 DOCCHECK_ASSIGNEES、既定 3）
    n_assign = DEFAULT_ASSIGNEES if assignees is None else max(1, int(assignees))
    stored_dpi = ocr.OCR_TARGET_DPI
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO batches "
            "(id, name, template_id, status, pages_per_document, auto_dispatch, "
            "assignees, dpi, total_images, total_documents, processed_documents, "
            "error_count, created_by, created_at) "
            "VALUES (?, ?, ?, 'processing', ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)",
            (
                batch_id,
                name.strip() or f"バッチ {now[:16]}",
                template_id,
                ppd,
                1 if auto_dispatch else 0,
                n_assign,
                stored_dpi,
                len(images),
                total_docs,
                created_by,
                now,
            ),
        )
        db.commit()

    # 画像を一時保存（メモリ肥大を避けるためファイルへ）＋ OCR 向け正規化
    staging = DATA_DIR / "batch_staging" / batch_id
    staging.mkdir(parents=True, exist_ok=True)
    staged: list[dict[str, str]] = []
    for i, img in enumerate(images):
        raw = ocr.decode_image_bytes(img.get("data") or "")
        fname = (img.get("name") or f"page_{i + 1:04d}.png").replace("/", "_")
        path = staging / f"{i:05d}_{fname}"
        try:
            normalized, stored_dpi = ocr.normalize_for_ocr(raw)
            path.write_bytes(normalized)
        except Exception:  # noqa: BLE001
            path.write_bytes(raw)
        staged.append({"path": str(path), "name": fname})

    meta_path = staging / "manifest.json"
    meta_path.write_text(
        json.dumps(
            {
                "batch_id": batch_id,
                "template_id": template_id,
                "pages_per_document": ppd,
                "auto_dispatch": auto_dispatch,
                "assignees": n_assign,
                "dpi": stored_dpi,
                "created_by": created_by,
                "images": staged,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    t = threading.Thread(
        target=_process_batch_worker,
        args=(batch_id,),
        name=f"doccheck-batch-{batch_id[:8]}",
        daemon=True,
    )
    t.start()
    result = get_batch(batch_id)
    assert result is not None
    return result


def _process_batch_worker(batch_id: str) -> None:
    staging = DATA_DIR / "batch_staging" / batch_id
    meta_path = staging / "manifest.json"
    db = connect()
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        with _lock:
            db.execute(
                "UPDATE batches SET status = 'error', last_error = ? WHERE id = ?",
                (f"manifest read failed: {e}", batch_id),
            )
            db.commit()
        return

    images: list[dict[str, str]] = meta["images"]
    ppd = int(meta["pages_per_document"])
    template_id = meta["template_id"]
    created_by = meta["created_by"]
    auto_dispatch = bool(meta["auto_dispatch"])
    assignees = int(meta["assignees"])
    dpi = int(meta.get("dpi") or 300)

    for doc_i in range(0, len(images), ppd):
        chunk = images[doc_i : doc_i + ppd]
        source = chunk[0]["name"]
        title = f"{Path(source).stem}"
        if ppd > 1:
            title = f"{title}_p{doc_i // ppd + 1}"
        try:
            pages_b64: list[str] = []
            for c in chunk:
                raw = Path(c["path"]).read_bytes()
                pages_b64.append(
                    "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
                )
            doc = create_document_from_images(
                template_id=template_id,
                title=title,
                created_by=created_by,
                pages_b64=pages_b64,
                dpi=dpi,
                batch_id=batch_id,
                source_name=source,
            )
            if auto_dispatch:
                dispatch_document(doc["id"], assignees=assignees)
            with _lock:
                db.execute(
                    "UPDATE batches SET processed_documents = processed_documents + 1 "
                    "WHERE id = ?",
                    (batch_id,),
                )
                db.commit()
        except Exception as e:  # noqa: BLE001
            print(f"[doccheck-batch] doc failed in {batch_id}: {e}")
            with _lock:
                db.execute(
                    "UPDATE batches SET error_count = error_count + 1, last_error = ? "
                    "WHERE id = ?",
                    (str(e)[:500], batch_id),
                )
                db.commit()

    with _lock:
        row = db.execute(
            "SELECT error_count, total_documents, processed_documents FROM batches "
            "WHERE id = ?",
            (batch_id,),
        ).fetchone()
        status = "ready"
        if row and row["error_count"] and row["processed_documents"] == 0:
            status = "error"
        elif row and row["error_count"]:
            status = "partial"
        db.execute(
            "UPDATE batches SET status = ? WHERE id = ?",
            (status, batch_id),
        )
        db.commit()

    # ステージング削除（失敗しても無視）
    try:
        for p in staging.glob("*"):
            p.unlink(missing_ok=True)
        staging.rmdir()
    except Exception:  # noqa: BLE001
        pass


def dispatch_batch(batch_id: str, *, assignees: int | None = None) -> dict[str, Any]:
    """バッチ内の ready 書類を一括配信。"""
    docs = list_documents(batch_id=batch_id)
    n = 0
    for d in docs:
        if d["status"] != "ready":
            continue
        try:
            dispatch_document(d["id"], assignees=assignees)
            n += 1
        except ValueError:
            continue
    batch = get_batch(batch_id)
    assert batch is not None
    batch["dispatched_now"] = n
    return batch


def export_batch(
    batch_id: str,
    *,
    format: str = "csv",
    status_filter: str = "completed",
) -> dict[str, Any]:
    """バッチの確定データを CSV / JSONL で返す。

    status_filter:
      - completed: 完了のみ（既定）
      - completed,needs_arbitration: 完了＋裁定待ち（value は確定分のみ）
      - all: 全件
    """
    batch = get_batch(batch_id)
    if not batch:
        raise ValueError("バッチが見つかりません")
    tmpl = get_template(batch["template_id"])
    field_names = consensus.export_column_names((tmpl or {}).get("regions") or [])
    allowed = {s.strip() for s in status_filter.split(",") if s.strip()}
    include_all = "all" in allowed

    rows_out: list[dict[str, Any]] = []
    for d in batch.get("documents") or []:
        if not include_all and d["status"] not in allowed:
            continue
        exported = export_document(d["id"])
        values = {f["name"]: f.get("value") for f in exported["fields"]}
        field_statuses = {f["name"]: f.get("status") for f in exported["fields"]}
        row = {
            "document_id": d["id"],
            "title": d["title"],
            "source_name": d.get("source_name") or "",
            "status": d["status"],
            "template_name": batch.get("template_name"),
            "batch_id": batch_id,
        }
        for name in field_names:
            row[name] = values.get(name)
            row[f"{name}__status"] = field_statuses.get(name)
        rows_out.append(row)

    fmt = (format or "csv").lower()
    stamp = _now_iso().replace(":", "").replace("-", "")[:15]
    if fmt == "jsonl":
        content = "\n".join(
            json.dumps(r, ensure_ascii=False) for r in rows_out
        ) + ("\n" if rows_out else "")
        filename = f"doccheck_batch_{batch_id[:8]}_{stamp}.jsonl"
        media = "application/x-ndjson; charset=utf-8"
    elif fmt == "json":
        content = json.dumps(
            {
                "batch_id": batch_id,
                "batch_name": batch["name"],
                "exported_at": _now_iso(),
                "status_filter": status_filter,
                "count": len(rows_out),
                "rows": rows_out,
            },
            ensure_ascii=False,
            indent=2,
        )
        filename = f"doccheck_batch_{batch_id[:8]}_{stamp}.json"
        media = "application/json; charset=utf-8"
    else:
        # CSV
        base_cols = [
            "document_id",
            "title",
            "source_name",
            "status",
            "template_name",
            "batch_id",
        ]
        cols = base_cols + field_names
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for r in rows_out:
            writer.writerow({c: r.get(c) if r.get(c) is not None else "" for c in cols})
        # Excel（日本語環境）は BOM 無し UTF-8 を Shift_JIS と誤認して見出しが化ける
        content = "\ufeff" + buf.getvalue()
        filename = f"doccheck_batch_{batch_id[:8]}_{stamp}.csv"
        media = "text/csv; charset=utf-8"

    return {
        "filename": filename,
        "format": fmt,
        "media_type": media,
        "content": content,
        "count": len(rows_out),
        "batch_id": batch_id,
        "status_filter": status_filter,
        "progress": batch["progress"],
        "exported_at": _now_iso(),
    }
