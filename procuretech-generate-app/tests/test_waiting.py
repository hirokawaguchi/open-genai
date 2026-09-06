from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app, _JOBS
from app.waiting import is_png, make_fallback_waiting_png


def test_fallback_is_png():
    data = make_fallback_waiting_png()
    assert is_png(data)


def test_waiting_picture_and_job_image(tmp_path):
    client = TestClient(app)
    standalone = client.post("/waiting-picture", json={})
    assert standalone.status_code == 200
    assert standalone.headers["content-type"].startswith("image/png")
    assert is_png(standalone.content)

    xlsx = tmp_path / "hearing.xlsx"
    # 最小の xlsx ではなく空バイトでも generate は受け付ける（パース失敗時は空 pairs）
    xlsx.write_bytes(b"not-xlsx")
    start = client.post(
        "/generate",
        files={"hearing": ("hearing.xlsx", xlsx.read_bytes(), "application/vnd.ms-excel")},
        data={"username": "u", "doc_type": "sample"},
    )
    assert start.status_code == 202
    rid = start.json()["request_id"]

    st = client.get(f"/status/{rid}")
    assert st.status_code == 200
    assert st.json()["waiting_ready"] is True

    img = client.get(f"/waiting/{rid}")
    assert img.status_code == 200
    assert is_png(img.content)

    result = client.get(f"/result/{rid}")
    assert result.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result.content)) as zf:
        names = zf.namelist()
        assert f"images/{rid}_waiting.png" in names
        assert is_png(zf.read(f"images/{rid}_waiting.png"))

    missing = client.get("/waiting/nope")
    assert missing.status_code == 404
    _JOBS.pop(rid, None)
