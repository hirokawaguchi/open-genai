"""保存した図（draw.io）の永続化テスト。"""

import os
import tempfile

import pytest

from app import storage


@pytest.fixture
def db_path(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(storage, "DB_PATH", path)
    storage.init_db()
    yield path
    os.unlink(path)


def test_diagram_is_scoped_to_user_and_tenant(db_path):
    tenant = storage.DEFAULT_TENANT_ID
    other = "00000000-0000-0000-0000-0000000000t2"
    created = storage.create_diagram("user-1", tenant, "経費フロー", "flowchart TD\nA-->B", "<xml/>")
    assert created["title"] == "経費フロー"
    assert created["drawioXml"] == "<xml/>"

    listed = storage.list_diagrams("user-1", tenant)
    assert [item["diagramId"] for item in listed] == [created["diagramId"]]
    assert "drawioXml" not in listed[0]

    assert storage.list_diagrams("user-2", tenant) == []
    assert storage.list_diagrams("user-1", other) == []
    assert storage.find_diagram(created["diagramId"], "user-2", tenant) is None

    renamed = storage.update_diagram(
        created["diagramId"], "user-1", tenant, title="更新後"
    )
    assert renamed is not None
    assert renamed["title"] == "更新後"
    assert storage.update_diagram(created["diagramId"], "user-2", tenant, title="横取り") is None

    assert storage.delete_diagram(created["diagramId"], "user-2", tenant) is False
    assert storage.delete_diagram(created["diagramId"], "user-1", tenant) is True
    assert storage.find_diagram(created["diagramId"], "user-1", tenant) is None


def test_diagram_keeps_instruction_and_type(db_path):
    tenant = storage.DEFAULT_TENANT_ID
    created = storage.create_diagram(
        "user-1",
        tenant,
        "朝の準備",
        "flowchart TD\nA-->B",
        "<xml/>",
        instruction="朝の準備の流れを図示する",
        diagram_type="flowchart",
    )
    assert created["instruction"] == "朝の準備の流れを図示する"
    assert created["diagramType"] == "flowchart"
    listed = storage.list_diagrams("user-1", tenant)
    assert "instruction" not in listed[0]
    assert "drawioXml" not in listed[0]

    updated = storage.update_diagram(
        created["diagramId"],
        "user-1",
        tenant,
        instruction="判断を一つ足す",
        diagram_type="sequencediagram",
    )
    assert updated is not None
    assert updated["instruction"] == "判断を一つ足す"
    assert updated["diagramType"] == "sequencediagram"
    assert updated["drawioXml"] == "<xml/>"
    assert updated["mermaidSource"] == "flowchart TD\nA-->B"


def test_existing_diagram_table_gains_prompt_columns(db_path):
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE diagrams")
    conn.execute(
        """
        CREATE TABLE diagrams (
            diagramId TEXT PRIMARY KEY,
            userId TEXT NOT NULL,
            tenantId TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            mermaidSource TEXT NOT NULL DEFAULT '',
            drawioXml TEXT NOT NULL DEFAULT '',
            createdDate TEXT NOT NULL,
            updatedDate TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO diagrams"
        " (diagramId, userId, tenantId, title, mermaidSource, drawioXml, createdDate, updatedDate)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("d1", "user-1", storage.DEFAULT_TENANT_ID, "既存", "", "<xml/>", "1", "1"),
    )
    conn.commit()
    conn.close()

    storage.init_db()
    found = storage.find_diagram("d1", "user-1", storage.DEFAULT_TENANT_ID)
    assert found is not None
    assert found["instruction"] == ""
    assert found["diagramType"] == ""
    assert found["drawioXml"] == "<xml/>"
