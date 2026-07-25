"""rag_role 別の動的フォーム定義。"""

from __future__ import annotations

from typing import Any

from . import docstore, tagstore, urlstore, vectorstore

_ACCEPT = ".pdf,.docx,.xlsx,.txt,.md,.csv,.html,.json"

ROLE_ACTIONS: dict[str, set[str]] = {
    "search": {"ask"},
    "tags": {"create_tag", "list_tags", "rename_tag", "delete_tag"},
    "register": {"add_tree_docs", "add_docs", "add_url"},
    "maintain": {
        "list_sources",
        "delete_source",
        "retag_source",
        "refresh_urls",
        "clear",
    },
    # 後方互換: 旧「管理」アプリ
    "manage": {
        "ask",
        "list_sources",
        "add_tree_docs",
        "add_docs",
        "delete_source",
        "list_tags",
        "create_tag",
        "rename_tag",
        "delete_tag",
        "add_url",
        "list_urls",
        "delete_url",
        "refresh_urls",
        "retag_source",
        "clear",
    },
}


async def _registry_tag_items(scope: str) -> list[dict[str, str]]:
    try:
        reg = {r["tag"]: 0 for r in tagstore.list_tags(scope)}
    except Exception:  # noqa: BLE001
        reg = {}
    try:
        for r in await vectorstore.list_tags(scope):
            reg[r["tag"]] = int(r.get("chunks") or 0)
    except Exception:  # noqa: BLE001
        pass
    return [
        {"title": f"{t}（{c}チャンク）" if c else t, "value": t}
        for t, c in sorted(reg.items(), key=lambda x: x[0])
    ]


async def _doc_items(scope: str, tags: list[str] | None = None) -> list[dict[str, str]]:
    try:
        srcs = await vectorstore.list_sources(scope, tags)
    except Exception:  # noqa: BLE001
        srcs = []
    seen = {s["source"] for s in srcs}
    try:
        for d in docstore.list_docs(scope, tags):
            if d["source"] not in seen:
                srcs.append(
                    {
                        "source": d["source"],
                        "chunks": 0,
                        "tags": d.get("tags") or [],
                    }
                )
                seen.add(d["source"])
    except Exception:  # noqa: BLE001
        pass
    items: list[dict[str, str]] = []
    for s in srcs:
        tag_s = ",".join(s.get("tags") or []) or "タグなし"
        items.append(
            {
                "title": f"{s['source']}（{s.get('chunks', 0)}ch / {tag_s}）",
                "value": s["source"],
            }
        )
    return items


async def build_search_schema(scope: str) -> dict[str, Any]:
    tag_items = await _registry_tag_items(scope)
    ui: dict[str, Any] = {
        "question": {
            "type": "text",
            "title": "質問",
            "required": True,
            "desc": (
                "ナレッジへの質問を入力してください。タグ未付与の資料は検索されません。"
                "検索方式は対象資料に応じて自動選択されます"
                "（全文が収まる場合は全文、構造化のみならハイブリッド、それ以外はベクトル）。"
            ),
        },
        "top_k": {
            "type": "number",
            "title": "参照件数",
            "default_value": 4,
            "min": 1,
            "max": 10,
            "desc": "ベクトル／ハイブリッド時に参照する件数です。全文モードでは文書単位で渡します。",
        },
    }
    if tag_items:
        ui["tags"] = {
            "type": "checkbox",
            "title": "タグで絞り込み（任意・複数選択可）",
            "items": tag_items,
            "desc": "未指定のときは、タグが付いた資料全体を検索します。",
        }
    return ui


async def build_tags_schema(scope: str) -> dict[str, Any]:
    tag_items = await _registry_tag_items(scope)
    ui: dict[str, Any] = {
        "action": {
            "type": "radio",
            "title": "操作",
            "items": [
                {"title": "新規作成", "value": "create_tag"},
                {"title": "一覧", "value": "list_tags"},
                {"title": "名称変更", "value": "rename_tag"},
                {
                    "title": "削除",
                    "value": "delete_tag",
                    "confirm": "未使用のタグ定義を削除します。ドキュメントからタグが消えるわけではありません。よろしいですか？",
                },
            ],
            "default_value": "create_tag",
        },
        "new_tag": {
            "type": "text",
            "title": "新しいタグ名",
            "required": True,
            "visibleWhen": {"field": "action", "in": ["create_tag"]},
        },
        "tag": {
            "type": "select" if tag_items else "text",
            "title": "対象タグ",
            **({"items": tag_items} if tag_items else {}),
            "visibleWhen": {"field": "action", "in": ["rename_tag", "delete_tag"]},
        },
        "rename_to": {
            "type": "text",
            "title": "変更後のタグ名",
            "visibleWhen": {"field": "action", "in": ["rename_tag"]},
        },
    }
    return ui


async def build_register_schema(scope: str, is_admin: bool = True) -> dict[str, Any]:
    tag_items = await _registry_tag_items(scope)
    # URL はドキュメントの一種として登録アプリに含める
    kind_items = [
        {"title": "ファイル（標準）", "value": "add_tree_docs"},
        {"title": "ファイル（簡易）", "value": "add_docs"},
        {"title": "URL", "value": "add_url"},
    ]
    _ = is_admin  # 権限差は invoke 側で見る（スキーマは共通）
    ui: dict[str, Any] = {
        "action": {
            "type": "radio",
            "title": "登録の種類",
            "items": kind_items,
            "default_value": "add_tree_docs",
            "desc": (
                "標準=ツリー＋ベクトル。"
                "簡易=全文＋ベクトル（ツリーなし）。"
                "URL=ページ取り込み（全文＋ベクトル）。"
            ),
        },
        "files": {
            "type": "file",
            "title": "登録するドキュメント",
            "accept": _ACCEPT,
            "multiple": True,
            "visibleWhen": {"field": "action", "in": ["add_docs", "add_tree_docs"]},
        },
        "new_url": {
            "type": "text",
            "title": "取り込む URL",
            "desc": "http/https。取り込むと自動更新の対象になります。",
            "visibleWhen": {"field": "action", "in": ["add_url"]},
        },
        "new_tags": {
            "type": "text",
            "title": "付与するタグ（任意・新規可）",
            "desc": "; か , 区切り（例 総務,例規）。未登録名はその場でタグ作成されます。"
            "タグ未付与の資料は登録できますが、検索対象外になります。",
        },
    }
    if tag_items:
        ui["tags"] = {
            "type": "checkbox",
            "title": "既存タグから選択（任意・複数可）",
            "items": tag_items,
            "desc": "上のテキストと合わせて付与します（どちらも任意）。",
        }
    return ui


async def build_maintain_schema(scope: str, is_admin: bool = True) -> dict[str, Any]:
    tag_items = await _registry_tag_items(scope)
    # 絞り込み用に「タグなし」擬似値
    filter_items = [{"title": "（タグなし）", "value": "__untagged__"}] + tag_items
    doc_items = await _doc_items(scope)
    action_items: list[dict[str, Any]] = [
        {"title": "一覧", "value": "list_sources"},
        {
            "title": "削除",
            "value": "delete_source",
            "confirm": "選択したドキュメントをナレッジから削除します。元に戻せません。よろしいですか？",
        },
        {"title": "タグ付け替え", "value": "retag_source"},
    ]
    if is_admin:
        action_items.append(
            {"title": "URL再取り込み", "value": "refresh_urls", "admin": True}
        )
        action_items.append(
            {
                "title": "ナレッジを全消去",
                "value": "clear",
                "confirm": "このナレッジを全消去します。元に戻せません。本当に実行しますか？",
            }
        )
    ui: dict[str, Any] = {
        "action": {
            "type": "radio",
            "title": "操作",
            "items": action_items,
            "default_value": "list_sources",
        },
        "filter_tags": {
            "type": "checkbox",
            "title": "タグで絞り込み（任意）",
            "items": filter_items,
            "visibleWhen": {
                "field": "action",
                "in": ["list_sources", "delete_source", "retag_source"],
            },
        },
        "document": (
            {
                "type": "select",
                "title": "対象ドキュメント",
                "items": doc_items,
                "visibleWhen": {
                    "field": "action",
                    "in": ["delete_source", "retag_source"],
                },
            }
            if doc_items
            else {
                "type": "text",
                "title": "対象ドキュメント名",
                "visibleWhen": {
                    "field": "action",
                    "in": ["delete_source", "retag_source"],
                },
            }
        ),
        "new_tags": {
            "type": "text",
            "title": "付け替えるタグ（必須）",
            "desc": "; か , 区切り。既存のタグは置き換えられます。",
            "visibleWhen": {"field": "action", "in": ["retag_source"]},
        },
    }
    if tag_items:
        ui["tags"] = {
            "type": "checkbox",
            "title": "付け替えるタグ（既存から選択）",
            "items": tag_items,
            "visibleWhen": {"field": "action", "in": ["retag_source"]},
        }
    return ui


async def build_manage_schema(scope: str, is_admin: bool = True) -> dict[str, Any]:
    """旧 manage ロール向け（移行期間の後方互換）。登録＋整備＋タグを統合。"""
    # シンプルに整備スキーマをベースに登録項目を足す
    ui = await build_maintain_schema(scope, is_admin)
    reg = await build_register_schema(scope, is_admin)
    # action に登録系を追加
    items = list(ui["action"]["items"])
    items = [
        {"title": "ドキュメント登録（標準）", "value": "add_tree_docs"},
        {"title": "ドキュメント登録（簡易）", "value": "add_docs"},
        {"title": "URL登録", "value": "add_url"},
        {"title": "タグ作成", "value": "create_tag"},
        {"title": "タグ一覧", "value": "list_tags"},
    ] + items
    ui["action"]["items"] = items
    ui["files"] = reg["files"]
    ui["new_url"] = reg["new_url"]
    ui["new_tag"] = {
        "type": "text",
        "title": "新しいタグ名",
        "visibleWhen": {"field": "action", "in": ["create_tag"]},
    }
    if "new_tags" in reg:
        ui["reg_tags"] = {
            **reg["new_tags"],
            "visibleWhen": {
                "field": "action",
                "in": ["add_docs", "add_tree_docs", "add_url"],
            },
        }
    return ui
