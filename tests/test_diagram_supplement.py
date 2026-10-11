"""チャット回答の補足図。モデルは呼ばず、判定と保存だけを確認する。"""

import os
import tempfile

import pytest

from app import diagram_supplement, storage


ANSWER = "朝は起床し、洗顔して、朝食を食べてから家を出ます。"


def test_none_when_model_declines():
    assert diagram_supplement.parse_diagram_response("NONE", ANSWER) == {"status": "none"}


def test_flowchart_when_labels_are_in_the_answer():
    raw = """```mermaid
flowchart TD
  A[起床] --> B[洗顔]
  B --> C[朝食]
  C --> D[家を出ます]
```"""
    got = diagram_supplement.parse_diagram_response(raw, ANSWER)
    assert got["status"] == "ready"
    assert "flowchart TD" in got["mermaid"]
    assert "朝食" in got["mermaid"]


def test_timeline_keeps_a_paraphrase_and_drops_an_unknown_office():
    timeline = """```mermaid
timeline
    title 朝起きてから会社に着くまで
    起床 : 朝は起床し
    歩く : 駅まで歩き
    到着 : 会社に着きます
```"""
    answer = "朝は起床し、駅まで歩き、電車に乗って会社に着きます。"
    assert diagram_supplement.parse_diagram_response(timeline, answer)["status"] == "ready"

    wrong = """```mermaid
flowchart TD
  A[知事許可] --> B[労働局]
```"""
    assert diagram_supplement.parse_diagram_response(wrong, "知事許可は都道府県へ出します。") == {
        "status": "none"
    }


def test_branch_flowchart_keeps_nodes_that_paraphrase_the_answer():
    raw = """```mermaid
flowchart TD
    A[許可の判断] -->|知事許可| B[都道府県へ提出]
    A -->|大臣許可| C[地方整備局へ提出]
```"""
    answer = "知事許可は都道府県へ、大臣許可は地方整備局へ出します。"
    assert diagram_supplement.parse_diagram_response(raw, answer)["status"] == "ready"


def test_drops_diagram_when_a_label_is_not_in_the_answer():
    raw = """```mermaid
flowchart TD
  A[起床] --> B[電車に乗る]
```"""
    assert diagram_supplement.parse_diagram_response(raw, ANSWER) == {"status": "none"}


def test_state_diagram_uses_node_names_as_labels():
    raw = """```mermaid
stateDiagram-v2
    [*] --> 下書き
    下書き --> 提出済み
```"""
    got = diagram_supplement.parse_diagram_response(raw, "下書きを提出済みにします。")
    assert got["status"] == "ready"


def test_sequence_and_mindmap_and_timeline():
    sequence = """```mermaid
sequenceDiagram
  participant 本人
  本人->>窓口: 申請書
```"""
    text = "本人が窓口へ申請書を出します。"
    assert diagram_supplement.parse_diagram_response(sequence, text)["status"] == "ready"

    mind = """```mermaid
mindmap
  root((朝食))
    パン
```"""
    assert diagram_supplement.parse_diagram_response(mind, "朝食はパンです。")["status"] == "ready"

    timeline = """```mermaid
timeline
    title 朝の流れ
    section 家
    起床 : 洗顔
```"""
    got = diagram_supplement.parse_diagram_response(timeline, "朝の流れは家で起床し、洗顔します。")
    assert got["status"] == "ready"


def test_number_missing_from_the_answer_drops_the_diagram():
    raw = """```mermaid
pie
  "起床" : 50
```"""
    answer = "起床して出勤します。"
    assert diagram_supplement.parse_diagram_response(raw, answer) == {"status": "none"}


def test_existing_mermaid_in_the_answer_is_reused():
    answer = "手順です。\n```mermaid\nflowchart TD\n  A[起床] --> B[朝食]\n```\n以上です。"
    code = diagram_supplement.existing_mermaid(answer)
    assert code is not None
    assert code.startswith("flowchart TD")


def test_prose_around_the_fence_is_ignored():
    raw = "図にします。\n```mermaid\nflowchart LR\n  A[起床] --> B[朝食]\n```\n補足は不要です。"
    got = diagram_supplement.parse_diagram_response(raw, "起床して朝食を食べます。")
    assert got["status"] == "ready"
    assert got["mermaid"].startswith("flowchart LR")


@pytest.fixture
def db_path(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(storage, "DB_PATH", path)
    storage.init_db()
    yield path
    os.unlink(path)


def test_a_classification_becomes_a_mindmap_without_asking_the_model():
    answer = """はい、日本の都道府県の分類です。

**1. 地方区分による分類（最も一般的）**
*   **北海道地方:** 北海道
*   **東北地方:** 青森県、岩手県
*   **関東地方:** 東京都

**2. 昔の区分（五畿七道）による分類**
*   **五畿:** 畿内
*   **七道:** 東海道
"""
    got = diagram_supplement.list_mindmap(answer, "日本の都道府県を分類して")
    assert got is not None
    assert got.startswith("mindmap")
    assert "日本の都道府県" in got
    assert "北海道地方" in got
    assert "五畿" in got
    assert "青森県" not in got


def test_a_flat_list_becomes_a_mindmap():
    answer = """日本語の品詞は次のとおりです。
1. **名詞:** 物の名前
2. **動詞:** 動作
3. **形容詞:** 性質
"""
    got = diagram_supplement.finalize_diagram(
        {"status": "none"},
        answer,
        "日本語の品詞を教えて",
    )
    assert got["status"] == "ready"
    assert "名詞" in got["mermaid"]
    assert "動詞" in got["mermaid"]
    assert "物の名前" not in got["mermaid"]


def test_rejected_diagram_falls_back_to_the_answer_words():
    got = diagram_supplement.finalize_diagram(
        {"status": "none"},
        "知事許可は都道府県へ出します。大臣許可は地方整備局へ出します。",
        "許可の出し先は？",
    )
    assert got["status"] == "ready"
    assert "労働局" not in got["mermaid"]
    assert "都道府県" in got["mermaid"]


def test_diagram_is_cached_until_the_message_is_saved_again(db_path):
    user = "user-1"
    chat = storage.create_chat(user, "/chat", storage.DEFAULT_TENANT_ID)
    chat_id = chat["chatId"].replace("chat#", "")
    storage.create_messages(
        chat_id,
        user,
        [
            {"messageId": "user-1", "role": "user", "content": "手順は？", "usecase": "/chat"},
            {
                "messageId": "msg-1",
                "role": "assistant",
                "content": ANSWER,
                "usecase": "/chat",
                "llmType": "gpt-oss:20b",
            },
        ],
        storage.DEFAULT_TENANT_ID,
    )
    source = storage.get_assistant_answer(chat_id, user, "msg-1", storage.DEFAULT_TENANT_ID)
    assert source is not None
    assert source["userContent"] == "手順は？"
    assert source["llmType"] == "gpt-oss:20b"

    stored = storage.save_message_diagram(
        chat_id,
        user,
        "msg-1",
        {"status": "ready", "mermaid": "flowchart TD\n  A[起床] --> B[朝食]"},
    )
    assert stored["status"] == "ready"
    assert storage.get_message_diagram(chat_id, "msg-1")["mermaid"].startswith("flowchart")

    with storage._lock, storage._connect() as conn:
        conn.execute(
            "UPDATE message_diagrams SET revision = '' WHERE messageId = ?",
            ("msg-1",),
        )
    assert storage.get_message_diagram(chat_id, "msg-1") is None
    storage.save_message_diagram(
        chat_id,
        user,
        "msg-1",
        {"status": "ready", "mermaid": "flowchart TD\n  A[起床] --> B[朝食]"},
    )

    storage.create_messages(
        chat_id,
        user,
        [
            {
                "messageId": "msg-1",
                "role": "assistant",
                "content": "書き直した回答",
                "usecase": "/chat",
                "createdDate": source["createdDate"],
            }
        ],
        storage.DEFAULT_TENANT_ID,
    )
    assert storage.get_message_diagram(chat_id, "msg-1") is None

    storage.save_message_diagram(chat_id, user, "msg-1", {"status": "none"})
    storage.delete_chat(chat_id, user, storage.DEFAULT_TENANT_ID)
    assert storage.get_message_diagram(chat_id, "msg-1") is None
