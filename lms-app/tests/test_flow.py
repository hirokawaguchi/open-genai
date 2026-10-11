import base64
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app import convert, storage, store, transcript
from app.main import app


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("LMS_DB_PATH", str(tmp_path / "lms.db"))
    monkeypatch.setenv("LMS_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LMS_STORAGE", "memory")
    monkeypatch.setenv("INTERNAL_SIGNING_SECRET", "")
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "lms.db"))
    monkeypatch.setattr(store, "UPLOAD_DIR", str(tmp_path / "uploads"))
    storage.reset_storage()
    transcript._busy.clear()
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    store.init_db()
    return store


def access(user="editor@example.jp", *, member=True, tenant="tenant-1", teams=None, users=None):
    return store.Access(
        user_id=user,
        user_name=user,
        tenant_id=tenant,
        member=member,
        teams=teams
        or {
            "team-1": store.TeamInfo("team-1", "市民課", ("editor@example.jp", "learner@example.jp")),
        },
        users=users
        or {
            "editor@example.jp": "編集者",
            "learner@example.jp": "受講者",
            "cert@example.jp": "認定者",
        },
    )


def _upload(editor, title="研修動画", filename="intro.mp4", payload=b"video-bytes"):
    session = store.start_upload(
        editor,
        {"title": title, "filename": filename, "kind": "video", "contentType": "video/mp4", "size": len(payload)},
    )
    store.append_part(editor, session["id"], 0, payload)
    return store.complete_upload(editor, session["id"])


def _publish_course(editor, material_id):
    course = store.create_course(editor, "情報セキュリティ")
    store.save_draft(
        editor,
        course["id"],
        {
            "title": "情報セキュリティ",
            "chapters": [
                {
                    "title": "本編",
                    "lessons": [
                        {
                            "title": "動画",
                            "kind": "video",
                            "required": True,
                            "materialId": material_id,
                        },
                        {
                            "title": "確認",
                            "kind": "quiz",
                            "required": True,
                            "masteryScore": 100,
                            "questions": [
                                {
                                    "prompt": "届ける先は",
                                    "choices": ["ブラウザ", "教材サーバ"],
                                    "correctIndex": 0,
                                }
                            ],
                        },
                        {
                            "title": "実技",
                            "kind": "practical",
                            "required": True,
                            "practicalText": "例のシステムで申請を登録できる",
                        },
                    ],
                }
            ],
        },
    )
    return store.publish_course(editor, course["id"])


def test_delete_course_removes_it(db):
    editor = access()
    course = store.create_course(editor, "消すコース")
    store.set_assignment(editor, course["id"], {"assigneeType": "user", "assigneeId": "learner@example.jp"})
    store.delete_course(editor, course["id"])
    with pytest.raises(store.LmsError) as missing:
        store.get_course(editor, course["id"])
    assert missing.value.status == 404
    kept = store.create_course(editor, "残すコース")
    with pytest.raises(store.LmsError) as other:
        store.delete_course(access(tenant="tenant-2"), kept["id"])
    assert other.value.status == 404
    with pytest.raises(store.LmsError) as learner:
        store.delete_course(access("learner@example.jp"), kept["id"])
    assert learner.value.status == 403
    assert store.get_course(editor, kept["id"])["title"] == "残すコース"


def test_preview_keeps_lessons_without_materials(db):
    editor = access()
    course = store.create_course(editor, "下書き")
    store.save_draft(
        editor,
        course["id"],
        {
            "title": "下書き",
            "chapters": [
                {
                    "title": "基礎",
                    "lessons": [
                        {"title": "動画", "kind": "video", "materialId": ""},
                        {"title": "確認", "kind": "quiz", "questions": []},
                        {"title": "実技", "kind": "practical", "practicalText": ""},
                    ],
                }
            ],
        },
    )
    preview = store.preview_course(editor, course["id"])
    titles = [lesson["title"] for chapter in preview["snapshot"]["chapters"] for lesson in chapter["lessons"]]
    assert titles == ["動画", "確認", "実技"]
    with pytest.raises(store.LmsError):
        store.publish_course(editor, course["id"])


def test_draft_keeps_blank_titles(db):
    editor = access()
    course = store.create_course(editor, "下書き")
    saved = store.save_draft(
        editor,
        course["id"],
        {"title": "下書き", "chapters": [{"title": "", "lessons": [{"title": "", "kind": "video"}]}]},
    )
    chapter = saved["draft"]["chapters"][0]
    assert chapter["title"] == ""
    assert chapter["lessons"][0]["title"] == ""
    with pytest.raises(store.LmsError) as raised:
        store.publish_course(editor, course["id"])
    assert "章タイトル" in str(raised.value)


def test_member_manages_library_without_a_course(db):
    person = access("learner@example.jp")
    assert store.home(person)["canUseLibrary"] is True
    assert store.list_materials(person)["materials"] == []
    material = _upload(person, title="先に置く")
    assert store.list_materials(person)["materials"][0]["id"] == material["id"]
    with pytest.raises(store.LmsError) as outsider:
        store.list_materials(access(member=False))
    assert outsider.value.status == 403


def test_publish_pin_and_completion(db):
    editor = access()
    store.create_course(editor, "置き場")
    material = _upload(editor)
    published = _publish_course(editor, material["id"])
    course_id = published["id"]
    store.set_role(editor, course_id, "cert@example.jp", "certifier")
    store.set_assignment(
        editor,
        course_id,
        {"assigneeType": "user", "assigneeId": "learner@example.jp", "required": True, "dueAt": "2020-01-01"},
    )
    learner = access("learner@example.jp")
    started = store.start_enrollment(learner, course_id)
    version_id = started["versionId"]
    lessons = started["snapshot"]["chapters"][0]["lessons"]
    video, quiz, practical = lessons
    assert "correctIndex" not in quiz["questions"][0]
    assert video["playbackUrl"].endswith(material["id"] + "/original.mp4") or "original.mp4" in video["playbackUrl"]

    store.save_draft(
        editor,
        course_id,
        {
            "title": "改訂",
            "chapters": [
                {
                    "title": "本編",
                    "lessons": [
                        {"title": "動画", "kind": "video", "required": True, "materialId": material["id"]},
                    ],
                }
            ],
        },
    )
    store.publish_course(editor, course_id)
    again = store.start_enrollment(learner, course_id)
    assert again["versionId"] == version_id
    assert again["snapshot"]["title"] == "情報セキュリティ"

    video_id = video["id"]
    mid = store.record_progress(
        learner,
        started["enrollmentId"],
        video_id,
        {"lesson_location": "3", "duration": 100, "sessionSeconds": 3},
    )
    assert mid["records"][video_id]["lesson_status"] == "incomplete"
    done = store.record_progress(
        learner,
        started["enrollmentId"],
        video_id,
        {"lesson_location": "100", "duration": 100, "sessionSeconds": 4, "ended": True},
    )
    assert done["records"][video_id]["lesson_status"] == "completed"
    assert done["state"] == "in_progress"

    failed = store.submit_quiz(learner, started["enrollmentId"], quiz["id"], [1])
    assert failed["records"][quiz["id"]]["lesson_status"] == "failed"
    assert failed["records"][quiz["id"]]["score_raw"] == 0
    passed = store.submit_quiz(learner, started["enrollmentId"], quiz["id"], [0])
    assert passed["records"][quiz["id"]]["lesson_status"] == "passed"
    assert passed["records"][quiz["id"]]["score_raw"] == 100
    assert passed["snapshot"]["chapters"][0]["lessons"][1]["questions"][0]["correctIndex"] == 0

    with pytest.raises(store.LmsError) as raised:
        store.grade_practical(editor, started["enrollmentId"], practical["id"], "passed", None)
    assert raised.value.status == 403
    cert = access("cert@example.jp")
    rows = store.progress(cert, course_id)["rows"]
    learner_row = next(row for row in rows if row["userId"] == "learner@example.jp")
    assert learner_row["materialDone"] is True
    assert learner_row["practicalPending"] is True
    assert learner_row["overdue"] is True
    graded = store.grade_practical(cert, started["enrollmentId"], practical["id"], "passed", 90)
    assert graded["records"][practical["id"]]["graded_by"] == "cert@example.jp"
    assert graded["state"] == "completed"
    finished = store.progress(editor, course_id)["rows"]
    learner_row = next(row for row in finished if row["userId"] == "learner@example.jp")
    assert learner_row["state"] == "completed"
    assert learner_row["practicalPending"] is False

    csv_text = store.progress_csv(editor, course_id)
    assert "受講者" in csv_text
    assert "修了" in csv_text


def test_suspend_data_limit_and_tenant_wall(db):
    editor = access()
    store.create_course(editor, "置き場")
    material = _upload(editor)
    published = _publish_course(editor, material["id"])
    store.set_assignment(
        editor,
        published["id"],
        {"assigneeType": "team", "assigneeId": "team-1", "required": False, "dueAt": None},
    )
    learner = access("learner@example.jp")
    started = store.start_enrollment(learner, published["id"])
    video_id = started["snapshot"]["chapters"][0]["lessons"][0]["id"]
    with pytest.raises(store.LmsError):
        store.record_progress(
            learner,
            started["enrollmentId"],
            video_id,
            {"lesson_location": "1", "duration": 10, "suspend_data": "x" * 4097},
        )
    other = access(tenant="tenant-2")
    with pytest.raises(store.LmsError) as raised:
        store.get_course(other, published["id"])
    assert raised.value.status == 404


def test_delete_material_only_when_unused(db):
    editor = access()
    store.create_course(editor, "置き場")
    unused = _upload(editor, title="未使用")
    store.delete_material(editor, unused["id"])
    assert store.list_materials(editor)["materials"] == []
    mem = storage.get_storage()
    assert not any(unused["id"] in key for key in mem.objects)

    used = _upload(editor, title="使用中")
    published = _publish_course(editor, used["id"])
    with pytest.raises(store.LmsError) as blocked:
        store.delete_material(editor, used["id"])
    assert "情報セキュリティ" in str(blocked.value)
    assert any(used["id"] in key for key in mem.objects)

    store.save_draft(editor, published["id"], {"title": "情報セキュリティ", "chapters": []})
    with pytest.raises(store.LmsError):
        store.delete_material(editor, used["id"])
    store.delete_course(editor, published["id"])
    store.delete_material(editor, used["id"])
    assert not any(used["id"] in key for key in mem.objects)

    kept = _upload(editor, title="残す")
    other_editor = access(tenant="tenant-2", teams={"team-2": store.TeamInfo("team-2", "別の課", ("editor@example.jp",))})
    store.create_course(other_editor, "別の棟")
    with pytest.raises(store.LmsError) as other:
        store.delete_material(other_editor, kept["id"])
    assert other.value.status == 404
    with pytest.raises(store.LmsError) as outsider:
        store.delete_material(access(member=False), kept["id"])
    assert outsider.value.status == 403


def test_trash_can_be_restored(db):
    editor = access()
    store.create_course(editor, "置き場")
    material = _upload(editor, title="戻す教材")
    store.hide_material(editor, material["id"])
    assert store.list_materials(editor)["materials"] == []
    assert [item["id"] for item in store.list_materials(editor, trashed=True)["materials"]] == [material["id"]]
    restored = store.restore_material(editor, material["id"])
    assert restored["id"] == material["id"]
    assert store.list_materials(editor, trashed=True)["materials"] == []
    assert store.list_materials(editor)["materials"][0]["id"] == material["id"]
    mem = storage.get_storage()
    assert any(material["id"] in key for key in mem.objects)


def test_hide_keeps_bytes(db):
    editor = access()
    store.create_course(editor, "置き場")
    material = _upload(editor)
    store.hide_material(editor, material["id"])
    assert store.list_materials(editor)["materials"] == []
    mem = storage.get_storage()
    assert any(material["id"] in key for key in mem.objects)


def test_slide_conversion_reports_progress(db, monkeypatch):
    editor = access()
    seen: list[str] = []

    def fake(_data, on_status=None):
        if on_status:
            on_status("PDF をページごとの画像にしています")
        return [b"png-a", b"png-b"]

    monkeypatch.setattr(convert, "pdf_to_pngs", fake)
    payload = b"%PDF-1.4 fake"
    session = store.start_upload(
        editor,
        {
            "title": "手順",
            "filename": "steps.pdf",
            "kind": "slides",
            "contentType": "application/pdf",
            "size": len(payload),
        },
    )

    real_note = store._note_upload

    def spy(session_id, text):
        real_note(session_id, text)
        if text == "PDF をページごとの画像にしています":
            seen.append(store.upload_progress(editor, session_id)["progress"])

    monkeypatch.setattr(store, "_note_upload", spy)
    store.append_part(editor, session["id"], 0, payload)
    material = store.complete_upload(editor, session["id"])
    assert seen == ["PDF をページごとの画像にしています"]
    assert material["slideCount"] == 2
    with pytest.raises(store.LmsError):
        store.upload_progress(editor, session["id"])


def test_slides_use_converter(db, monkeypatch):
    editor = access()
    store.create_course(editor, "置き場")
    monkeypatch.setattr(convert, "pdf_to_pngs", lambda data, on_status=None: [b"png-a", b"png-b"])
    with pytest.raises(store.LmsError):
        store.start_upload(
            editor,
            {
                "title": "手順",
                "filename": "steps.pptx",
                "kind": "slides",
                "contentType": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "size": 4,
            },
        )
    payload = b"%PDF-1.4 fake"
    session = store.start_upload(
        editor,
        {
            "title": "手順",
            "filename": "steps.pdf",
            "kind": "slides",
            "contentType": "application/pdf",
            "size": len(payload),
        },
    )
    store.append_part(editor, session["id"], 0, payload)
    material = store.complete_upload(editor, session["id"])
    assert material["kind"] == "slides"
    assert material["slideCount"] == 2


def _slides(editor, monkeypatch, title="手順"):
    monkeypatch.setattr(convert, "pdf_to_pngs", lambda data, on_status=None: [b"png-a", b"png-b"])
    payload = b"%PDF-1.4 fake"
    session = store.start_upload(
        editor,
        {
            "title": title,
            "filename": "steps.pdf",
            "kind": "slides",
            "contentType": "application/pdf",
            "size": len(payload),
        },
    )
    store.append_part(editor, session["id"], 0, payload)
    return store.complete_upload(editor, session["id"])


def test_pdf_transcript_is_one_row_per_page(db, monkeypatch):
    editor = access()
    material = _slides(editor, monkeypatch)
    monkeypatch.setenv("LMS_TRANSCRIBE_SYNC", "1")
    monkeypatch.setattr(convert, "pdf_page_texts", lambda data: ["1ページの本文", ""])
    started = store.start_transcript(editor, material["id"], redo=False)
    assert started["status"] == "draft"
    assert started["playbackUrl"].startswith("http")
    assert [row["text"] for row in started["segments"]] == ["1ページの本文", ""]
    assert [row["start"] for row in started["segments"]] == [1, 2]
    assert store.list_materials(editor)["materials"][0]["transcriptStatus"] == "draft"
    saved = store.save_transcript(
        editor,
        material["id"],
        {"segments": [{**started["segments"][0], "text": "直した本文"}, started["segments"][1]]},
    )
    assert saved["status"] == "draft"
    assert saved["segments"][0]["text"] == "直した本文"
    confirmed = store.confirm_transcript(editor, material["id"])
    assert confirmed["status"] == "confirmed"
    assert store.list_materials(editor)["materials"][0]["transcriptStatus"] == "confirmed"
    edited = store.save_transcript(editor, material["id"], {"segments": confirmed["segments"]})
    assert edited["status"] == "draft"
    with pytest.raises(store.LmsError, match="やり直す"):
        store.start_transcript(editor, material["id"], redo=False)
    store.finish_transcript(editor.tenant_id, material["id"], "stale", [{"id": "x", "start": 1, "end": 1, "text": "上書き"}], "")
    assert store.get_transcript(editor, material["id"])["segments"][0]["text"] == "直した本文"


def test_scanned_pdf_has_no_body(db, monkeypatch):
    editor = access()
    material = _slides(editor, monkeypatch)
    monkeypatch.setenv("LMS_TRANSCRIBE_SYNC", "1")
    monkeypatch.setattr(convert, "pdf_page_texts", lambda data: ["", ""])
    started = store.start_transcript(editor, material["id"], redo=False)
    assert "本文がありません" in started["notice"]
    with pytest.raises(store.LmsError, match="本文がありません"):
        store.confirm_transcript(editor, material["id"])


def test_sparse_pdf_page_gets_image_description(db, monkeypatch):
    from app import vision

    editor = access()
    material = _slides(editor, monkeypatch)
    monkeypatch.setenv("LMS_TRANSCRIBE_SYNC", "1")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://llm.invalid/v1")
    dense = "あ" * 60
    monkeypatch.setattr(convert, "pdf_page_texts", lambda data: [dense, "図"])

    def fake(png: bytes) -> str:
        assert png == b"png-b"
        return "庁舎の外観が写っています"

    monkeypatch.setattr(vision, "describe_png", fake)
    started = store.start_transcript(editor, material["id"], redo=False)
    assert started["segments"][0]["text"] == dense
    assert "図" in started["segments"][1]["text"]
    assert "庁舎の外観が写っています" in started["segments"][1]["text"]
    assert started["segments"][1]["text"].startswith("図")


def test_video_transcript_uses_speech_spans(db, monkeypatch):
    editor = access()
    material = _upload(editor)
    monkeypatch.setenv("LMS_TRANSCRIBE_SYNC", "1")

    def fake(_data, _filename):
        return [{"start": 0.0, "end": 1.5, "text": "こんにちは"}]

    monkeypatch.setattr(transcript, "transcribe_video", fake)
    started = store.start_transcript(editor, material["id"], redo=False)
    assert started["status"] == "draft"
    assert started["playbackUrl"].startswith("http")
    assert started["segments"][0]["text"] == "こんにちは"
    assert started["segments"][0]["end"] == 1.5
    second = {**started["segments"][0], "id": "right", "start": 1.5, "end": 3.0, "text": "次の区間"}
    saved = store.save_transcript(
        editor,
        material["id"],
        {"segments": [{**started["segments"][0], "end": 1.5}, second]},
    )
    assert [row["text"] for row in saved["segments"]] == ["こんにちは", "次の区間"]
    assert store.confirm_transcript(editor, material["id"])["status"] == "confirmed"

    def replaced(_data, _filename):
        return [{"start": 0.2, "end": 0.8, "text": "やり直した"}]

    monkeypatch.setattr(transcript, "transcribe_video", replaced)
    again = store.start_transcript(editor, material["id"], redo=True)
    assert again["segments"][0]["text"] == "やり直した"
    assert again["status"] == "draft"


def test_video_transcript_failure_and_size(db, monkeypatch):
    editor = access()
    material = _upload(editor)
    monkeypatch.setenv("LMS_TRANSCRIBE_SYNC", "1")
    real_transcribe = transcript.transcribe_video

    def boom(_data, _filename):
        raise store.LmsError("文字起こしサービスに接続できません")

    monkeypatch.setattr(transcript, "transcribe_video", boom)
    failed = store.start_transcript(editor, material["id"], redo=False)
    assert failed["status"] == "failed"
    assert failed["error"] == "文字起こしサービスに接続できません"
    with pytest.raises(store.LmsError, match="やり直してください"):
        store.save_transcript(editor, material["id"], {"segments": []})
    monkeypatch.setattr(transcript, "transcribe_video", real_transcribe)
    monkeypatch.setenv("LMS_TRANSCRIBE_MAX_BYTES", "4")
    with pytest.raises(store.LmsError, match="180MB"):
        transcript.transcribe_video(b"12345", "intro.mp4")
    outsider = access(member=False)
    with pytest.raises(store.LmsError) as denied:
        store.get_transcript(outsider, material["id"])
    assert denied.value.status == 403
    other = access(tenant="tenant-2")
    with pytest.raises(store.LmsError) as missing:
        store.get_transcript(other, material["id"])
    assert missing.value.status == 404
    transcript.claim(material["id"])
    try:
        with pytest.raises(store.LmsError, match="途中"):
            store.start_transcript(editor, material["id"], redo=True)
    finally:
        transcript.release(material["id"])


def test_http_config(db):
    payload = {
        "userId": "editor@example.jp",
        "userName": "編集者",
        "tenantId": "tenant-1",
        "member": True,
        "teams": [],
        "users": [],
    }
    raw = base64.b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).decode()
    scope = hashlib.sha256(raw.encode()).hexdigest()
    client = TestClient(app)
    res = client.get(
        "/config",
        headers={
            "x-api-key": "local-rag-key",
            "x-user-id": "editor@example.jp",
            "x-scope": scope,
            "x-lms-access": raw,
        },
    )
    assert res.status_code == 200
    assert res.json()["enabled"] is True
