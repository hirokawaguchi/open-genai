"""補正候補（suggestions_for_region）と種別正規化の統合テスト。

一時ディレクトリに SQLite を作り、同一テンプレ・同一項目キーの
過去採用値・手入力値が候補として集計されることを確認する。
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="doccheck-test-")
os.environ["DOCCHECK_DB_PATH"] = str(Path(_TMP) / "test.db")
os.environ["DOCCHECK_DATA_DIR"] = _TMP
os.environ.setdefault("DOCCHECK_OCR_ENGINE", "none")

from app import store  # noqa: E402


def _insert_instance(
    db,
    *,
    document_id: str,
    name: str,
    field_type: str = "text_single",
    group_name: str | None = None,
    status: str = "adopted",
    adopted_text: str | None = None,
) -> str:
    rid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO region_instances "
        "(id, document_id, region_template_id, name, page_index, crop_path, "
        "ocr_text, ocr_confidence, field_type, is_trap, trap_answer, status, "
        "group_id, group_name, line_index, part_index, choice_options) "
        "VALUES (?, ?, NULL, ?, 0, ?, '', 0, ?, 0, NULL, ?, NULL, ?, 0, 0, NULL)",
        (rid, document_id, name, f"{rid}.png", field_type, status, group_name),
    )
    if adopted_text is not None:
        db.execute(
            "UPDATE region_instances SET adopted_text = ? WHERE id = ?",
            (adopted_text, rid),
        )
    return rid


def _insert_answer(db, *, region_instance_id: str, text: str) -> None:
    task_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO check_tasks "
        "(id, region_instance_id, token, tier, status, created_at) "
        "VALUES (?, ?, ?, 'external', 'done', ?)",
        (task_id, region_instance_id, str(uuid.uuid4()), store._now_iso()),
    )
    db.execute(
        "INSERT INTO check_answers "
        "(id, task_id, region_instance_id, answer_text, tier, checker_user_id, "
        "checker_label, is_unreadable, created_at) "
        "VALUES (?, ?, ?, ?, 'external', NULL, ?, 0, ?)",
        (
            str(uuid.uuid4()),
            task_id,
            region_instance_id,
            text,
            f"guest:{uuid.uuid4()}",
            store._now_iso(),
        ),
    )


def _seed():
    store.init_db()
    db = store.connect()
    tid = "tmpl-suggest"
    db.execute(
        "INSERT INTO form_templates (id, name, description, created_by, created_at) "
        "VALUES (?, ?, '', 'system', ?)",
        (tid, "候補テスト", store._now_iso()),
    )
    docs = []
    for i in range(3):
        did = str(uuid.uuid4())
        db.execute(
            "INSERT INTO documents (id, template_id, title, status, created_by, created_at) "
            "VALUES (?, ?, ?, 'ready', 'system', ?)",
            (did, tid, f"doc{i}", store._now_iso()),
        )
        docs.append(did)
    db.commit()
    return db, docs


def test_suggestions_same_field_frequency() -> None:
    db, docs = _seed()
    # doc0/doc1: 採用済み「みずほ銀行」、doc2: 別値
    _insert_instance(db, document_id=docs[0], name="銀行名", adopted_text="みずほ銀行")
    _insert_instance(db, document_id=docs[1], name="銀行名", adopted_text="みずほ銀行")
    target = _insert_instance(
        db, document_id=docs[2], name="銀行名", status="ready", adopted_text=None
    )
    # 別項目は候補に混ざらない
    _insert_instance(db, document_id=docs[0], name="氏名", adopted_text="山田太郎")
    db.commit()

    out = store.suggestions_for_region(target)
    assert "みずほ銀行" in out
    assert "山田太郎" not in out
    # 自領域は除外
    assert out[0] == "みずほ銀行"


def test_suggestions_include_handinput_answers() -> None:
    db, docs = _seed2()
    src = _insert_instance(
        db, document_id=docs[0], name="支店名", status="ready", adopted_text=None
    )
    _insert_answer(db, region_instance_id=src, text="本店")
    target = _insert_instance(
        db, document_id=docs[1], name="支店名", status="ready", adopted_text=None
    )
    db.commit()
    out = store.suggestions_for_region(target)
    assert "本店" in out


def _seed2():
    db = store.connect()
    tid = "tmpl-suggest2"
    db.execute(
        "INSERT INTO form_templates (id, name, description, created_by, created_at) "
        "VALUES (?, ?, '', 'system', ?)",
        (tid, "候補テスト2", store._now_iso()),
    )
    docs = []
    for i in range(2):
        did = str(uuid.uuid4())
        db.execute(
            "INSERT INTO documents (id, template_id, title, status, created_by, created_at) "
            "VALUES (?, ?, ?, 'ready', 'system', ?)",
            (did, tid, f"d{i}", store._now_iso()),
        )
        docs.append(did)
    db.commit()
    return db, docs


def test_field_type_normalization() -> None:
    assert store.normalize_field_type("text") == "text_single"
    assert store.normalize_field_type("") == "text_single"
    assert store.normalize_field_type("choice_multi") == "choice_multi"
    assert store.normalize_field_type("bogus") == "text_single"


if __name__ == "__main__":
    test_suggestions_same_field_frequency()
    test_suggestions_include_handinput_answers()
    test_field_type_normalization()
    print("ok")
