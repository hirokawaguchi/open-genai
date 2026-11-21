"""台帳の定義、行、入出力、項目提案。"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app import assist, ingest, io, material, store


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch):
    fd, path = tempfile.mkstemp(suffix="-ledger.db")
    os.close(fd)
    monkeypatch.setenv("LEDGER_DB_PATH", path)
    monkeypatch.setenv("LEDGER_FILES_DIR", tempfile.mkdtemp())
    store.reset_connection()
    store.connect()
    yield path
    store.reset_connection()
    os.remove(path)


def actor(
    teams: list[str] | None = None,
    *,
    tenant: str = "t1",
    admin: bool = False,
    user_id: str = "user-1",
) -> store.Actor:
    return store.Actor(
        user_id=user_id,
        team_ids=teams if teams is not None else ["team-a"],
        tenant_id=tenant,
        is_admin=admin,
        groups=["SystemAdminGroup"] if admin else [],
    )


def test_create_requires_tenant_and_team(db: str) -> None:
    saved, err = store.create_ledger(actor(tenant=""), {"name": "備品"})
    assert saved is None
    assert err
    saved, err = store.create_ledger(actor(teams=[]), {"name": "備品", "grants": []})
    assert saved is None
    ledger, err = store.create_ledger(
        actor(),
        {"name": "備品", "statuses": ["受付", "完了"], "grants": [{"team_id": "team-a", "role": "admin"}]},
    )
    assert err is None
    assert ledger is not None
    assert ledger["name"] == "備品"
    assert store.list_ledgers(actor())[0]["id"] == ledger["id"]
    assert store.list_ledgers(actor(teams=["other"], user_id="user-2")) == []


def test_field_type_is_fixed_and_rows_keep_history(db: str) -> None:
    ledger, _ = store.create_ledger(
        actor(),
        {
            "name": "備品",
            "statuses": ["受付", "完了"],
            "fields": [{"id": "name", "label": "氏名", "type": "text"}],
            "grants": [{"team_id": "team-a", "role": "admin"}],
        },
    )
    assert ledger is not None
    updated, err = store.update_ledger(
        actor(),
        ledger["id"],
        {"fields": [{"id": "name", "label": "名前", "type": "number"}]},
    )
    assert updated is None
    assert "型" in (err or "")
    row, err = store.upsert_row(
        actor(),
        ledger["id"],
        {"business_key": "k1", "fields": {"name": "山田"}, "extras": [{"label": "置き場", "value": "倉庫"}]},
    )
    assert err is None and row is not None
    again, err = store.upsert_row(
        actor(),
        ledger["id"],
        {"business_key": "k1", "fields": {"name": "佐藤"}, "status": "完了"},
    )
    assert err is None and again is not None
    assert again["fields"]["name"] == "佐藤"
    assert again["extras"][0]["label"] == "置き場"
    detail, _ = store.get_row(actor(), again["id"])
    assert detail is not None
    assert any(change["after"] == "佐藤" for rev in detail["revisions"] for change in rev["changes"])


def test_mask_viewer_and_csv_leaves_extras(db: str) -> None:
    ledger, _ = store.create_ledger(
        actor(),
        {
            "name": "備品",
            "statuses": ["受付"],
            "fields": [{"id": "secret", "label": "番号", "type": "text", "masked": True}],
            "grants": [
                {"team_id": "team-a", "role": "admin"},
                {"team_id": "team-b", "role": "viewer"},
            ],
        },
    )
    assert ledger is not None
    store.upsert_row(
        actor(),
        ledger["id"],
        {
            "business_key": "k1",
            "fields": {"secret": "1234"},
            "extras": [{"label": "メモ", "value": "残す"}],
        },
    )
    viewer = actor(teams=["team-b"], user_id="user-2")
    page, _ = store.list_rows(viewer, ledger["id"])
    assert page is not None
    assert page["rows"][0]["fields"]["secret"] == ""
    assert page["rows"][0]["extras"][0]["value"] == "残す"
    text = io.export_csv(io.export_document(ledger, page["rows"], role="viewer"))
    assert "1234" not in text
    rows, err = io.parse_csv_import("business_key,status,assignee,comment,番号\nk1,受付,山田,,9999\n", ledger)
    assert err is None and rows is not None
    assert "extras" not in rows[0]
    saved, err = store.upsert_row(actor(), ledger["id"], rows[0])
    assert err is None and saved is not None
    assert saved["extras"][0]["value"] == "残す"
    assert saved["fields"]["secret"] == "9999"


def test_json_unknown_field_becomes_extra(db: str) -> None:
    ledger, _ = store.create_ledger(
        actor(),
        {
            "name": "備品",
            "statuses": ["受付"],
            "fields": [{"id": "name", "label": "氏名", "type": "text"}],
            "grants": [{"team_id": "team-a", "role": "admin"}],
        },
    )
    assert ledger is not None
    payload = {
        "ledger": {"fields": [{"id": "other", "label": "置き場"}]},
        "rows": [{"business_key": "k1", "status": "受付", "fields": {"other": "倉庫", "name": "山田"}}],
    }
    rows, err = io.parse_json_import(json.dumps(payload), ledger)
    assert err is None and rows is not None
    assert rows[0]["fields"] == {"name": "山田"}
    assert rows[0]["extras"][0]["label"] == "置き場"
    bad, err = io.parse_csv_import("business_key,謎\nk1,x\n", ledger)
    assert bad is None
    assert "定義の無い列" in (err or "")


def test_promote_and_proposal(db: str) -> None:
    ledger, _ = store.create_ledger(
        actor(),
        {
            "name": "備品",
            "statuses": ["受付"],
            "grants": [{"team_id": "team-a", "role": "admin"}],
        },
    )
    assert ledger is not None
    for value in ("倉庫", "倉庫", "倉庫", "庁舎"):
        store.upsert_row(
            actor(),
            ledger["id"],
            {"extras": [{"label": "置き場", "value": value}, {"label": "個数", "value": "3"}]},
        )
    samples, _ = store.sample_extras(actor(), ledger["id"])
    assert samples is not None
    proposed = assist.propose_fields(samples, existing_labels=[])
    labels = {item["label"]: item["type"] for item in proposed}
    assert labels["置き場"] == "select"
    assert labels["個数"] == "number"
    saved, err = store.promote_extra(actor(), ledger["id"], label="置き場", field_type="text")
    assert err is None and saved is not None
    page, _ = store.list_rows(actor(), ledger["id"])
    assert page is not None
    field_id = next(item["id"] for item in saved["fields"] if item["label"] == "置き場")
    assert all(row["fields"][field_id] for row in page["rows"])
    assert all(all(extra["label"] != "置き場" for extra in row["extras"]) for row in page["rows"])


def test_delete_restore_and_legacy_import(db: str) -> None:
    ledger, _ = store.create_ledger(
        actor(),
        {"name": "備品", "statuses": ["受付"], "grants": [{"team_id": "team-a", "role": "admin"}]},
    )
    assert ledger is not None
    row, _ = store.upsert_row(actor(), ledger["id"], {"business_key": "k1"})
    assert row is not None
    hidden, _ = store.set_deleted(actor(), row["id"], True)
    assert hidden is not None and hidden["deleted_at"]
    page, _ = store.list_rows(actor(), ledger["id"])
    assert page is not None and page["rows"] == []
    store.set_deleted(actor(), row["id"], False)
    page, _ = store.list_rows(actor(), ledger["id"])
    assert page is not None and len(page["rows"]) == 1

    fd, legacy = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    src = sqlite3.connect(legacy)
    src.execute(
        """
        CREATE TABLE ledger_rows (
          id TEXT, application_id TEXT, procedure_id TEXT, procedure_name TEXT,
          confirmed_at TEXT, confirmed_by TEXT, assignee TEXT, status TEXT,
          snapshot_json TEXT, review_json TEXT, comment TEXT, updated_at TEXT
        )
        """
    )
    src.execute(
        "INSERT INTO ledger_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?)",
        (
            "old-row",
            "app-1",
            "proc-1",
            "旧手続き",
            "2020-01-01T00:00:00+00:00",
            "owner",
            "担当課",
            "受理",
            json.dumps({"answers": [{"lines": [{"label": "氏名", "value": "山田"}]}]}),
            "2020-01-01T00:00:00+00:00",
        ),
    )
    src.commit()
    src.close()
    assert store.import_legacy(legacy) == 1
    assert store.import_legacy(legacy) == 0
    owner = store.Actor(user_id="owner", tenant_id=store.DEFAULT_TENANT_ID, is_admin=True)
    found = store.list_ledgers(owner)
    assert any(item["name"] == "旧手続き" for item in found)
    os.remove(legacy)


def test_delete_hides_ledger_and_keeps_rows(db: str) -> None:
    ledger, err = store.create_ledger(
        actor(),
        {"name": "備品", "grants": [{"team_id": "team-a", "role": "admin"}]},
    )
    assert err is None and ledger is not None
    row, err = store.upsert_row(actor(), ledger["id"], {"status": "受付", "fields": {}})
    assert err is None and row is not None
    removed, err = store.delete_ledger(actor(teams=["other"], user_id="user-2"), ledger["id"])
    assert removed is None
    removed, err = store.delete_ledger(actor(), ledger["id"])
    assert err is None and removed is not None
    assert store.list_ledgers(actor()) == []
    missing, err = store.get_ledger(actor(), ledger["id"])
    assert missing is None
    kept = store.connect().execute("SELECT deleted_at FROM ledger_rows WHERE id = ?", (row["id"],)).fetchone()
    assert kept is not None
    assert kept["deleted_at"] == ""


def test_access_follows_teams_not_the_creator(db: str) -> None:
    ledger, err = store.create_ledger(
        actor(),
        {"name": "備品", "grants": [{"team_id": "team-a", "role": "admin"}]},
    )
    assert err is None and ledger is not None
    assert store.list_ledgers(actor(teams=[], user_id="user-1")) == []
    blocked, err = store.update_ledger(actor(), ledger["id"], {"grants": []})
    assert blocked is None
    assert "チーム" in (err or "")
    saved, err = store.update_ledger(
        actor(),
        ledger["id"],
        {
            "grants": [
                {"team_id": "team-a", "role": "admin"},
                {"team_id": "team-b", "role": "editor"},
                {"team_id": "team-c", "role": "viewer"},
            ]
        },
    )
    assert err is None and saved is not None
    assert store.list_ledgers(actor(teams=["team-b"], user_id="user-2"))[0]["role"] == "editor"
    assert store.list_ledgers(actor(teams=["team-c"], user_id="user-3"))[0]["role"] == "viewer"


def test_system_fields_keep_registered_at_and_visibility(db: str) -> None:
    ledger, err = store.create_ledger(
        actor(),
        {"name": "備品", "grants": [{"team_id": "team-a", "role": "admin"}]},
    )
    assert err is None and ledger is not None
    flags = {item["key"]: item["visible"] for item in ledger["system"]}
    assert flags["registered_at"] is True
    assert flags["comment"] is True
    saved, err = store.update_ledger(
        actor(),
        ledger["id"],
        {"system": [{"key": "comment", "visible": False}]},
    )
    assert err is None and saved is not None
    flags = {item["key"]: item["visible"] for item in saved["system"]}
    assert flags["comment"] is False
    assert flags["registered_at"] is True
    assert flags["business_key"] is True
    row, err = store.upsert_row(actor(), ledger["id"], {})
    assert err is None and row is not None
    assert row["created_at"]


def test_material_reads_csv_and_rejects_json() -> None:
    from app import material

    text = material.text_from_bytes("備品.csv", "名前,場所\n机,倉庫\n".encode())
    assert "机" in text and "倉庫" in text
    with pytest.raises(ValueError, match="PDF"):
        material.extension("data.json")
    with pytest.raises(ValueError, match="PDF"):
        material.extension("memo.md")


def test_material_reads_excel_as_a_sample() -> None:
    import io

    import openpyxl

    from app import material

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "備品"
    sheet.append(["名前", "場所", "数量"])
    sheet.append(["机", "倉庫", 2])
    buf = io.BytesIO()
    book.save(buf)
    text = material.text_from_bytes("備品.xlsx", buf.getvalue())
    assert "# 備品" in text
    assert "机" in text and "倉庫" in text


def test_material_proposal_drops_secrets_and_keeps_known_types() -> None:
    text = assist.sanitize_material("氏名 山田\nマイナンバー 123456789012\n数量 3\n")
    assert "マイナンバー" not in text
    assert "123456789012" not in text
    assert "氏名" in text
    fields = assist.fields_from_model(
        {
            "fields": [
                {"label": "氏名", "type": "text"},
                {"label": "マイナンバー", "type": "text"},
                {"label": "数量", "type": "number"},
                {"label": "区分", "type": "select", "options": ["甲", "乙"]},
                {"label": "メモ", "type": "weird"},
                {"label": "氏名", "type": "date"},
            ]
        },
        ["数量"],
    )
    assert [item["label"] for item in fields] == ["氏名", "区分", "メモ"]
    assert fields[1]["options"] == ["甲", "乙"]
    assert fields[2]["type"] == "text"


def test_weaker_origin_does_not_replace_entered(db: str) -> None:
    ledger, _ = store.create_ledger(
        actor(),
        {
            "name": "備品",
            "statuses": ["受付"],
            "fields": [{"id": "place", "label": "場所", "type": "text"}],
            "grants": [{"team_id": "team-a", "role": "admin"}],
        },
    )
    assert ledger is not None
    row, err = store.upsert_row(
        actor(),
        ledger["id"],
        {"fields": {"place": "倉庫"}, "origins": {"place": {"origin": "entered"}}},
    )
    assert err is None and row is not None
    assert row["origins"]["place"]["origin"] == "entered"
    kept, err = store.upsert_row(
        actor(),
        ledger["id"],
        {
            "business_key": row["business_key"],
            "fields": {"place": "会議室"},
            "origins": {"place": {"origin": "inferred"}},
        },
    )
    assert err is None and kept is not None
    assert kept["fields"]["place"] == "倉庫"
    assert kept["kept"][0]["origin"] == "entered"
    imported, err = store.upsert_row(
        actor(),
        ledger["id"],
        {"business_key": row["business_key"], "fields": {"place": "廊下"}},
    )
    assert err is None and imported is not None
    assert imported["fields"]["place"] == "倉庫"
    typed, err = store.upsert_row(
        actor(),
        ledger["id"],
        {
            "business_key": row["business_key"],
            "fields": {"place": "会議室"},
            "origins": {"place": {"origin": "entered"}},
        },
    )
    assert err is None and typed is not None
    assert typed["fields"]["place"] == "会議室"
    assert typed["origins"]["place"]["origin"] == "entered"


def test_ingest_splits_excel_rows_and_attaches_the_file(db: str) -> None:
    import io as bytesio

    import openpyxl

    ledger, _ = store.create_ledger(
        actor(),
        {
            "name": "備品",
            "statuses": ["受付"],
            "fields": [
                {"id": "name", "label": "名前", "type": "text"},
                {"id": "place", "label": "場所", "type": "text"},
            ],
            "grants": [{"team_id": "team-a", "role": "admin"}],
        },
    )
    assert ledger is not None
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "備品"
    sheet.append(["名前", "場所"])
    sheet.append(["机", "倉庫"])
    sheet.append(["椅子", "会議室"])
    buf = bytesio.BytesIO()
    book.save(buf)
    raw = buf.getvalue()
    text = material.text_from_bytes("備品.xlsx", raw)
    parsed = ingest.rows_from_table(text, ledger["fields"], 0)
    assert len(parsed) == 2
    assert parsed[0]["fields"]["place"] == "倉庫"
    assert parsed[0]["origins"]["place"]["origin"] == "imported"
    assert parsed[1]["fields"]["name"] == "椅子"
    batch = ingest.stage_batch(
        ledger["id"],
        "user-1",
        [{"name": "備品.xlsx", "mime": "application/vnd.ms-excel", "raw": raw}],
        parsed,
    )
    count, err = ingest.commit_batch(actor(), ledger["id"], batch, [0, 1])
    assert err is None
    assert count == 2
    page, _ = store.list_rows(actor(), ledger["id"])
    assert page is not None
    places = {row["fields"]["place"]: row for row in page["rows"]}
    assert set(places) == {"倉庫", "会議室"}
    sample = places["倉庫"]
    assert sample["origins"]["place"]["origin"] == "imported"
    assert sample["files"][0]["name"] == "備品.xlsx"
    assert sample["origins"]["place"]["file_id"] == sample["files"][0]["file_id"]
    assert sample["status"] == "受付"


def test_office_preview_shows_excel_cells() -> None:
    import io

    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "備品"
    sheet.append(["名前", "場所"])
    sheet.append(["机", "倉庫"])
    buf = io.BytesIO()
    book.save(buf)
    preview = material.office_preview("備品.xlsx", buf.getvalue())
    assert preview is not None
    assert preview["kind"] == "sheets"
    assert preview["sheets"][0]["name"] == "備品"
    assert preview["sheets"][0]["rows"][1] == ["机", "倉庫"]
    assert material.office_preview("写真.png", b"png") is None


def test_query_parser_finds_last_month() -> None:
    parsed = assist.parse_query("先月、処理中の山田", ["処理中", "完了"])
    assert parsed["status"] == "処理中"
    assert parsed["q"] == "山田"
    assert parsed["date_from"] < parsed["date_to"]


def _body(row: dict) -> dict:
    return next(item for item in row["files"] if item.get("role") == "body")


def test_office_save_replaces_the_body_and_keeps_the_previous(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEDGER_OFFICE_MAX_BYTES", "8")
    saved, err = store.save_office_file(actor(), filename="議事.docx", data=b"one")
    assert err is None and saved is not None
    assert saved["status"] == "下書き"
    assert "title" not in saved["fields"]
    assert saved["fields"]["kind"] == "文書"
    assert saved["business_key"]
    body = _body(saved)
    assert body["name"] == "議事.docx"
    shared = store.list_ledgers(actor(teams=["other"], user_id="user-2"))
    assert shared[0]["source_key"] == "office"
    assert shared[0]["role"] == "editor"
    assert shared[0]["system"][0]["visible"] is False

    again, err = store.save_office_file(
        actor(),
        filename="議事録.docx",
        data=b"two",
        row_id=saved["id"],
        file_id=body["file_id"],
    )
    assert err is None and again is not None
    assert again["id"] == saved["id"]
    assert again["business_key"] == saved["business_key"]
    assert again["status"] == "下書き"
    assert "title" not in again["fields"]
    current = _body(again)
    former = next(item for item in again["files"] if item.get("role") == "former")
    assert current["name"] == "議事録.docx"
    assert current["saved_at"]
    assert former["file_id"] == body["file_id"]
    assert former["saved_at"] == body["saved_at"]
    assert former["replaced_at"] >= former["saved_at"]
    assert current["saved_at"] >= former["replaced_at"]
    path, _name, msg = store.file_path(actor(), again["id"], former["file_id"])
    assert msg is None and path is not None
    assert path.read_bytes() == b"one"

    clash, err = store.save_office_file(
        actor(user_id="user-2", teams=["other"]),
        filename="第三.docx",
        data=b"three",
        row_id=again["id"],
        file_id=body["file_id"],
    )
    assert clash is not None and clash.get("conflict") is True
    assert err and "更新" in err
    stayed, _ = store.get_row(actor(), again["id"])
    assert stayed is not None
    assert _body(stayed)["file_id"] == current["file_id"]

    forced, err = store.save_office_file(
        actor(user_id="user-2", teams=["other"]),
        filename="第三.docx",
        data=b"three",
        row_id=again["id"],
        file_id=body["file_id"],
        force=True,
    )
    assert err is None and forced is not None
    assert _body(forced)["name"] == "第三.docx"

    locked, err = store.upsert_row(
        actor(), forced["ledger_id"], {"business_key": forced["business_key"], "status": "確定"}
    )
    assert err is None and locked is not None
    editor = actor(user_id="user-2", teams=["other"])
    denied, err = store.save_office_file(
        editor,
        filename="第四.docx",
        data=b"four",
        row_id=forced["id"],
        file_id=_body(forced)["file_id"],
        force=True,
    )
    assert denied is None and err and "確定" in err
    reverted, err = store.upsert_row(
        editor, forced["ledger_id"], {"business_key": forced["business_key"], "status": "下書き"}
    )
    assert reverted is None and err and "確定" in err

    copied, err = store.save_office_file(editor, filename="別名.docx", data=b"copy")
    assert err is None and copied is not None
    assert copied["id"] != forced["id"]
    assert copied["status"] == "下書き"

    owner, err = store.save_office_file(
        actor(),
        filename="確定の更新.docx",
        data=b"owner",
        row_id=forced["id"],
        file_id=_body(forced)["file_id"],
    )
    assert err is None and owner is not None
    assert owner["status"] == "確定"

    empty, err = store.save_office_file(actor(), filename="空.docx", data=b"")
    assert empty is None and err
    huge, err = store.save_office_file(actor(), filename="大.docx", data=b"0123456789")
    assert huge is None and err and "大き" in err
    other, err = store.save_office_file(actor(), filename="メモ.pdf", data=b"pdf")
    assert other is None and err


def test_office_ledger_drops_a_title_field_left_from_before(db: str) -> None:
    saved, err = store.save_office_file(actor(), filename="document.docx", data=b"v1")
    assert err is None and saved is not None
    db = store.connect()
    ledger = db.execute("SELECT fields_json FROM ledgers WHERE id = ?", (saved["ledger_id"],)).fetchone()
    fields = json.loads(ledger["fields_json"])
    fields.insert(0, {"id": "title", "label": "題名", "type": "text", "masked": False, "options": []})
    db.execute("UPDATE ledgers SET fields_json = ? WHERE id = ?", (json.dumps(fields), saved["ledger_id"]))
    values = dict(saved["fields"])
    values["title"] = "別の題名"
    db.execute(
        "UPDATE ledger_rows SET fields_json = ? WHERE id = ?",
        (json.dumps(values), saved["id"]),
    )
    db.commit()
    store.reset_connection()
    store.connect()
    ledger_after, err = store.get_ledger(actor(), saved["ledger_id"])
    assert err is None and ledger_after is not None
    assert [item["id"] for item in ledger_after["fields"]] == ["kind", "memo"]
    row, err = store.get_row(actor(), saved["id"])
    assert err is None and row is not None
    assert "title" not in row["fields"]
    assert _body(row)["name"] == "document.docx"


def test_office_versions_remember_when_they_were_saved(db: str) -> None:
    saved, err = store.save_office_file(actor(), filename="document.docx", data=b"v1")
    assert err is None and saved is not None
    again, err = store.save_office_file(
        actor(),
        filename="document.docx",
        data=b"v2",
        row_id=saved["id"],
        file_id=_body(saved)["file_id"],
    )
    assert err is None and again is not None
    conn = store.connect()
    files = json.loads(conn.execute("SELECT files_json FROM ledger_rows WHERE id = ?", (saved["id"],)).fetchone()["files_json"])
    for item in files:
        item.pop("saved_at", None)
    conn.execute("UPDATE ledger_rows SET files_json = ? WHERE id = ?", (json.dumps(files), saved["id"]))
    conn.commit()
    store.reset_connection()
    store.connect()
    row, err = store.get_row(actor(), saved["id"])
    assert err is None and row is not None
    current = _body(row)
    former = next(item for item in row["files"] if item.get("role") == "former")
    assert former["saved_at"]
    assert current["saved_at"]
    assert former["saved_at"] <= current["saved_at"]
    assert former["name"] == current["name"] == "document.docx"


def test_office_restore_makes_the_former_body_current(db: str) -> None:
    saved, _ = store.save_office_file(actor(), filename="初稿.docx", data=b"v1")
    assert saved is not None
    first = _body(saved)["file_id"]
    again, _ = store.save_office_file(
        actor(), filename="二稿.docx", data=b"v2", row_id=saved["id"], file_id=first
    )
    assert again is not None
    restored, err = store.restore_office_body(actor(), again["id"], first)
    assert err is None and restored is not None
    assert _body(restored)["file_id"] == first
    assert _body(restored)["name"] == "初稿.docx"
    path, _name, msg = store.file_path(actor(), restored["id"], _body(again)["file_id"])
    assert msg is None and path is not None
    assert path.read_bytes() == b"v2"

    locked, _ = store.upsert_row(
        actor(), restored["ledger_id"], {"business_key": restored["business_key"], "status": "確定"}
    )
    assert locked is not None
    denied, err = store.restore_office_body(
        actor(user_id="user-2", teams=["other"]), restored["id"], _body(again)["file_id"]
    )
    assert denied is None and err and "確定" in err


def test_office_viewer_cannot_save(db: str) -> None:
    saved, _ = store.save_office_file(actor(), filename="共有.docx", data=b"v1")
    assert saved is not None
    ledger, _ = store.get_ledger(actor(), saved["ledger_id"])
    assert ledger is not None
    updated, err = store.update_ledger(
        actor(),
        ledger["id"],
        {
            "grants": [
                {"team_id": "team-a", "role": "admin"},
                {"team_id": "team-b", "role": "viewer"},
            ]
        },
    )
    assert err is None and updated is not None
    denied, err = store.save_office_file(
        actor(teams=["team-b"], user_id="user-b"), filename="追記.docx", data=b"no"
    )
    assert denied is None and err and "権限" in err
