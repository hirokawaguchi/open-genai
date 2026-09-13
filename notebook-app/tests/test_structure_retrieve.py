from app import retrieve, store, structure


def test_build_nodes_from_markdown_headings():
    pages = [
        {"page": 1, "text": "# 背景\n\n予算が不足している。\n\n# 対策\n\n人員を増やす。"}
    ]
    nodes = structure.build_nodes(pages)
    titles = [n["title"] for n in nodes]
    assert "背景" in titles
    assert "対策" in titles
    briefing = structure.briefing_from_nodes("note.md", nodes)
    assert "背景" in briefing["outline"]


def test_select_nodes_prefers_matching_section():
    nodes = [
        {"title": "背景", "text": "予算が不足している。", "source": "a.md"},
        {"title": "その他", "text": "今日の天気は晴れ。", "source": "a.md"},
    ]
    picked = retrieve.select_nodes("予算はどうか", nodes)
    assert picked
    assert any("予算" in (n.get("text") or "") for n in picked)
    material, cites = retrieve.format_material(picked)
    assert "[1]" in material
    assert cites
    assert cites[0]["n"] == 1
    assert "[1]" not in cites[0]["display_name"]


def test_filter_and_strip_citation_marks():
    cites = [
        {"n": 1, "display_name": "a.md / 背景", "text": "予算"},
        {"n": 2, "display_name": "a.md / その他", "text": "天気"},
    ]
    used = retrieve.filter_used_citations("予算は不足している。[1]", cites)
    assert [c["n"] for c in used] == [1]
    assert retrieve.strip_citation_marks("不足。[1][2] 増員する。") == "不足。 増員する。"


def test_store_nodes_and_knowledge_ref(tmp_path, monkeypatch):
    db = tmp_path / "hearing.db"
    monkeypatch.setenv("HEARING_DB_PATH", str(db))
    store._db = None
    store.init_db()
    created = store.create_session(user_id="u1", title="調査")
    sid = created["id"]
    store.add_file(
        sid,
        "u1",
        filename="note.md",
        raw="# 課題\n不足".encode("utf-8"),
        nodes=[{"title": "課題", "text": "不足", "source": "note.md"}],
        briefing={"summary": "不足", "outline": ["課題"], "terms": []},
    )
    store.add_knowledge_ref(
        sid,
        "u1",
        scope="team-1",
        doc_id="doc-1",
        source="規程.pdf",
        title="規程",
        nodes=[{"title": "第1条", "text": "目的", "source": "規程.pdf"}],
        briefing={"summary": "目的", "outline": ["第1条"]},
    )
    nodes = store.list_material_nodes(sid, "u1")
    assert nodes and {n["title"] for n in nodes} >= {"課題", "第1条"}
    listed = store.list_sessions("u1")
    assert listed[0]["item_count"] == 0
    added = store.add_item(sid, "u1", label="課題は何か")
    item_id = added["items"][0]["id"]
    store.update_item(
        sid,
        "u1",
        item_id,
        value="不足している。",
        citations=[{"n": 1, "display_name": "note.md / 課題", "text": "不足"}],
    )
    detail = store.get_session(sid, "u1")
    assert detail["items"][0]["citations"][0]["display_name"] == "note.md / 課題"
