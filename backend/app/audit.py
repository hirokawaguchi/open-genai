"""監査ログ基盤（利用状況・利用内容ログ）。

本サービス仕様書 8-(1)「利用者単位の利用状況/内容ログを管理者が確認できること。
ログの保存期間は最低3年以上」への対応。

設計方針（docs/設計_ログ基盤とユーザー別履歴分離.md §2）:
- チャット履歴(messages)とは独立した append-only ストア（利用者削除と非連動）。
- 専用 SQLite DB（AUDIT_DB_PATH）。非同期ライター（キュー＋デーモンスレッド）で
  リクエスト経路をブロックしない。
- 保持期間は最低3年を下限としてガードし、日次パージで超過分を削除。
- ローカル保存のみ（外部送信なし）。

このモジュールは標準ライブラリのみに依存する（auth はクレーム抽出時に遅延 import）。
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

AUDIT_DB_PATH = os.environ.get("AUDIT_DB_PATH", "/data/audit.db")
AUDIT_ENABLED = os.environ.get("AUDIT_ENABLED", "true").lower() not in ("0", "false", "no")
AUDIT_STORE_CONTENT = os.environ.get("AUDIT_STORE_CONTENT", "true").lower() not in (
    "0",
    "false",
    "no",
)
AUDIT_MAX_CONTENT_CHARS = int(os.environ.get("AUDIT_MAX_CONTENT_CHARS", "8000"))

# 保持日数。3年(1095日)を下限としてガードする。
_RETENTION_MIN_DAYS = 1095
AUDIT_RETENTION_DAYS = max(
    int(os.environ.get("AUDIT_RETENTION_DAYS", "1825")), _RETENTION_MIN_DAYS
)

# パージ間隔（秒）。既定 1 日。
PURGE_INTERVAL_SECONDS = int(os.environ.get("AUDIT_PURGE_INTERVAL", str(24 * 3600)))

# アクセスログを記録しないパス接頭辞（ノイズ削減）。
_SKIP_ACCESS_PREFIXES = (
    "/health",
    "/files/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/auth/saml/metadata",
)
# 専用の内容ログを別途記録するため、アクセスログを重複させないパス。
_CONTENT_LOGGED_PREFIXES = (
    "/predict/stream",
    "/predict/title",
    "/exapps/invoke",
)

_queue: "queue.Queue[dict[str, Any] | None]" = queue.Queue(maxsize=10000)
_writer_started = False
_writer_lock = threading.Lock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str = AUDIT_DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id           TEXT PRIMARY KEY,
                ts           INTEGER NOT NULL,
                tsIso        TEXT NOT NULL,
                userId       TEXT NOT NULL DEFAULT '',
                userEmail    TEXT NOT NULL DEFAULT '',
                userName     TEXT NOT NULL DEFAULT '',
                groups       TEXT NOT NULL DEFAULT '[]',
                action       TEXT NOT NULL,
                method       TEXT,
                path         TEXT,
                usecase      TEXT,
                chatId       TEXT,
                teamId       TEXT,
                exAppId      TEXT,
                model        TEXT,
                inputChars   INTEGER,
                outputChars  INTEGER,
                inputText    TEXT,
                outputText   TEXT,
                status       INTEGER,
                latencyMs    INTEGER,
                ip           TEXT,
                userAgent    TEXT,
                sessionId    TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_user_ts ON audit_logs(userId, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_action_ts ON audit_logs(action, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(ts);
            """
        )


# ---------------------------------------------------------------------------
# 非同期ライター
# ---------------------------------------------------------------------------
def _writer_loop() -> None:
    conn = _connect()
    try:
        while True:
            item = _queue.get()
            if item is None:  # 終了シグナル
                break
            batch = [item]
            # 滞留分をまとめて書く
            while len(batch) < 200:
                try:
                    nxt = _queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    batch.append(None)  # type: ignore[arg-type]
                    break
                batch.append(nxt)
            rows = [b for b in batch if b is not None]
            if rows:
                try:
                    _write_batch(conn, rows)
                except Exception as e:  # noqa: BLE001 - ログ失敗は本処理に影響させない
                    print(f"[audit] 書き込み失敗: {e}")
            if any(b is None for b in batch):
                break
    finally:
        conn.close()


_COLUMNS = (
    "id", "ts", "tsIso", "userId", "userEmail", "userName", "groups", "action",
    "method", "path", "usecase", "chatId", "teamId", "exAppId", "model",
    "inputChars", "outputChars", "inputText", "outputText", "status",
    "latencyMs", "ip", "userAgent", "sessionId",
)


def _write_batch(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    placeholders = ",".join(["?"] * len(_COLUMNS))
    sql = f"INSERT OR IGNORE INTO audit_logs ({','.join(_COLUMNS)}) VALUES ({placeholders})"
    with conn:
        conn.executemany(
            sql, [tuple(r.get(c) for c in _COLUMNS) for r in rows]
        )


def _ensure_writer() -> None:
    global _writer_started
    if _writer_started:
        return
    with _writer_lock:
        if _writer_started:
            return
        init_db()
        t = threading.Thread(target=_writer_loop, name="audit-writer", daemon=True)
        t.start()
        _writer_started = True


def start() -> None:
    """起動時に呼ぶ（ライター起動＋パージスケジューラ起動）。"""
    if not AUDIT_ENABLED:
        return
    _ensure_writer()
    _start_purge_scheduler()


# ---------------------------------------------------------------------------
# クレーム抽出（request から best-effort）
# ---------------------------------------------------------------------------
def _claims_from_request(request: Any) -> dict[str, Any]:
    if request is None:
        return {}
    try:
        authz = request.headers.get("authorization", "")
    except Exception:  # noqa: BLE001
        return {}
    if not authz.startswith("Bearer "):
        return {}
    try:
        from . import auth  # 遅延 import（テスト時の依存を避ける）

        return auth.verify_token(authz[7:])
    except Exception:  # noqa: BLE001
        return {}


def _clip(text: str | None) -> str | None:
    if text is None:
        return None
    if not AUDIT_STORE_CONTENT:
        return None
    if len(text) > AUDIT_MAX_CONTENT_CHARS:
        return text[:AUDIT_MAX_CONTENT_CHARS] + "…(以下省略)"
    return text


def _client_ip(request: Any) -> str | None:
    if request is None:
        return None
    try:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        client = getattr(request, "client", None)
        return getattr(client, "host", None) if client else None
    except Exception:  # noqa: BLE001
        return None


def record(
    request: Any = None,
    *,
    action: str,
    usecase: str | None = None,
    chatId: str | None = None,
    teamId: str | None = None,
    exAppId: str | None = None,
    model: str | None = None,
    input_text: str = "",
    output_text: str = "",
    status: int | None = None,
    latency_ms: int | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    user_email: str | None = None,
    user_name: str | None = None,
    groups: list[str] | None = None,
) -> None:
    """監査ログを1件キューに積む（非ブロッキング）。

    user_* を明示しない場合は request の Bearer トークンから抽出する
    （ログイン処理など、まだ JWT が無い場面では明示指定する）。
    """
    if not AUDIT_ENABLED:
        return
    _ensure_writer()

    claims = {}
    if user_id is None:
        claims = _claims_from_request(request)

    method = path = ua = None
    if request is not None:
        try:
            method = request.method
            path = request.url.path
            ua = request.headers.get("user-agent")
        except Exception:  # noqa: BLE001
            pass

    event = {
        "id": str(uuid.uuid4()),
        "ts": _now_ms(),
        "tsIso": _now_iso(),
        "userId": user_id if user_id is not None else (claims.get("sub") or claims.get("email") or ""),
        "userEmail": user_email if user_email is not None else (claims.get("email") or ""),
        "userName": user_name if user_name is not None else (claims.get("name") or ""),
        "groups": json.dumps(
            groups if groups is not None else (claims.get("groups") or []),
            ensure_ascii=False,
        ),
        "action": action,
        "method": method,
        "path": path,
        "usecase": usecase,
        "chatId": chatId,
        "teamId": teamId,
        "exAppId": exAppId,
        "model": model,
        "inputChars": len(input_text) if input_text else 0,
        "outputChars": len(output_text) if output_text else 0,
        "inputText": _clip(input_text) if input_text else None,
        "outputText": _clip(output_text) if output_text else None,
        "status": status,
        "latencyMs": latency_ms,
        "ip": _client_ip(request),
        "userAgent": ua,
        "sessionId": session_id,
    }
    try:
        _queue.put_nowait(event)
    except queue.Full:
        print("[audit] キュー満杯のためログを1件ドロップしました")


def record_access(request: Any, status: int, latency_ms: int) -> None:
    """ミドルウェア用: 全 API のアクセスログ（内容なし）。"""
    if not AUDIT_ENABLED:
        return
    try:
        path = request.url.path
    except Exception:  # noqa: BLE001
        return
    if any(path.startswith(p) for p in _SKIP_ACCESS_PREFIXES):
        return
    if any(path.startswith(p) for p in _CONTENT_LOGGED_PREFIXES):
        return  # 専用の内容ログがあるため重複させない
    record(
        request,
        action="api.access",
        usecase=path,
        status=status,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# ストリーム応答のラップ（入力＋集約した出力を1件記録）
# ---------------------------------------------------------------------------
def _extract_text_from_ndjson(buf: str) -> str:
    parts: list[str] = []
    for line in buf.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("text")
        if t:
            parts.append(t)
    return "".join(parts)


async def wrap_stream(
    gen: AsyncIterator[str],
    request: Any,
    *,
    action: str,
    usecase: str | None = None,
    input_text: str = "",
    model: str | None = None,
) -> AsyncIterator[str]:
    """StreamingResponse の generator をラップし、完了時に監査ログを1件記録する。"""
    started = time.time()
    chunks: list[str] = []
    status = 200
    try:
        async for chunk in gen:
            chunks.append(chunk)
            yield chunk
    finally:
        try:
            output_text = _extract_text_from_ndjson("".join(chunks))
            record(
                request,
                action=action,
                usecase=usecase,
                model=model,
                input_text=input_text,
                output_text=output_text,
                status=status,
                latency_ms=int((time.time() - started) * 1000),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[audit] ストリーム記録に失敗: {e}")


# ---------------------------------------------------------------------------
# 管理者閲覧（クエリ・エクスポート）
# ---------------------------------------------------------------------------
def query(
    *,
    user_id: str | None = None,
    action: str | None = None,
    ts_from: int | None = None,
    ts_to: int | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    if user_id:
        where.append("userId = ?")
        params.append(user_id)
    if action:
        where.append("action = ?")
        params.append(action)
    if ts_from is not None:
        where.append("ts >= ?")
        params.append(ts_from)
    if ts_to is not None:
        where.append("ts <= ?")
        params.append(ts_to)
    if q:
        where.append("(inputText LIKE ? OR outputText LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    limit = max(1, min(limit, 1000))
    with _connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM audit_logs{clause}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM audit_logs{clause} ORDER BY ts DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return {
        "total": total,
        "items": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


def iter_export(ts_from: int | None = None, ts_to: int | None = None):
    """JSONL エクスポート用のジェネレータ（管理者向け）。"""
    where: list[str] = []
    params: list[Any] = []
    if ts_from is not None:
        where.append("ts >= ?")
        params.append(ts_from)
    if ts_to is not None:
        where.append("ts <= ?")
        params.append(ts_to)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with _connect() as conn:
        for r in conn.execute(
            f"SELECT * FROM audit_logs{clause} ORDER BY ts ASC", params
        ):
            yield json.dumps(dict(r), ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# パージ（保持期間超過の削除）
# ---------------------------------------------------------------------------
def purge_old() -> int:
    """保持期間を超えたログを削除し、削除件数を返す。"""
    cutoff = _now_ms() - AUDIT_RETENTION_DAYS * 24 * 3600 * 1000
    with _connect() as conn:
        with conn:
            cur = conn.execute("DELETE FROM audit_logs WHERE ts < ?", (cutoff,))
        return cur.rowcount


def _purge_loop() -> None:
    while True:
        try:
            deleted = purge_old()
            if deleted:
                print(f"[audit] 保持期間超過のログを {deleted} 件削除しました")
        except Exception as e:  # noqa: BLE001
            print(f"[audit] パージに失敗: {e}")
        time.sleep(PURGE_INTERVAL_SECONDS)


_purge_started = False


def _start_purge_scheduler() -> None:
    global _purge_started
    if _purge_started:
        return
    with _writer_lock:
        if _purge_started:
            return
        t = threading.Thread(target=_purge_loop, name="audit-purge", daemon=True)
        t.start()
        _purge_started = True
