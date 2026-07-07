from __future__ import annotations

from conftest import load_service_module


def test_keys_from_artifacts_prefers_object_key() -> None:
    objstore = load_service_module("backend/app/objstore.py")
    artifacts = [
        {
            "file_url": "http://localhost:8333/open-genai/exapp/hash/uuid/a.pdf",
            "object_key": "exapp/hash/uuid/a.pdf",
        }
    ]
    assert objstore.keys_from_artifacts(artifacts) == ["exapp/hash/uuid/a.pdf"]


def test_keys_from_artifacts_parses_managed_file_url() -> None:
    objstore = load_service_module("backend/app/objstore.py")
    artifacts = [
        {
            "file_url": (
                "http://localhost:8333/open-genai/exapp/258d8dc916db8cea2cafb6c3cd0cb024/"
                "d79d66da703f4807924be6285fbd65db/output_1.pdf?X-Amz-Signature=abc"
            )
        }
    ]
    assert objstore.keys_from_artifacts(artifacts) == [
        "exapp/258d8dc916db8cea2cafb6c3cd0cb024/d79d66da703f4807924be6285fbd65db/output_1.pdf"
    ]


def test_keys_from_artifacts_ignores_external_urls() -> None:
    objstore = load_service_module("backend/app/objstore.py")
    artifacts = [{"file_url": "https://upload.dify.ai/files/tools/test.bin"}]
    assert objstore.keys_from_artifacts(artifacts) == []


def test_is_managed_key_rejects_path_traversal() -> None:
    objstore = load_service_module("backend/app/objstore.py")
    assert not objstore._is_managed_key("exapp/../secret.txt")
