from app import extract, ocr, store


def test_update_file_replaces_body(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()
    created = store.create_session(user_id="u1")
    sid = created["id"]
    # 登録は「読み取り中」で先に受け付ける（本文なし）。
    store.add_file(
        sid,
        "u1",
        filename="scan.pdf",
        raw=b"%PDF",
        error="",
        nodes=[],
        briefing={"ocr_pending": True},
        file_id="f1",
    )
    detail = store.get_session(sid, "u1")
    assert detail["files"][0]["briefing"].get("ocr_pending") is True

    # OCR 完了後の差し替え。
    ok = store.update_file(
        sid,
        "u1",
        "f1",
        nodes=[{"id": "n1", "text": "本文", "source": "scan.pdf"}],
        briefing={"ocr": True},
        error="",
    )
    assert ok is True
    detail = store.get_session(sid, "u1")
    f = detail["files"][0]
    assert f["node_count"] == 1
    assert f["briefing"].get("ocr") is True
    assert f["briefing"].get("ocr_pending") is None

    # 他人のセッションは更新できない。
    assert store.update_file(sid, "other", "f1", error="x") is False


def test_text_file_needs_no_ocr(tmp_path):
    pages, pending = extract.extract_text_pages("note.txt", b"hello world")
    assert pending is False
    assert any((p.get("text") or "").strip() for p in pages)


def test_scanned_pdf_defers_ocr(monkeypatch):
    # 文字の無いスキャン PDF は、ここでは OCR を走らせず ocr_pending を立てる。
    monkeypatch.setattr(extract, "extract_doc_pages", lambda *a, **k: [{"page": 1, "text": ""}])
    monkeypatch.setattr(ocr, "OCR_ENABLED", True)
    monkeypatch.setattr(ocr, "_engine_failed", False)
    pages, pending = extract.extract_text_pages("scan.pdf", b"%PDF-1.4")
    assert pending is True
    assert all(not (p.get("text") or "").strip() for p in pages)
