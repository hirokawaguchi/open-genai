from app import ocr


def test_needs_ocr_when_pages_empty():
    assert ocr.needs_ocr([])
    assert ocr.needs_ocr([{"page": 1, "text": ""}])
    assert not ocr.needs_ocr([{"page": 1, "text": "この要綱は支援を行うためのものである。"}])


def test_merge_ocr_fills_empty_pages_only():
    pages = [
        {"page": 1, "text": "デジタル本文が十分にあるページです。"},
        {"page": 2, "text": ""},
    ]
    merged = ocr.merge_ocr(pages, {2: "OCRで読んだ条文"})
    assert merged[0]["text"].startswith("デジタル")
    assert merged[0].get("ocr") is None
    assert merged[1]["text"] == "OCRで読んだ条文"
    assert merged[1]["ocr"] is True
