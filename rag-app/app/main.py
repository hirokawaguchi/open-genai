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

from shared.docextract import DocExtractError, extract_doc_text

from . import (
    docstore,
    embeddings,
    intauth,
    rag_schema,
    retrieve,
    tagstore,
    tree_ingest,
    urlfetch,
    urlstore,
    vectorstore,
)

# URL 自動更新の間隔（秒）。既定 1 日。
URL_REFRESH_INTERVAL = int(os.environ.get("URL_REFRESH_INTERVAL", str(24 * 3600)))

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")

# ナレッジのスコープ（既定 = 共通チーム）。backend が x-scope ヘッダで teamId を渡す。
DEFAULT_SCOPE = os.environ.get(
    "RAG_DEFAULT_SCOPE", "00000000-0000-0000-0000-000000000000"
)
# 旧「ナレッジ管理（管理者）」が ADMIN_TEAM スコープへ誤登録していた分の移行元。
# backend の ADMIN_TEAM_ID と同一。環境変数で上書き可能。
LEGACY_ADMIN_SCOPE = os.environ.get(
    "RAG_LEGACY_ADMIN_SCOPE", "00000000-0000-0000-0000-0000000000a1"
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
    """docs を全文保存＋埋め込みして登録する。

    全文は docstore（index_kind=fulltext）へ、チャンクは Qdrant へ保存する。
    チャンク ID は決定的なため再登録は上書き（重複排除）。
    """
    tags = [t for t in (tags or []) if t]
    total = 0
    for doc in docs:
        text = (doc.get("text") or "").strip()
        source = doc.get("source") or "unknown"
        if not text:
            continue
        info = await tree_ingest.ingest_fulltext_text(
            scope=scope,
            source=source,
            text=text,
            tags=tags,
            also_vector=True,
        )
        total += int(info.get("vector_chunks") or 0)
    return total


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
    info = await tree_ingest.ingest_fulltext_text(
        scope=scope,
        source=url,
        text=text,
        tags=tags,
        also_vector=True,
    )
    return int(info.get("vector_chunks") or 0), content_hash, title


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


async def _migrate_tags_into_registry() -> None:
    """既存データのタグをレジストリへ upsert する。"""
    # 共通＋判明しているスコープを走査するのは重いので、
    # URL レジストリと構造化 docs の scope 一覧＋ベクトルのサンプル投入分を対象にする。
    scopes: set[str] = {DEFAULT_SCOPE}
    try:
        for row in urlstore.all_urls():
            scopes.add(row["scope"])
            tagstore.ensure_tags(row["scope"], row.get("tags") or [])
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] URL タグ移行警告: {e}")
    try:
        # docstore に scope 一覧 API は無いので DEFAULT と URL 由来のみ＋ベクトル tags
        for scope in list(scopes):
            for r in await vectorstore.list_tags(scope):
                tagstore.ensure_tags(scope, [r["tag"]])
            for d in docstore.list_docs(scope):
                tagstore.ensure_tags(scope, d.get("tags") or [])
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] ベクトル/構造化タグ移行警告: {e}")


async def _migrate_tag_unicode_nfc() -> None:
    """タグ名を Unicode NFC に揃える（LLM が NFC で渡しても照合できるようにする）。"""
    from . import textnorm

    renamed = 0
    # 1) タグレジストリ
    try:
        with tagstore._connect() as conn:  # noqa: SLF001 - 移行専用
            rows = list(conn.execute("SELECT scope, tag FROM tags"))
            for scope, tag in rows:
                nfc = textnorm.normalize_tag(tag)
                if not nfc or nfc == tag:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM tags WHERE scope = ? AND tag = ?",
                    (scope, nfc),
                ).fetchone()
                if exists:
                    conn.execute(
                        "DELETE FROM tags WHERE scope = ? AND tag = ?",
                        (scope, tag),
                    )
                else:
                    conn.execute(
                        "UPDATE tags SET tag = ? WHERE scope = ? AND tag = ?",
                        (nfc, scope, tag),
                    )
                renamed += 1
                try:
                    await vectorstore.rename_tag_in_payloads(scope, tag, nfc)
                except Exception as e:  # noqa: BLE001
                    print(f"[rag-app] Qdrant タグ NFC 移行警告 ({scope}/{tag}): {e}")
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] タグレジストリ NFC 移行警告: {e}")

    # 2) 構造化 docs.tags JSON
    try:
        import json

        with docstore._connect() as conn:  # noqa: SLF001 - 移行専用
            rows = list(conn.execute("SELECT doc_id, tags FROM docs"))
            for doc_id, raw in rows:
                try:
                    cur = json.loads(raw or "[]")
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(cur, list):
                    continue
                nxt = textnorm.normalize_tags(str(t) for t in cur)
                if nxt == [str(t).strip() for t in cur if str(t).strip()] and all(
                    textnorm.normalize_tag(str(t)) == str(t).strip() for t in cur if str(t).strip()
                ):
                    continue
                if json.dumps(nxt, ensure_ascii=False) == (raw or "[]"):
                    continue
                conn.execute(
                    "UPDATE docs SET tags = ? WHERE doc_id = ?",
                    (json.dumps(nxt, ensure_ascii=False), doc_id),
                )
                renamed += 1
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] docs タグ NFC 移行警告: {e}")

    if renamed:
        print(f"[rag-app] タグ Unicode NFC 移行: {renamed} 件更新")


@app.on_event("startup")
async def _startup() -> None:
    await vectorstore.ensure_collection()
    try:
        urlstore.init_db()
    except Exception as e:  # noqa: BLE001 - 起動を止めない
        print(f"[rag-app] URL DB初期化をスキップ: {e}")
    try:
        docstore.init_db()
    except Exception as e:  # noqa: BLE001 - 起動を止めない
        print(f"[rag-app] 構造化ドキュメント DB初期化をスキップ: {e}")
    try:
        tagstore.init_db()
    except Exception as e:  # noqa: BLE001 - 起動を止めない
        print(f"[rag-app] タグレジストリ DB初期化をスキップ: {e}")
    # 既存チャンク／構造化／URL からタグレジストリを埋める（冪等）
    try:
        await _migrate_tags_into_registry()
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] タグ移行をスキップ: {e}")
    try:
        await _migrate_tag_unicode_nfc()
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] タグ NFC 移行をスキップ: {e}")
    # 旧 rag-manage(ADMIN_TEAM scope) → 共有ナレッジ(COMMON) への一度きり移行
    try:
        moved = await vectorstore.reassign_scope(LEGACY_ADMIN_SCOPE, DEFAULT_SCOPE)
        if moved:
            print(
                f"[rag-app] 共有ナレッジのスコープを移行: "
                f"{LEGACY_ADMIN_SCOPE} → {DEFAULT_SCOPE}（{moved} チャンク）"
            )
        url_moved = urlstore.reassign_scope(LEGACY_ADMIN_SCOPE, DEFAULT_SCOPE)
        if url_moved:
            print(
                f"[rag-app] URL 登録のスコープを移行: "
                f"{LEGACY_ADMIN_SCOPE} → {DEFAULT_SCOPE}（{url_moved} 件）"
            )
    except Exception as e:  # noqa: BLE001 - 起動を止めない
        print(f"[rag-app] 旧管理スコープ移行をスキップ: {e}")
    # URL 自動更新スケジューラ（6-(26)）
    try:
        asyncio.create_task(_url_refresh_loop())
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] URL 自動更新スケジューラ起動をスキップ: {e}")
    # RAG_SEED_SAMPLES=false で起動時のサンプル自動投入を無効化できる（本番想定）。
    seed_samples = os.environ.get("RAG_SEED_SAMPLES", "true").lower() != "false"
    try:
        if seed_samples and await vectorstore.count() == 0:
            # サンプルは共通スコープにタグ付きで投入（タグなしは検索対象外のため）
            tagstore.ensure_tags(DEFAULT_SCOPE, ["サンプル"])
            await ingest_documents(SAMPLE_DOCS, DEFAULT_SCOPE, ["サンプル"])
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
    try:
        # scope 横断の件数は持たないため、ヘルスでは DB 初期化可否のみ見る
        docstore.init_db()
        tree_ok = True
    except Exception:  # noqa: BLE001
        tree_ok = False
    return {"status": "ok", "chunks": n, "tree_store": tree_ok}


# ---------------------------------------------------------------------------
# 動的フォーム（/schema）: rag_role 別に分割
# ---------------------------------------------------------------------------
async def _build_schema_for_role(
    role: str, scope: str, is_admin: bool
) -> dict[str, Any]:
    if role == "search":
        return await rag_schema.build_search_schema(scope)
    if role == "tags":
        return await rag_schema.build_tags_schema(scope)
    if role == "register":
        return await rag_schema.build_register_schema(scope, is_admin)
    if role == "maintain":
        return await rag_schema.build_maintain_schema(scope, is_admin)
    # manage / 未指定: 後方互換の統合管理
    return await rag_schema.build_manage_schema(scope, is_admin)


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
    return {
        "placeholder": await _build_schema_for_role(
            role, scope, _is_admin(x_user_groups)
        )
    }


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
    try:
        docstore.delete_scope(scope)
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] clear_scope: 構造化索引の削除に失敗: {e}")
    try:
        tagstore.delete_scope(scope)
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] clear_scope: タグレジストリの削除に失敗: {e}")
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
# 機械向け Retrieval API（Dify / 他クライアント用）
# ---------------------------------------------------------------------------
def _auth_scoped(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
) -> tuple[str | None, JSONResponse | None]:
    """API キー + 内部署名を検証し scope を返す。"""
    err = _check_key(x_api_key)
    if err:
        return None, err
    if not intauth.verify(
        x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    ):
        return None, JSONResponse(
            status_code=401, content={"error": "invalid internal signature"}
        )
    return (x_scope or DEFAULT_SCOPE).strip(), None


def _auth_read(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
    *,
    scope_query: str | None = None,
) -> tuple[str | None, JSONResponse | None]:
    """読み取り用認証。署名ありは検証、無しは機械クライアント（APIキー＋scope）。"""
    err = _check_key(x_api_key)
    if err:
        return None, err
    if (x_user_sig or "").strip():
        return _auth_scoped(
            x_api_key,
            x_user_id,
            x_user_groups,
            x_scope,
            x_user_ts,
            x_user_sig,
            x_user_tags,
        )
    scope = (scope_query or x_scope or DEFAULT_SCOPE).strip()
    return scope, None


@app.get("/knowledge/tags")
async def api_list_tags(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    scope: str | None = None,
) -> Any:
    """スコープ内タグ一覧（レジストリ＋使用中チャンク数）。

    機械クライアント（Dify / MCP）: API キーのみ。scope はクエリまたは x-scope。
    """
    resolved, err = _auth_read(
        x_api_key,
        x_user_id,
        x_user_groups,
        x_scope,
        x_user_ts,
        x_user_sig,
        x_user_tags,
        scope_query=scope,
    )
    if err:
        return err
    from . import textnorm

    reg = {
        textnorm.normalize_tag(r["tag"]): r
        for r in tagstore.list_tags(resolved)  # type: ignore[arg-type]
        if textnorm.normalize_tag(r["tag"])
    }
    used: dict[str, int] = {}
    for r in await vectorstore.list_tags(resolved):  # type: ignore[arg-type]
        name = textnorm.normalize_tag(r["tag"])
        if not name:
            continue
        used[name] = used.get(name, 0) + int(r.get("chunks") or 0)
    names = sorted(set(reg) | set(used))
    tags_out = [
        {"tag": name, "chunks": int(used.get(name, 0))} for name in names
    ]
    return {"scope": resolved, "tags": tags_out}


@app.get("/knowledge/docs")
async def api_list_docs(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    tags: str | None = None,
    scope: str | None = None,
) -> Any:
    """文書一覧。機械クライアントは API キーのみ（scope クエリまたは x-scope）。"""
    resolved, err = _auth_read(
        x_api_key,
        x_user_id,
        x_user_groups,
        x_scope,
        x_user_ts,
        x_user_sig,
        x_user_tags,
        scope_query=scope,
    )
    if err:
        return err
    tag_list = _parse_tags(tags) if tags else None
    return {
        "scope": resolved,
        "documents": docstore.list_docs(resolved, tag_list),  # type: ignore[arg-type]
    }


@app.get("/knowledge/docs/{doc_id}/toc")
async def api_get_toc(
    doc_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Any:
    scope, err = _auth_scoped(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    doc = docstore.get_doc(doc_id, scope)  # type: ignore[arg-type]
    if not doc:
        return JSONResponse(status_code=404, content={"error": "document not found"})
    return {"doc_id": doc_id, "source": doc["source"], "nodes": docstore.get_toc(doc_id)}


@app.post("/knowledge/docs/{doc_id}/nodes")
async def api_get_nodes(
    doc_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Any:
    scope, err = _auth_scoped(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    doc = docstore.get_doc(doc_id, scope)  # type: ignore[arg-type]
    if not doc:
        return JSONResponse(status_code=404, content={"error": "document not found"})
    body = await request.json()
    node_ids = body.get("node_ids") or []
    if not isinstance(node_ids, list) or not node_ids:
        return JSONResponse(status_code=400, content={"error": "node_ids required"})
    nodes = docstore.get_nodes_with_text(doc_id, [str(x) for x in node_ids])
    return {"doc_id": doc_id, "source": doc["source"], "nodes": nodes}


@app.post("/retrieve")
async def api_retrieve(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Any:
    """共通 Retrieval API。mode=auto|full|vector|tree|hybrid。

    認証:
    - backend 経由: API キー + 内部署名（x-user-*）
    - Dify 等の機械クライアント: API キーのみ（署名ヘッダなし）。
      scope は JSON body.scope または x-scope（未指定時は既定スコープ）
    """
    err = _check_key(x_api_key)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}

    if (x_user_sig or "").strip():
        scope, auth_err = _auth_scoped(
            x_api_key,
            x_user_id,
            x_user_groups,
            x_scope,
            x_user_ts,
            x_user_sig,
            x_user_tags,
        )
        if auth_err:
            return auth_err
    else:
        # 機械クライアント: 署名なしでも API キーがあれば許可
        scope = (body.get("scope") or x_scope or DEFAULT_SCOPE).strip()

    question = (body.get("question") or body.get("query") or "").strip()
    if not question:
        return JSONResponse(status_code=400, content={"error": "question required"})
    mode = (body.get("mode") or "auto").strip().lower()
    top_k = int(body.get("top_k") or 4)
    tags = _parse_tags(body.get("tags"))
    try:
        result = await retrieve.retrieve(
            question,
            scope,  # type: ignore[arg-type]
            mode=mode,
            top_k=top_k,
            tags=tags or None,
            doc_id=(body.get("doc_id") or "").strip() or None,
            source=(body.get("source") or "").strip() or None,
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})
    return result


@app.post("/ingest_tree")
async def api_ingest_tree(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> Any:
    """構造化取込（内部／CLI 向け）。files: [{filename, content(base64), media_type?}]"""
    err = _check_key(x_api_key)
    if err:
        return err
    body = await request.json()
    scope = (body.get("scope") or DEFAULT_SCOPE).strip()
    tags = _parse_tags(body.get("tags"))
    if tags:
        tagstore.ensure_tags(scope, tags)
    also_vector = bool(body.get("also_vector", True))
    files = body.get("files") or []
    if not files:
        return JSONResponse(status_code=400, content={"error": "files required"})
    results: list[dict[str, Any]] = []
    for f in files:
        try:
            info = await tree_ingest.ingest_structured_file(
                scope=scope,
                filename=f.get("filename") or "uploaded",
                media_type=f.get("media_type") or "",
                content_b64=f.get("content") or "",
                tags=tags,
                also_vector=also_vector,
            )
            results.append(info)
        except DocExtractError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
    return {"documents": results}


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


def _iter_uploaded_files(inputs: dict[str, Any]) -> list[dict[str, str]]:
    """inputs.files から {filename, content, media_type} を列挙する。"""
    out: list[dict[str, str]] = []
    for entry in inputs.get("files") or []:
        for f in entry.get("files", []):
            content_b64 = f.get("content", "")
            if not content_b64:
                continue
            out.append(
                {
                    "filename": f.get("filename", "uploaded"),
                    "content": content_b64,
                    "media_type": f.get("media_type") or f.get("type") or "",
                }
            )
    return out


# フロントの出典アコーディオン用。画像 base64(content) と区別する。
CITATION_MIME = "text/x.open-genai.citation"


async def _answer_with_hits(question: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    """検索ヒットから回答と出典 artifacts を生成する。

    戻り値: {"outputs": str, "artifacts": list}
    artifacts は mime_type=CITATION_MIME の引用。フロントがアコーディオン表示する。
    """
    context_blocks = []
    artifacts: list[dict[str, Any]] = []
    for i, hit in enumerate(hits, start=1):
        payload = hit.get("payload", {})
        text = payload.get("text", "")
        source = payload.get("source", "unknown")
        score = float(hit.get("score", 0) or 0)
        context_blocks.append(f"[{i}] (ドキュメント: {source})\n{text}")
        artifacts.append(
            {
                "display_name": f"[{i}] {source}（類似度: {score:.3f}）",
                "mime_type": CITATION_MIME,
                "text": text,
            }
        )

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
    return {
        "outputs": f"{answer}\n\n---\n**参照ドキュメント**",
        "artifacts": artifacts,
    }


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
    Unicode NFC + strip、重複を除いて順序を保持する。
    """
    from . import textnorm

    raw: list[str] = []
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw = [str(v) for v in value]
    else:
        raw = str(value).replace(";", ",").split(",")
    return textnorm.normalize_tags(raw)


def _resolve_assign_tags(inputs: dict[str, Any]) -> list[str]:
    """登録・付け替え用タグ（checkbox + テキスト）を合流する。"""
    assign = _parse_tags(inputs.get("new_tags")) or []
    for t in _parse_tags(inputs.get("tags")):
        if t not in assign:
            assign.append(t)
    for t in _parse_tags(inputs.get("reg_tags")):
        if t not in assign:
            assign.append(t)
    return assign


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

    try:
        cfg = json.loads(x_app_config) if x_app_config else {}
        role = (cfg.get("rag_role") or "manage").strip()
    except (json.JSONDecodeError, TypeError):
        role = "manage"

    allowed = rag_schema.ROLE_ACTIONS.get(role) or rag_schema.ROLE_ACTIONS["manage"]
    if action not in allowed:
        return {
            "outputs": (
                f"この操作（{action}）は現在のアプリ（role={role}）では実行できません。"
                "タグ管理／ドキュメント登録／ドキュメント管理／ナレッジ検索を使い分けてください。"
            )
        }

    # ---- タグ操作 ----
    if action == "create_tag":
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジのタグ作成はシステム管理者のみ実行できます。"}
        try:
            name = tagstore.create_tag(scope, (inputs.get("new_tag") or "").strip())
        except ValueError as e:
            return {"outputs": str(e)}
        return {"outputs": f"タグ「{name}」を作成しました。"}

    if action == "list_tags":
        reg = {r["tag"]: r for r in tagstore.list_tags(scope)}
        used = {r["tag"]: r["chunks"] for r in await vectorstore.list_tags(scope)}
        all_names = sorted(set(reg) | set(used))
        if not all_names:
            return {"outputs": "タグはまだありません。「タグ管理」で新規作成するか、登録時に付与してください。"}
        lines = []
        for name in all_names:
            ch = used.get(name, 0)
            empty = "（空・未使用）" if ch == 0 else f"（{ch} チャンク）"
            lines.append(f"- `{name}` {empty}")
        return {"outputs": "## タグ一覧\n\n" + "\n".join(lines)}

    if action == "rename_tag":
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジのタグ変更はシステム管理者のみ実行できます。"}
        old = (inputs.get("tag") or "").strip()
        new = (inputs.get("rename_to") or "").strip()
        try:
            tagstore.rename_tag(scope, old, new)
        except ValueError as e:
            return {"outputs": str(e)}
        n_vec = await vectorstore.rename_tag_in_payloads(scope, old, new)
        n_doc = docstore.rename_tag(scope, old, new)
        n_url = urlstore.rename_tag(scope, old, new)
        return {
            "outputs": (
                f"タグ「{old}」を「{new}」に変更しました"
                f"（ベクトル {n_vec} / 構造化 {n_doc} / URL {n_url}）。"
            )
        }

    if action == "delete_tag":
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジのタグ削除はシステム管理者のみ実行できます。"}
        name = (inputs.get("tag") or "").strip()
        used = {r["tag"]: r["chunks"] for r in await vectorstore.list_tags(scope)}
        if used.get(name, 0) > 0:
            return {
                "outputs": (
                    f"タグ「{name}」はドキュメントに付与されているため削除できません。"
                    "先に「ドキュメント管理」でタグ付け替えしてください。"
                )
            }
        try:
            tagstore.delete_tag(scope, name)
        except ValueError as e:
            return {"outputs": str(e)}
        return {"outputs": f"タグ「{name}」を削除しました。"}

    # ---- ドキュメント登録（簡易）: 全文 + ベクトル（ツリーなし）----
    if action == "add_docs":
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジへの登録はシステム管理者のみ実行できます。"}
        assign = _resolve_assign_tags(inputs)
        if assign:
            tagstore.ensure_tags(scope, assign)
        files = _iter_uploaded_files(inputs)
        if not files:
            return {"outputs": "登録するドキュメントを添付してください。"}
        lines: list[str] = []
        total_chunks = 0
        for f in files:
            try:
                info = await tree_ingest.ingest_fulltext_file(
                    scope=scope,
                    filename=f["filename"],
                    media_type=f.get("media_type") or "",
                    content_b64=f["content"],
                    tags=assign,
                    also_vector=True,
                )
            except DocExtractError as e:
                return {"outputs": f"ドキュメント登録（簡易）に失敗しました: {e}"}
            except Exception as e:  # noqa: BLE001
                return {"outputs": f"ドキュメント登録（簡易）でエラーが発生しました: {e}"}
            total_chunks += int(info.get("vector_chunks") or 0)
            lines.append(
                f"- {info['source']}（doc_id=`{info['doc_id']}`, "
                f"{info['page_count']}ページ / {info['char_count']}文字 / "
                f"ベクトル {info['vector_chunks']}チャンク）"
            )
        tag_note = f"タグ: {', '.join(assign)}" if assign else "タグなし（検索対象外）"
        return {
            "outputs": (
                f"ナレッジに登録しました（簡易・全文＋ベクトル）"
                f"（{tag_note} / 合計 {total_chunks} チャンク）。\n\n"
                + "\n".join(lines)
            )
        }

    # ---- ドキュメント登録（標準）: ツリー索引 + ベクトル併用 ----
    if action == "add_tree_docs":
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジへの登録はシステム管理者のみ実行できます。"}
        assign = _resolve_assign_tags(inputs)
        if assign:
            tagstore.ensure_tags(scope, assign)
        files = _iter_uploaded_files(inputs)
        if not files:
            return {"outputs": "登録するドキュメントを添付してください。"}
        lines: list[str] = []
        for f in files:
            try:
                info = await tree_ingest.ingest_structured_file(
                    scope=scope,
                    filename=f["filename"],
                    media_type=f.get("media_type") or "",
                    content_b64=f["content"],
                    tags=assign,
                    also_vector=True,
                )
            except DocExtractError as e:
                return {"outputs": f"ドキュメント登録（標準）に失敗しました: {e}"}
            except Exception as e:  # noqa: BLE001
                return {"outputs": f"ドキュメント登録（標準）でエラーが発生しました: {e}"}
            lines.append(
                f"- {info['source']}（doc_id=`{info['doc_id']}`, "
                f"{info['page_count']}ページ / {info['node_count']}ノード / "
                f"ベクトル {info['vector_chunks']}チャンク）"
            )
        tag_note = f"タグ: {', '.join(assign)}" if assign else "タグなし（検索対象外）"
        return {
            "outputs": (
                f"ナレッジに登録しました（標準・ツリー＋ベクトル）"
                f"（{tag_note}）。\n\n" + "\n".join(lines)
            )
        }

    # ---- URL 取り込み（ドキュメントの一種）----
    if action == "add_url":
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジへの URL 登録はシステム管理者のみ実行できます。"}
        url = (inputs.get("new_url") or inputs.get("url") or "").strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            return {"outputs": "http(s):// で始まる URL を指定してください。"}
        assign = _resolve_assign_tags(inputs)
        if assign:
            tagstore.ensure_tags(scope, assign)
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
        tag_note = f"タグ: {', '.join(assign)}" if assign else "タグなし（検索対象外）"
        return {
            "outputs": (
                f"URL を登録しました（{tag_note}）。\n\n"
                f"- {title or url}\n- {added} チャンク登録"
            )
        }

    if action == "list_urls":
        rows = urlstore.list_urls(scope)
        if not rows:
            return {"outputs": "登録済みの URL はありません。"}
        lines = "\n".join(
            f"- {r.get('title') or r['url']}（{r['url']}"
            + (f" / タグ {', '.join(r['tags'])}" if r.get("tags") else " / タグなし")
            + "）"
            for r in rows
        )
        return {"outputs": f"## 登録済み URL\n\n{lines}"}

    if action == "delete_url":
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジの URL 削除はシステム管理者のみ実行できます。"}
        url = (inputs.get("url") or inputs.get("document") or "").strip()
        if not url:
            return {"outputs": "削除する URL を指定してください。"}
        await vectorstore.delete_by_source(url, scope)
        try:
            docstore.delete_by_source(scope, url)
        except Exception as e:  # noqa: BLE001
            print(f"[rag-app] delete_url: 構造化索引の削除に失敗: {e}")
        urlstore.delete_url(scope, url)
        return {"outputs": f"URL「{url}」をナレッジから削除しました。"}

    if action == "refresh_urls":
        if not is_admin:
            return {"outputs": "URL の再取り込みはシステム管理者のみ実行できます。"}
        await _refresh_urls(urlstore.scope_urls(scope))
        return {"outputs": "このチームの登録済み URL を再取り込みしました（変更分のみ更新）。"}

    # ---- ドキュメント管理 ----
    if action == "list_sources":
        filter_tags = _parse_tags(inputs.get("filter_tags"))
        want_untagged = "__untagged__" in filter_tags
        real_filters = [t for t in filter_tags if t != "__untagged__"]
        srcs = await vectorstore.list_sources(
            scope, real_filters or None
        )
        tree_docs = docstore.list_docs(scope, real_filters or None)
        urls = urlstore.list_urls(scope)

        def _match_tags(doc_tags: list[str]) -> bool:
            if not filter_tags:
                return True
            if want_untagged and not doc_tags:
                return True
            if real_filters and any(t in doc_tags for t in real_filters):
                return True
            return False

        srcs = [s for s in srcs if _match_tags(s.get("tags") or [])]
        tree_docs = [d for d in tree_docs if _match_tags(d.get("tags") or [])]
        url_rows = [u for u in urls if _match_tags(u.get("tags") or [])]

        if not srcs and not tree_docs and not url_rows:
            return {
                "outputs": (
                    "該当するドキュメントはありません。\n\n"
                    "> 「ドキュメント登録」アプリから資料を追加してください。"
                )
            }

        # タグ別にグループ化
        by_tag: dict[str, list[str]] = {}
        untagged_lines: list[str] = []

        def _add(tag_list: list[str], line: str) -> None:
            if not tag_list:
                untagged_lines.append(line)
                return
            for t in tag_list:
                by_tag.setdefault(t, []).append(line)

        for s in srcs:
            kind = "URL" if str(s["source"]).startswith("http") else "ファイル"
            line = (
                f"- **{s['source']}** （{kind} / {s['chunks']}チャンク / "
                f"タグ: {', '.join(s.get('tags') or []) or 'なし'}）"
            )
            _add(s.get("tags") or [], line)
        for d in tree_docs:
            if any(s["source"] == d["source"] for s in srcs):
                continue
            line = (
                f"- **{d['source']}** （構造化 / {d['page_count']}ページ / "
                f"タグ: {', '.join(d.get('tags') or []) or 'なし'}）"
            )
            _add(d.get("tags") or [], line)
        for u in url_rows:
            if any(s["source"] == u["url"] for s in srcs):
                continue
            line = (
                f"- **{u.get('title') or u['url']}** （URL / {u['url']} / "
                f"タグ: {', '.join(u.get('tags') or []) or 'なし'}）"
            )
            _add(u.get("tags") or [], line)

        parts = ["## ドキュメント一覧\n"]
        for t in sorted(by_tag):
            parts.append(f"### タグ: `{t}`\n\n" + "\n".join(by_tag[t]))
        if untagged_lines:
            parts.append(
                "### タグなし（検索対象外）\n\n" + "\n".join(untagged_lines)
            )
        return {"outputs": "\n\n".join(parts)}

    if action == "retag_source":
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジのタグ付け替えはシステム管理者のみ実行できます。"}
        source = (inputs.get("document") or inputs.get("source") or "").strip()
        if not source:
            return {"outputs": "対象ドキュメントを指定してください。"}
        assign = _resolve_assign_tags(inputs)
        if not assign:
            return {"outputs": "付け替えるタグを1つ以上指定してください。"}
        tagstore.ensure_tags(scope, assign)
        await vectorstore.set_tags_by_source(scope, source, assign)
        docstore.set_tags(scope, source, assign)
        if source.startswith("http://") or source.startswith("https://"):
            urlstore.set_tags(scope, source, assign)
        return {
            "outputs": (
                f"「{source}」のタグを更新しました: {', '.join(assign)}"
            )
        }

    if action == "delete_source":
        if not _can_manage(scope, is_admin):
            return {"outputs": "共有ナレッジのドキュメント削除はシステム管理者のみ実行できます。"}
        source = (inputs.get("document") or inputs.get("source") or "").strip()
        if not source:
            return {"outputs": "削除するドキュメントを指定してください。"}
        await vectorstore.delete_by_source(source, scope)
        try:
            docstore.delete_by_source(scope, source)
        except Exception as e:  # noqa: BLE001
            print(f"[rag-app] delete_source: 構造化索引の削除に失敗: {e}")
        if source.startswith("http://") or source.startswith("https://"):
            urlstore.delete_url(scope, source)
        return {"outputs": f"ドキュメント「{source}」をナレッジから削除しました。"}

    if action == "clear":
        if not is_admin:
            return {"outputs": "この操作はシステム管理者のみ実行できます。"}
        await vectorstore.clear(scope)
        removed = urlstore.delete_scope(scope)
        try:
            tree_removed = docstore.delete_scope(scope)
        except Exception:  # noqa: BLE001
            tree_removed = 0
        try:
            tag_removed = tagstore.delete_scope(scope)
        except Exception:  # noqa: BLE001
            tag_removed = 0
        note = f"（URL {removed} / 構造化 {tree_removed} / タグ {tag_removed}）"
        return {"outputs": f"このチームのナレッジを全消去しました{note}。"}

    # ---- 通常の質問応答 ----
    question = (inputs.get("question") or "").strip()
    if not question:
        return {"outputs": "質問が空です。質問を入力してください。"}

    store_mode = (inputs.get("store_mode") or "ephemeral").strip()
    # 互換のため入力があれば尊重。未指定／auto は候補文書に応じて自動選択。
    retrieval_mode = (inputs.get("retrieval_mode") or "auto").strip().lower()
    if retrieval_mode not in ("auto", "full", "vector", "tree", "hybrid"):
        retrieval_mode = "auto"
    # 永続登録は管理権限が要る（共有ナレッジは管理者のみ）。権限が無ければ一時利用に降格。
    if store_mode == "permanent" and not _can_manage(scope, is_admin):
        store_mode = "ephemeral"
    uploaded = _extract_uploaded_texts(inputs)

    result_nodes: dict[str, Any] = {}
    try:
        if uploaded and store_mode == "ephemeral":
            # 一時利用: Qdrant に保存せず、添付ドキュメントのみから回答
            hits = await ephemeral_search(question, uploaded, top_k)
            if not hits:
                return {"outputs": "添付ドキュメントから情報を抽出できませんでした。"}
            result = await _answer_with_hits(question, hits)
            note = "\n\n> ※ 添付ファイルはこの回答のみで使用し、ナレッジには保存していません。"
            return {
                "outputs": result["outputs"] + note,
                "artifacts": result["artifacts"],
            }

        # 永続: 添付があればこのチームのスコープへ取り込み（重複排除）、その後検索
        if uploaded:
            await ingest_documents(uploaded, scope, tags)
        result_nodes = await retrieve.retrieve(
            question,
            scope,
            mode=retrieval_mode,
            top_k=top_k,
            tags=tags or None,
            doc_id=(inputs.get("doc_id") or "").strip() or None,
            source=(inputs.get("source") or "").strip() or None,
        )
        hits = retrieve.nodes_to_hits(result_nodes.get("nodes") or [])
    except Exception as e:  # noqa: BLE001
        return {"outputs": f"検索中にエラーが発生しました: {e}"}

    if not hits:
        return {
            "outputs": (
                "ナレッジに該当する情報が見つかりませんでした。"
                "タグ付きで登録された資料があるか確認してください"
                "（タグ未付与の資料は検索対象外です）。"
            )
        }

    result = await _answer_with_hits(question, hits)
    resolved = result_nodes.get("resolved_mode") or retrieval_mode
    return {
        **result,
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "retrieval_mode": resolved,
            "requested_mode": retrieval_mode,
            "trace": result_nodes.get("trace"),
        },
    }
