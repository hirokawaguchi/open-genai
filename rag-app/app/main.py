"""ローカル RAG「AI アプリ」マイクロサービス。

源内 の「行政実務用 AI アプリ」プロトコル（同期形式）に準拠する:
- リクエスト: { "inputs": { "question": str, "top_k"?: int, "files"?: [...] } }
- レスポンス: { "outputs": "<Markdown テキスト>" }

埋め込みは Ollama の mxbai-embed-large、ベクトル DB は Qdrant、
回答生成も Ollama（既定 gpt-oss:20b）を利用する。
"""

from __future__ import annotations

import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from shared.docextract import extract_doc_text

from . import embeddings, folders, vectorstore

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")

# ナレッジのスコープ（既定 = 共通チーム）。backend が x-scope ヘッダで teamId を渡す。
DEFAULT_SCOPE = os.environ.get(
    "RAG_DEFAULT_SCOPE", "00000000-0000-0000-0000-000000000000"
)

# チャンク内容から決定的な ID を生成する名前空間（重複排除に利用）
_CHUNK_NS = uuid.UUID("6f1e0c2a-9b4d-5e7a-8c3f-0a1b2c3d4e5f")


def _chunk_id(scope: str, folder: str, source: str, text: str) -> str:
    # 同一(スコープ+フォルダ+出典+本文)のチャンクは同じ ID になり、upsert で上書き＝重複排除
    return str(uuid.uuid5(_CHUNK_NS, f"{scope}\n{folder}\n{source}\n{text}"))

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
    docs: list[dict[str, Any]], scope: str, folder: str = ""
) -> int:
    """docs を埋め込んで、指定スコープ(teamId 等)・フォルダに紐付けて Qdrant に登録。

    チャンクは (スコープ+フォルダ+出典+本文) の決定的 ID を持つため、再登録は
    上書きとなり重複しない（重複排除）。folder は階層パス（例 `総務/例規`）。
    """
    folder = folders.normalize_path(folder)
    folder_path = folders.ancestors(folder)  # 祖先を含むパス配列（サブツリー検索用）
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs:
        text = doc.get("text", "")
        source = doc.get("source", "unknown")
        for chunk in chunk_text(text):
            cid = _chunk_id(scope, folder, source, chunk)
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
                        "folder": folder,
                        "folder_path": folder_path,
                    },
                }
            )
    if not items:
        return 0
    return await vectorstore.upsert(items)


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
        folders.init_db()
    except Exception as e:  # noqa: BLE001 - 起動を止めない
        print(f"[rag-app] フォルダDB初期化をスキップ: {e}")
    try:
        if await vectorstore.count() == 0:
            # サンプルは共通スコープのルートに投入
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


@app.post("/clear_scope")
async def clear_scope(
    request: Request, x_api_key: str | None = Header(default=None)
) -> Any:
    """指定スコープ(teamId 等)のナレッジを全消去する（チーム削除時に backend が呼ぶ）。"""
    err = _check_key(x_api_key)
    if err:
        return err
    body = await request.json()
    scope = (body.get("scope") or "").strip()
    if not scope:
        return {"cleared": None}
    await vectorstore.clear(scope)
    return {"cleared": scope}


@app.post("/ingest")
async def ingest(request: Request, x_api_key: str | None = Header(default=None)) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err
    body = await request.json()
    docs = body.get("documents", [])
    scope = (body.get("scope") or DEFAULT_SCOPE).strip()
    folder = folders.normalize_path(body.get("folder"))
    added = await ingest_documents(docs, scope, folder)
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
        context_blocks.append(f"[{i}] (出典: {source})\n{text}")
        sources.append(f"[{i}] {source} (類似度: {score:.3f})")

    context = "\n\n".join(context_blocks)
    system_prompt = (
        "あなたは行政実務を支援する RAG アシスタントです。"
        "以下の「参考情報」だけを根拠に、日本語で簡潔かつ正確に回答してください。"
        "回答中で参照した箇所には [1] のように出典番号を付けてください。"
        "参考情報に答えが無い場合は、推測せず『提供された情報では分かりません』と述べてください。"
    )
    user_prompt = f"# 参考情報\n{context}\n\n# 質問\n{question}"
    answer = await embeddings.generate(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    return f"{answer}\n\n---\n**出典**\n" + "\n".join(f"- {s}" for s in sources)


def _user_groups(x_user_groups: str | None) -> list[str]:
    return [g.strip() for g in (x_user_groups or "").split(",") if g.strip()]


def _is_admin(x_user_groups: str | None) -> bool:
    return "SystemAdminGroup" in set(_user_groups(x_user_groups))


def _parse_groups(value: str | None) -> list[str]:
    """';' か ',' 区切りのグループ名リスト。"""
    if not value:
        return []
    out: list[str] = []
    for chunk in str(value).replace(";", ",").split(","):
        g = chunk.strip()
        if g:
            out.append(g)
    return out


@app.post("/invoke")
async def invoke(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err

    # ナレッジのスコープ（= AI アプリを所有するチーム。共通チームは共有ナレッジ）
    scope = (x_scope or DEFAULT_SCOPE).strip()

    body = await request.json()
    inputs = body.get("inputs", body)
    action = (inputs.get("action") or "ask").strip()
    top_k = int(inputs.get("top_k") or 4)
    folder = folders.normalize_path(inputs.get("folder"))
    groups = _user_groups(x_user_groups)
    is_admin = _is_admin(x_user_groups)

    # ---- フォルダ管理（6-(10)(11)(13)）----
    if action == "list_folders":
        rows = folders.list_folders(scope)
        if not rows:
            return {"outputs": "フォルダは未作成です（ルートに登録されます）。"}
        lines = "\n".join(
            f"- `{r['path']}`" + (f"（許可: {', '.join(r['allowedGroups'])}）" if r["allowedGroups"] else "（許可: 制限なし）")
            for r in rows
        )
        return {"outputs": f"## フォルダ一覧（このチーム）\n\n{lines}"}

    if action == "create_folder":
        if not is_admin:
            return {"outputs": "フォルダ作成はシステム管理者のみ実行できます。"}
        if not folder:
            return {"outputs": "作成するフォルダのパス（例 `総務/例規`）を指定してください。"}
        allow = _parse_groups(inputs.get("groups"))
        folders.create_folder(scope, folder, allow)
        acl = f"（許可グループ: {', '.join(allow)}）" if allow else "（許可: 制限なし）"
        return {"outputs": f"フォルダ `{folder}` を作成しました{acl}。"}

    if action == "set_folder_acl":
        if not is_admin:
            return {"outputs": "フォルダ権限の設定はシステム管理者のみ実行できます。"}
        if not folder:
            return {"outputs": "対象フォルダのパスを指定してください。"}
        allow = _parse_groups(inputs.get("groups"))
        folders.set_acl(scope, folder, allow)
        acl = f"{', '.join(allow)}" if allow else "制限なし"
        return {"outputs": f"フォルダ `{folder}` のアクセス許可を「{acl}」に設定しました。"}

    if action == "delete_folder":
        if not is_admin:
            return {"outputs": "フォルダ削除はシステム管理者のみ実行できます。"}
        if not folder:
            return {"outputs": "削除するフォルダのパスを指定してください。"}
        await vectorstore.delete_folder(scope, folder)
        folders.delete_folder(scope, folder)
        return {"outputs": f"フォルダ `{folder}`（配下含む）を削除しました。"}

    # ---- 管理操作: 出典一覧 / 出典削除 / 全消去（スコープ＋任意フォルダ内） ----
    if action == "list_sources":
        if folder and not folders.can_access(scope, folder, groups, is_admin):
            return {"outputs": f"フォルダ `{folder}` へのアクセス権限がありません。"}
        srcs = await vectorstore.list_sources(scope, folder or None)
        where = f"フォルダ `{folder}`" if folder else "このチーム"
        if not srcs:
            return {"outputs": f"{where}の知識ベースは空です。"}
        lines = "\n".join(f"- {s['source']}（{s['chunks']} チャンク）" for s in srcs)
        return {"outputs": f"## 登録済みの出典（{where}）\n\n{lines}"}

    if action == "delete_source":
        if not is_admin:
            return {"outputs": "この操作はシステム管理者のみ実行できます。"}
        source = (inputs.get("source") or "").strip()
        if not source:
            return {"outputs": "削除する出典名（source）を指定してください。"}
        await vectorstore.delete_by_source(source, scope, folder or None)
        return {"outputs": f"出典「{source}」を知識ベースから削除しました。"}

    if action == "clear":
        if not is_admin:
            return {"outputs": "この操作はシステム管理者のみ実行できます。"}
        await vectorstore.clear(scope)
        return {"outputs": "このチームの知識ベースを全消去しました。"}

    # ---- 通常の質問応答 ----
    question = (inputs.get("question") or "").strip()
    if not question:
        return {"outputs": "質問が空です。質問を入力してください。"}

    # フォルダ指定時はアクセス権限を確認
    if folder and not folders.can_access(scope, folder, groups, is_admin):
        return {"outputs": f"フォルダ `{folder}` へのアクセス権限がありません。"}

    store_mode = (inputs.get("store_mode") or "permanent").strip()
    uploaded = _extract_uploaded_texts(inputs)

    try:
        if uploaded and store_mode == "ephemeral":
            # 一時利用: Qdrant に保存せず、添付ドキュメントのみから回答
            hits = await ephemeral_search(question, uploaded, top_k)
            if not hits:
                return {"outputs": "添付ドキュメントから情報を抽出できませんでした。"}
            answer = await _answer_with_hits(question, hits)
            note = "\n\n> ※ 添付ファイルはこの回答のみで使用し、知識ベースには保存していません。"
            return {"outputs": answer + note}

        # 永続: 添付があればこのチームのスコープ・フォルダへ取り込み（重複排除）、その後検索
        if uploaded:
            await ingest_documents(uploaded, scope, folder)
        qvec = await embeddings.embed(question, is_query=True)
        hits = await vectorstore.search(qvec, top_k, scope, folder or None)
    except Exception as e:  # noqa: BLE001
        return {"outputs": f"検索中にエラーが発生しました: {e}"}

    if not hits:
        return {
            "outputs": (
                "知識ベースに該当する情報が見つかりませんでした。"
                "ドキュメントを添付するか、知識を登録してください。"
            )
        }

    answer = await _answer_with_hits(question, hits)
    return {
        "outputs": answer,
        "_meta": {"generated_at": datetime.now(timezone.utc).isoformat()},
    }
