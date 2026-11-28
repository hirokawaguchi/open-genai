"""ノートから Markdown エディタの編集画面へ渡すときの手順。"""

from __future__ import annotations

import asyncio
import base64
import json

import httpx

from app.notebook_handoff import HandoffError, manuscript_filename, open_in_editor, place_manuscript


def _run(handler, **kwargs):
    async def main():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await open_in_editor(
                client,
                download_url="http://notebook/sessions/s1/download",
                editor_base="http://editor",
                notebook_headers={"x-user-id": "u"},
                editor_headers={"x-user-id": "u"},
                **kwargs,
            )

    return asyncio.run(main())


def test_new_project_starts_hearing_generation() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/download"):
            return httpx.Response(200, content=b"PK\x03\x04sheet")
        if request.method == "POST" and request.url.path == "/projects":
            assert json.loads(request.content) == {"name": "議事録"}
            return httpx.Response(200, json={"project": {"id": "p1", "name": "議事録"}})
        if request.url.path == "/projects/p1/generate":
            body = json.loads(request.content)
            assert body["theme"] == "hearing"
            assert body["inputs"]["hearing"] == base64.b64encode(b"PK\x03\x04sheet").decode()
            assert "compose" not in request.url.path
            return httpx.Response(200, json={"request_id": "r1", "status": "processing"})
        return httpx.Response(500, json={"error": "unexpected"})

    result = _run(handler, mode="new", name="議事録", project_id="")
    assert result == {"project_id": "p1", "request_id": "r1"}
    assert ("POST", "/projects") in seen
    assert ("POST", "/projects/p1/generate") in seen


def test_existing_project_does_not_create_another() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/download"):
            return httpx.Response(200, content=b"PK\x03\x04sheet")
        if request.method == "GET" and request.url.path == "/projects/p9":
            return httpx.Response(200, json={"project": {"id": "p9"}})
        if request.method == "POST" and request.url.path == "/projects":
            return httpx.Response(500, json={"error": "作ってはいけない"})
        if request.url.path == "/projects/p9/generate":
            return httpx.Response(200, json={"request_id": "r9"})
        return httpx.Response(404, json={"error": "unexpected"})

    result = _run(handler, mode="existing", name="", project_id="p9")
    assert result["project_id"] == "p9"
    assert result["request_id"] == "r9"


def test_generate_failure_keeps_the_new_project_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/download"):
            return httpx.Response(200, content=b"PK\x03\x04sheet")
        if request.method == "POST" and request.url.path == "/projects":
            return httpx.Response(200, json={"project": {"id": "p2"}})
        if request.url.path.endswith("/generate"):
            return httpx.Response(503, json={"error": "生成 API に接続できません。"})
        return httpx.Response(500)

    try:
        _run(handler, mode="new", name="仕様書", project_id="")
    except HandoffError as e:
        assert e.status == 503
        assert e.project_id == "p2"
        assert "接続できません" in e.message
    else:
        raise AssertionError("失敗するはず")


def test_manuscript_filename_keeps_the_previous_file() -> None:
    assert manuscript_filename("DXに関する取組", "document", set()) == "DXに関する取組-文書.md"
    assert (
        manuscript_filename("DXに関する取組", "slides", {"DXに関する取組-文書.md"})
        == "DXに関する取組-スライド.md"
    )
    assert (
        manuscript_filename("DXに関する取組", "document", {"DXに関する取組-文書.md"})
        == "DXに関する取組-文書-2.md"
    )


def test_place_manuscript_uses_a_new_name() -> None:
    saved: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/projects/p1":
            return httpx.Response(200, json={"project": {"id": "p1"}})
        if request.method == "GET" and request.url.path == "/projects/p1/files":
            return httpx.Response(200, json={"files": [{"rel_path": "DXに関する取組-文書.md"}]})
        if request.method == "POST" and request.url.path == "/projects/p1/files/save":
            body = json.loads(request.content)
            saved["path"] = body["path"]
            saved["content"] = body["content"]
            return httpx.Response(200, json={"path": body["path"]})
        return httpx.Response(500, json={"error": "unexpected"})

    async def main():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await place_manuscript(
                client,
                editor_base="http://editor",
                editor_headers={"x-user-id": "u"},
                mode="existing",
                name="DXに関する取組",
                project_id="p1",
                manuscript="本文",
                form="slides",
                title="DXに関する取組",
            )

    result = asyncio.run(main())
    assert result["file"] == "DXに関する取組-スライド.md"
    assert saved["path"] == "DXに関する取組-スライド.md"
    assert saved["content"] == "本文"
