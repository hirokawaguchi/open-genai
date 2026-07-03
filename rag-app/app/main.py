"""ローカル RAG「AI アプリ」マイクロサービス。

源内 の「行政実務用 AI アプリ」プロトコル（同期形式）に準拠する:
- リクエスト: { "inputs": { "question": str, "top_k"?: int, "files"?: [...] } }
- レスポンス: { "outputs": "<Markdown テキスト>" }

埋め込みは Ollama の mxbai-embed-large、ベクトル DB は Qdrant、
回答生成も Ollama（既定 gpt-oss:20b）を利用する。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from shared.docextract import extract_doc_text

from . import embeddings, intauth, urlfetch, urlstore, vectorstore

# URL 自動更新の間隔（秒）。既定 1 日。
URL_REFRESH_INTERVAL = int(os.environ.get("URL_REFRESH_INTERVAL", str(24 * 3600)))

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")

# ナレッジのスコープ（既定 = 共通チーム）。backend が x-scope ヘッダで teamId を渡す。
DEFAULT_SCOPE = os.environ.get(
    "RAG_DEFAULT_SCOPE", "00000000-0000-0000-0000-000000000000"
)

# チャンク内容から決定的な ID を生成する名前空間（重複排除に利用）
_CHUNK_NS = uuid.UUID("6f1e0c2a-9b4d-5e7a-8c3f-0a1b2c3d4e5f")


def _chunk_id(scope: str, source: str, text: str) -> str:
    # 同一(スコープ+ドキュメント+本文)のチャンクは同じ ID になり、upsert で上書き＝重複排除
    # （タグは同一ドキュメントの再登録で更新されるため ID には含めない）
    return str(uuid.uuid5(_CHUNK_NS, f"{scope}\n{source}\n{text}"))

app = FastAPI(title="Open GENAI RAG App", version="0.1.0")


# ---------------------------------------------------------------------------
# テキスト分割
# ---------------------------------------------------------------------------
def chunk_text(text: str, size: int = 600, overlap: int = 80) -> list[str]:
    text = text.strip()
    if not text:
        return []
    # まず段落で大まかに分割し、長すぎるものをスライドウィンドウで分割
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    for para in paragraphs:
        if len(para) <= size:
            chunks.append(para)
            continue
        start = 0
        while start < len(para):
            chunks.append(para[start : start + size])
            start += size - overlap
    return chunks


async def ingest_documents(
    docs: list[dict[str, Any]], scope: str, tags: list[str] | None = None
) -> int:
    """docs を埋め込んで、指定スコープ(teamId 等)・タグに紐付けて Qdrant に登録。

    チャンクは (スコープ+ドキュメント+本文) の決定的 ID を持つため、再登録は
    上書きとなり重複しない（重複排除）。tags は分類用のフラットなラベル配列。
    """
    tags = [t for t in (tags or []) if t]
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs:
        text = doc.get("text", "")
        source = doc.get("source", "unknown")
        for chunk in chunk_text(text):
            cid = _chunk_id(scope, source, chunk)
            if cid in seen:
                continue  # 同一リクエスト内の重複も排除
            seen.add(cid)
            vector = await embeddings.embed(chunk)
            items.append(
                {
                    "id": cid,
                    "vector": vector,
                    "payload": {
                        "text": chunk,
                        "source": source,
                        "scope": scope,
                        "tags": tags,
                    },
                }
            )
    if not items:
        return 0
    return await vectorstore.upsert(items)


async def ingest_url(
    scope: str, url: str, tags: list[str] | None = None, *, prev_hash: str | None = None
) -> tuple[int, str, str]:
    """URL を取得して取り込む。(追加チャンク数, contentHash, title) を返す。

    変更検知のため本文ハッシュを返す。prev_hash と一致すれば再取り込みしない。
    再取り込み時は同一 URL(source) の既存チャンクを削除してから入れ直す。
    """
    text, title = await urlfetch.fetch_url(url)
    if not text.strip():
        return 0, "", title
    content_hash = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    if prev_hash and prev_hash == content_hash:
        return 0, content_hash, title  # 変更なし
    # 既存チャンクを消してから入れ直す（更新反映）
    await vectorstore.delete_by_source(url, scope)
    added = await ingest_documents([{"text": text, "source": url}], scope, tags)
    return added, content_hash, title


async def _refresh_urls(rows: list[dict[str, Any]]) -> None:
    """与えられた URL 行を再クロールし、変更があれば取り込み直す。"""
    for row in rows:
        try:
            _, content_hash, title = await ingest_url(
                row["scope"], row["url"], row.get("tags") or [],
                prev_hash=row.get("contentHash") or None,
            )
            if content_hash:
                urlstore.mark_fetched(row["scope"], row["url"], content_hash, title)
        except Exception as e:  # noqa: BLE001 - 1 件の失敗で全体を止めない
            print(f"[rag-app] URL 再取り込み失敗 {row.get('url')}: {e}")


async def _refresh_all_urls() -> None:
    """全スコープの登録 URL を再クロールする（スケジューラ用）。"""
    await _refresh_urls(urlstore.all_urls())


async def _url_refresh_loop() -> None:
    while True:
        await asyncio.sleep(URL_REFRESH_INTERVAL)
        try:
            await _refresh_all_urls()
        except Exception as e:  # noqa: BLE001
            print(f"[rag-app] URL 自動更新でエラー: {e}")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def ephemeral_search(
    question: str, docs: list[dict[str, str]], top_k: int
) -> list[dict[str, Any]]:
    """一時利用: 添付ドキュメントのみを使い、Qdrant に保存せず検索する。"""
    chunks: list[tuple[str, str]] = []  # (source, text)
    for doc in docs:
        for chunk in chunk_text(doc.get("text", "")):
            chunks.append((doc.get("source", "uploaded"), chunk))
    if not chunks:
        return []
    qvec = await embeddings.embed(question, is_query=True)
    scored: list[dict[str, Any]] = []
    for source, text in chunks:
        vec = await embeddings.embed(text)
        scored.append(
            {"score": _cosine(qvec, vec), "payload": {"text": text, "source": source}}
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# 起動時: コレクション作成 + サンプル投入
# ---------------------------------------------------------------------------
SAMPLE_DOCS = [
    {
        "source": "Open GENAI README",
        "text": (
            "Open GENAI は、デジタル庁がオープンソース公開したガバメント AI「源内 (GENAI)」を、"
            "完全ローカル環境とローカル LLM (Ollama) で動かすためのプロジェクトである。"
            "認証 (Amazon Cognito / SAML) はダミー化され、常に管理者としてログイン済みになる。"
            "LLM 呼び出しは Ollama に向き、チャット履歴は SQLite に保存される。"
        ),
    },
    {
        "source": "源内の構成",
        "text": (
            "源内は大きく2つのシステムからなる。源内 Web (genai-web) は利用者が直接操作する "
            "Web インターフェースで、AWS の GenU をベースにデジタル庁デザインシステムや "
            "チーム管理・AI アプリ管理機能を追加している。源内 AI アプリ (genai-ai-api) は "
            "RAG や法制度 AI などの行政実務用マイクロサービス群である。"
        ),
    },
]


@app.on_event("startup")
async def _startup() -> None:
    await vectorstore.ensure_collection()
    try:
        urlstore.init_db()
    except Exception as e:  # noqa: BLE001 - 起動を止めない
        print(f"[rag-app] URL DB初期化をスキップ: {e}")
    # URL 自動更新スケジューラ（6-(26)）
    try:
        asyncio.create_task(_url_refresh_loop())
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] URL 自動更新スケジューラ起動をスキップ: {e}")
    try:
        if await vectorstore.count() == 0:
            # サンプルは共通スコープにタグなしで投入
            await ingest_documents(SAMPLE_DOCS, DEFAULT_SCOPE)
    except Exception as e:  # noqa: BLE001 - 起動を止めない
        print(f"[rag-app] サンプル投入をスキップ: {e}")


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        n = await vectorstore.count()
    except Exception:  # noqa: BLE001
        n = -1
    return {"status": "ok", "chunks": n}


# ---------------------------------------------------------------------------
# 動的フォーム（/schema）: タグ/ドキュメント/URL を選択式で提示（案P）
# ---------------------------------------------------------------------------
_ACCEPT = ".pdf,.docx,.xlsx,.txt,.md,.csv,.html,.json"

# 管理系アクションの基底定義。`admin=True` は SystemAdminGroup 必須のアクション。
# ラベルの「（管理者）」注記は、権限差が意味を持つ非管理者（チーム用RAG管理を使う
# チームメンバー）にのみ付ける。システム管理者には冗長なので付けない。
_MANAGE_ACTIONS = [
    {"title": "ドキュメント一覧", "value": "list_sources"},
    {"title": "ドキュメント登録（タグ付け）", "value": "add_docs"},
    {
        "title": "ドキュメント削除",
        "value": "delete_source",
        "confirm": "選択したドキュメントをナレッジから削除します。元に戻せません。よろしいですか？",
    },
    {"title": "タグ一覧", "value": "list_tags"},
    {"title": "URL取り込み", "value": "add_url", "admin": True},
    {"title": "URL一覧", "value": "list_urls"},
    {
        "title": "URL削除",
        "value": "delete_url",
        "admin": True,
        "confirm": "選択したURLの取り込み内容を削除します。元に戻せません。よろしいですか？",
    },
    {"title": "URL再取り込み", "value": "refresh_urls", "admin": True},
    {
        "title": "ナレッジを全消去",
        "value": "clear",
        "admin": True,
        "confirm": "このナレッジを全消去します。元に戻せません。本当に実行しますか？",
    },
]


def _manage_action_items(is_admin: bool) -> list[dict[str, Any]]:
    """操作プルダウンの選択肢を作る。非管理者にのみ管理者専用アクションへ注記する。"""
    items: list[dict[str, Any]] = []
    for a in _MANAGE_ACTIONS:
        title = a["title"]
        if a.get("admin") and not is_admin:
            title += "（管理者）"
        item: dict[str, Any] = {"title": title, "value": a["value"]}
        if a.get("confirm"):
            item["confirm"] = a["confirm"]
        items.append(item)
    return items


async def _tag_items(scope: str) -> list[dict[str, str]]:
    """使用中タグを複数選択用の選択肢にする。"""
    try:
        rows = await vectorstore.list_tags(scope)
    except Exception:  # noqa: BLE001
        rows = []
    return [{"title": f"{r['tag']}（{r['chunks']}）", "value": r["tag"]} for r in rows]


async def _build_search_schema(scope: str) -> dict[str, Any]:
    tag_items = await _tag_items(scope)
    ui: dict[str, Any] = {
        "question": {
            "type": "text",
            "title": "質問",
            "required": True,
            "desc": "ナレッジへの質問を入力してください。",
        },
    }
    # タグが1つでもあれば絞り込み用の複数選択（checkbox）を出す（無ければ非表示）
    if tag_items:
        ui["tags"] = {
            "type": "checkbox",
            "title": "タグで絞り込み（任意・複数選択可）",
            "items": tag_items,
        }
    ui["top_k"] = {
        "type": "number",
        "title": "参照件数",
        "default_value": 4,
        "min": 1,
        "max": 10,
    }
    return ui


async def _build_manage_schema(scope: str, is_admin: bool = True) -> dict[str, Any]:
    try:
        srcs = await vectorstore.list_sources(scope)
    except Exception:  # noqa: BLE001
        srcs = []
    doc_items = [{"title": s["source"], "value": s["source"]} for s in srcs]
    try:
        urls = urlstore.list_urls(scope)
    except Exception:  # noqa: BLE001
        urls = []
    url_items = [{"title": (u.get("title") or u["url"]), "value": u["url"]} for u in urls]
    tag_items = await _tag_items(scope)

    # OpenGENAI Form Spec v1: action ごとに関連フィールドだけ表示する（visibleWhen）。
    ui: dict[str, Any] = {
        "action": {
            "type": "select",
            "title": "操作",
            "items": _manage_action_items(is_admin),
            "default_value": "list_sources",
        },
        "files": {
            "type": "file",
            "title": "登録するドキュメント（登録時）",
            "accept": _ACCEPT,
            "multiple": True,
            "visibleWhen": {"field": "action", "in": ["add_docs"]},
        },
        "new_tags": {
            "type": "text",
            "title": "付与するタグ（登録時・任意）",
            "desc": "分類ラベルを ; か , 区切りで（例 総務,例規）。後から付け替えも可。",
            "visibleWhen": {"field": "action", "in": ["add_docs", "add_url"]},
        },
        "new_url": {
            "type": "text",
            "title": "取り込む URL（URL取り込み時）",
            "desc": "本市ホームページ等（http/https）。取り込むと自動更新の対象になります。",
            "visibleWhen": {"field": "action", "in": ["add_url"]},
        },
    }
    # 既存タグがあれば絞り込み用の複数選択（一覧/登録時の絞り込み・付与に使用）
    if tag_items:
        ui["tags"] = {
            "type": "checkbox",
            "title": "タグで絞り込み（一覧時・任意・複数選択可）",
            "items": tag_items,
            "visibleWhen": {"field": "action", "in": ["list_sources", "add_docs", "add_url"]},
        }
    # ドキュメント/URL は既存があれば選択式、無ければ手入力にフォールバック
    _doc_base = (
        {"type": "select", "title": "ドキュメント（削除時に選択）", "items": doc_items}
        if doc_items
        else {"type": "text", "title": "ドキュメント名（削除時）"}
    )
    _doc_base["visibleWhen"] = {"field": "action", "in": ["delete_source"]}
    ui["document"] = _doc_base
    _url_base = (
        {"type": "select", "title": "URL（削除時に選択）", "items": url_items}
        if url_items
        else {"type": "text", "title": "URL（削除時）"}
    )
    _url_base["visibleWhen"] = {"field": "action", "in": ["delete_url"]}
    ui["url"] = _url_base
    return ui


@app.get("/schema")
async def schema(
    x_api_key: str | None = Header(default=None),
    x_app_config: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})
    scope = (x_scope or DEFAULT_SCOPE).strip()
    role = "manage"
    try:
        cfg = json.loads(x_app_config) if x_app_config else {}
        role = (cfg.get("rag_role") or "manage").strip()
    except (json.JSONDecodeError, TypeError):
        cfg = {}
    if role == "search":
        return {"placeholder": await _build_search_schema(scope)}
    return {"placeholder": await _build_manage_schema(scope, _is_admin(x_user_groups))}


@app.post("/clear_scope")
async def clear_scope(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
) -> Any:
    """指定スコープ(teamId 等)のナレッジを全消去する（チーム削除時に backend が呼ぶ）。"""
    err = _check_key(x_api_key)
    if err:
        return err
    body = await request.json()
    scope = (body.get("scope") or "").strip()
    if not scope:
        return {"cleared": None}
    # backend がシステム操作として scope をバインド署名する（destructive 操作の保護）
    if not intauth.verify("system", "", scope, x_user_ts, x_user_sig):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})
    await vectorstore.clear(scope)
    # ベクトルに加え、URL 登録も削除（自動更新スケジューラによる復活を防ぐ）。
    try:
        urlstore.delete_scope(scope)
    except Exception as e:  # noqa: BLE001 - ベクトル削除は成功しているため握りつぶす
        print(f"[rag-app] clear_scope: URL 登録の削除に失敗: {e}")
    return {"cleared": scope}


@app.post("/ingest")
async def ingest(request: Request, x_api_key: str | None = Header(default=None)) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err
    body = await request.json()
    docs = body.get("documents", [])
    scope = (body.get("scope") or DEFAULT_SCOPE).strip()
    tags = _parse_tags(body.get("tags"))
    added = await ingest_documents(docs, scope, tags)
    return {"added_chunks": added, "total_chunks": await vectorstore.count()}


# ---------------------------------------------------------------------------
# 源内 AI アプリ プロトコル (同期)
# ---------------------------------------------------------------------------
def _extract_uploaded_texts(inputs: dict[str, Any]) -> list[dict[str, str]]:
    """inputs.files (base64) からテキストを抽出する。

    PDF/Word/Excel/テキストに対応（共通モジュール docextract を利用）。
    """
    docs: list[dict[str, str]] = []
    for entry in inputs.get("files") or []:
        for f in entry.get("files", []):
            filename = f.get("filename", "uploaded")
            content_b64 = f.get("content", "")
            if not content_b64:
                continue
            text = extract_doc_text(filename, "", content_b64)
            if text and text.strip():
                docs.append({"text": text, "source": filename})
    return docs


async def _answer_with_hits(question: str, hits: list[dict[str, Any]]) -> str:
    """検索ヒット(共通形式 [{score, payload:{text,source}}])から回答を生成する。"""
    context_blocks = []
    sources = []
    for i, hit in enumerate(hits, start=1):
        payload = hit.get("payload", {})
        text = payload.get("text", "")
        source = payload.get("source", "unknown")
        score = hit.get("score", 0)
        context_blocks.append(f"[{i}] (ドキュメント: {source})\n{text}")
        sources.append(f"[{i}] {source} (類似度: {score:.3f})")

    context = "\n\n".join(context_blocks)
    system_prompt = (
        "あなたは行政実務を支援する RAG アシスタントです。"
        "以下の「参考情報」だけを根拠に、日本語で簡潔かつ正確に回答してください。"
        "回答中で参照した箇所には [1] のように参照番号を付けてください。"
        "参考情報に答えが無い場合は、推測せず『提供された情報では分かりません』と述べてください。"
    )
    user_prompt = f"# 参考情報\n{context}\n\n# 質問\n{question}"
    answer = await embeddings.generate(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    return f"{answer}\n\n---\n**参照ドキュメント**\n" + "\n".join(f"- {s}" for s in sources)


def _user_groups(x_user_groups: str | None) -> list[str]:
    return [g.strip() for g in (x_user_groups or "").split(",") if g.strip()]


def _is_admin(x_user_groups: str | None) -> bool:
    return "SystemAdminGroup" in set(_user_groups(x_user_groups))


def _can_manage(scope: str, is_admin: bool) -> bool:
    """自グループ(チーム)スコープの基本管理を許可するか。

    - システム管理者: 常に許可。
    - 一般利用者: 自チームスコープ（= 共有 common 以外）なら許可（backend が
      当該チームのメンバーであることを保証済み）。
    - 共有(common)ナレッジの管理は管理者のみ。
    """
    return is_admin or scope != DEFAULT_SCOPE


def _parse_tags(value: Any) -> list[str]:
    """タグ入力を正規化する。

    動的フォームの複数選択は配列で届く。手入力は ';' か ',' 区切り文字列。
    重複を除いて順序を保持する。
    """
    raw: list[str] = []
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw = [str(v) for v in value]
    else:
        raw = str(value).replace(";", ",").split(",")
    out: list[str] = []
    for chunk in raw:
        t = chunk.strip()
        if t and t not in out:
            out.append(t)
    return out


# 検索(search)ロールで許可する操作。管理系(一覧/登録/削除/URL/全消去)は禁止。
_SEARCH_ROLE_ACTIONS = {"ask"}


@app.post("/invoke")
async def invoke(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_app_config: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err
    # backend 署名の検証（x-user-groups/x-scope 偽装による権限・スコープ越えを防ぐ）
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})

    # ナレッジのスコープ（= AI アプリを所有するチーム。共通チームは共有ナレッジ）
    scope = (x_scope or DEFAULT_SCOPE).strip()

    body = await request.json()
    inputs = body.get("inputs", body)
    action = (inputs.get("action") or "ask").strip()
    top_k = int(inputs.get("top_k") or 4)
    tags = _parse_tags(inputs.get("tags"))
    is_admin = _is_admin(x_user_groups)

    # rag_role=search の検索専用アプリでは、管理系アクションを API 経由でも実行不可にする
    # （/schema だけでなく /invoke でもロールを強制し、検索/管理の分離を担保）
    try:
        cfg = json.loads(x_app_config) if x_app_config else {}
        role = (cfg.get("rag_role") or "").strip()
    except (json.JSONDecodeError, TypeError):
        role = ""
    if role == "search" and action not in _SEARCH_ROLE_ACTIONS:
        return {"outputs": "この操作は「ナレッジ管理」アプリから実行してください（検索アプリでは利用できません）。"}

    # ---- タグ一覧 ----
    if action == "list_tags":
        rows = await vectorstore.list_tags(scope)
        if not rows:
            return {"outputs": "タグはまだありません（ドキュメント登録時に付与できます）。"}
        lines = "\n".join(f"- `{r['tag']}`（{r['chunks']} チャンク）" for r in rows)
        return {"outputs": f"## タグ一覧（このチーム）\n\n{lines}"}

    # ---- ドキュメント登録（タグ付け）----
    if action == "add_docs":
        # 永続登録。一般利用者=自チーム, 共有=管理者。
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジへの登録はシステム管理者のみ実行できます。"}
        assign = _parse_tags(inputs.get("new_tags")) or tags
        docs = _extract_uploaded_texts(inputs)
        if not docs:
            return {"outputs": "登録するドキュメントを添付してください。"}
        added = await ingest_documents(docs, scope, assign)
        tag_note = f"（タグ: {', '.join(assign)}）" if assign else "（タグなし）"
        names = "、".join(d["source"] for d in docs)
        return {"outputs": f"ナレッジに登録しました{tag_note}（{added} チャンク）。\n\n- {names}"}

    # ---- URL 取り込み（6-(26)）----
    if action == "add_url":
        if not is_admin:
            return {"outputs": "URL の取り込みはシステム管理者のみ実行できます。"}
        # 取り込む URL は new_url（動的フォーム）。無ければ url を使用（後方互換）。
        url = (inputs.get("new_url") or inputs.get("url") or "").strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            return {"outputs": "http(s):// で始まる URL を指定してください。"}
        assign = _parse_tags(inputs.get("new_tags")) or tags
        try:
            added, content_hash, title = await ingest_url(scope, url, assign)
        except httpx.HTTPError as e:
            return {"outputs": f"URL の取得に失敗しました: {e}"}
        except Exception as e:  # noqa: BLE001
            return {"outputs": f"URL の取り込みでエラーが発生しました: {e}"}
        if added == 0 and not content_hash:
            return {"outputs": f"URL から本文を抽出できませんでした: {url}"}
        urlstore.add_url(scope, url, assign, title)
        urlstore.mark_fetched(scope, url, content_hash, title)
        tag_note = f"（タグ: {', '.join(assign)}）" if assign else ""
        return {
            "outputs": (
                f"URL を取り込み、自動更新の対象に登録しました{tag_note}。\n\n"
                f"- {title or url}\n- {added} チャンク登録"
            )
        }

    if action == "list_urls":
        rows = urlstore.list_urls(scope)
        if not rows:
            return {"outputs": "登録済みの URL はありません。"}
        lines = "\n".join(
            f"- {r.get('title') or r['url']}（{r['url']}"
            + (f" / タグ {', '.join(r['tags'])}" if r.get("tags") else "")
            + "）"
            for r in rows
        )
        return {"outputs": f"## 登録済み URL（このチーム）\n\n{lines}"}

    if action == "delete_url":
        if not is_admin:
            return {"outputs": "URL の削除はシステム管理者のみ実行できます。"}
        url = (inputs.get("url") or "").strip()
        if not url:
            return {"outputs": "削除する URL を指定してください。"}
        await vectorstore.delete_by_source(url, scope)
        urlstore.delete_url(scope, url)
        return {"outputs": f"URL「{url}」をナレッジと自動更新対象から削除しました。"}

    if action == "refresh_urls":
        if not is_admin:
            return {"outputs": "URL の再取り込みはシステム管理者のみ実行できます。"}
        # このチーム(scope)の登録 URL のみ再クロールする（他チームには影響しない）。
        await _refresh_urls(urlstore.scope_urls(scope))
        return {"outputs": "このチームの登録済み URL を再取り込みしました（変更分のみ更新）。"}

    # ---- 管理操作: ドキュメント一覧 / ドキュメント削除 / 全消去（スコープ＋任意タグ絞り込み）----
    if action == "list_sources":
        srcs = await vectorstore.list_sources(scope, tags or None)
        where = f"タグ {', '.join(tags)}" if tags else "このチーム"
        if not srcs:
            return {"outputs": f"{where}のナレッジは空です。"}
        lines = "\n".join(f"- {s['source']}（{s['chunks']} チャンク）" for s in srcs)
        return {"outputs": f"## 登録済みドキュメント（{where}）\n\n{lines}"}

    if action == "delete_source":
        # ドキュメント削除: 自チームは利用者可、共有は管理者のみ。
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジのドキュメント削除はシステム管理者のみ実行できます。"}
        # 削除対象は document（動的フォームの選択）。無ければ source（後方互換）。
        source = (inputs.get("document") or inputs.get("source") or "").strip()
        if not source:
            return {"outputs": "削除するドキュメントを指定してください（「ドキュメント一覧」で確認できます）。"}
        await vectorstore.delete_by_source(source, scope)
        return {"outputs": f"ドキュメント「{source}」をナレッジから削除しました。"}

    if action == "clear":
        if not is_admin:
            return {"outputs": "この操作はシステム管理者のみ実行できます。"}
        await vectorstore.clear(scope)
        # URL 登録も消す。残すと自動更新スケジューラが再クロールして復活してしまう。
        removed = urlstore.delete_scope(scope)
        note = f"（URL登録 {removed} 件も解除）" if removed else ""
        return {"outputs": f"このチームのナレッジを全消去しました{note}。"}

    # ---- 通常の質問応答 ----
    question = (inputs.get("question") or "").strip()
    if not question:
        return {"outputs": "質問が空です。質問を入力してください。"}

    store_mode = (inputs.get("store_mode") or "ephemeral").strip()
    # 永続登録は管理権限が要る（共有ナレッジは管理者のみ）。権限が無ければ一時利用に降格。
    if store_mode == "permanent" and not _can_manage(scope, is_admin):
        store_mode = "ephemeral"
    uploaded = _extract_uploaded_texts(inputs)

    try:
        if uploaded and store_mode == "ephemeral":
            # 一時利用: Qdrant に保存せず、添付ドキュメントのみから回答
            hits = await ephemeral_search(question, uploaded, top_k)
            if not hits:
                return {"outputs": "添付ドキュメントから情報を抽出できませんでした。"}
            answer = await _answer_with_hits(question, hits)
            note = "\n\n> ※ 添付ファイルはこの回答のみで使用し、ナレッジには保存していません。"
            return {"outputs": answer + note}

        # 永続: 添付があればこのチームのスコープへ取り込み（重複排除）、その後検索
        if uploaded:
            await ingest_documents(uploaded, scope, tags)
        qvec = await embeddings.embed(question, is_query=True)
        hits = await vectorstore.search(qvec, top_k, scope, tags or None)
    except Exception as e:  # noqa: BLE001
        return {"outputs": f"検索中にエラーが発生しました: {e}"}

    if not hits:
        return {
            "outputs": (
                "ナレッジに該当する情報が見つかりませんでした。"
                "ドキュメントを添付するか、知識を登録してください。"
            )
        }

    answer = await _answer_with_hits(question, hits)
    return {
        "outputs": answer,
        "_meta": {"generated_at": datetime.now(timezone.utc).isoformat()},
    }
