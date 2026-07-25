from __future__ import annotations

import pytest

from conftest import load_service_module


@pytest.fixture()
def tagstore(tmp_path, monkeypatch: pytest.MonkeyPatch):
    mod = load_service_module("rag-app/app/tagstore.py")
    monkeypatch.setattr(mod, "DB_PATH", str(tmp_path / "rag_meta.db"))
    mod.init_db()
    return mod


def test_create_and_list_tags(tagstore) -> None:
    tagstore.create_tag("s1", "例規")
    tagstore.ensure_tags("s1", ["総務", "例規"])
    names = [r["tag"] for r in tagstore.list_tags("s1")]
    assert names == ["例規", "総務"]


def test_rename_and_delete(tagstore) -> None:
    tagstore.create_tag("s1", "old")
    tagstore.rename_tag("s1", "old", "new")
    assert [r["tag"] for r in tagstore.list_tags("s1")] == ["new"]
    tagstore.delete_tag("s1", "new")
    assert tagstore.list_tags("s1") == []


def test_rename_conflict(tagstore) -> None:
    tagstore.create_tag("s1", "a")
    tagstore.create_tag("s1", "b")
    with pytest.raises(ValueError):
        tagstore.rename_tag("s1", "a", "b")
