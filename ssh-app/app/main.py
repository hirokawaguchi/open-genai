"""Web SSH マイクロサービス（Open GENAI 専用ページ向け）。

- 庁内: backend が JWT 検証後、HMAC 署名付きで /hosts と /ws へプロキシ
- 接続先は管理者が登録したカタログのみ。パスワードは保存しない

Compose では profiles: ["ssh"] でオプション起動する。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import asyncssh
from fastapi import FastAPI, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from . import intauth, session, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
IDLE_SECONDS = session.IDLE_SECONDS
MAX_SESSIONS = session.MAX_SESSIONS

app = FastAPI(title="Open GENAI SSH App", version="0.1.0")


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _is_admin(groups: str | None) -> bool:
    return "SystemAdminGroup" in [g.strip() for g in (groups or "").split(",") if g.strip()]


def _verify_internal(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
) -> tuple[JSONResponse | None, str, bool]:
    err = _check_key(x_api_key)
    if err:
        return err, "", False
    if not intauth.verify(
        x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    ):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"}), "", False
    if not x_user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), "", False
    return None, x_user_id, _is_admin(x_user_groups)


def _headers_from_ws(websocket: WebSocket) -> tuple[str | None, str]:
    h = websocket.headers
    err, user_id, _admin = _verify_internal(
        h.get("x-api-key"),
        h.get("x-user-id"),
        h.get("x-user-groups"),
        h.get("x-scope"),
        h.get("x-user-ts"),
        h.get("x-user-sig"),
        h.get("x-user-tags"),
    )
    if err:
        return err.body.decode("utf-8") if err.body else "unauthorized", ""
    return None, user_id


@app.on_event("startup")
def on_startup() -> None:
    store.init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def config(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _user_id, is_admin = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(
        {
            "enabled": True,
            "is_admin": is_admin,
            "idle_seconds": IDLE_SECONDS,
            "max_sessions_per_user": MAX_SESSIONS,
        }
    )


@app.get("/hosts")
def list_hosts(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _user_id, is_admin = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    hosts = store.list_hosts(include_disabled=is_admin, include_key=is_admin)
    return JSONResponse({"hosts": hosts, "is_admin": is_admin})


@app.post("/hosts")
async def create_host(
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _user_id, is_admin = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if not is_admin:
        return JSONResponse(status_code=403, content={"error": "管理者のみ接続先を登録できます"})
    created, msg = store.create_host(payload if isinstance(payload, dict) else {})
    if msg:
        return JSONResponse(status_code=400, content={"error": msg})
    return JSONResponse({"host": created})


@app.put("/hosts/{host_id}")
async def update_host(
    host_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _user_id, is_admin = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if not is_admin:
        return JSONResponse(status_code=403, content={"error": "管理者のみ接続先を更新できます"})
    updated, msg = store.update_host(host_id, payload if isinstance(payload, dict) else {})
    if msg:
        status = 404 if msg == "接続先が見つかりません" else 400
        return JSONResponse(status_code=status, content={"error": msg})
    return JSONResponse({"host": updated})


@app.delete("/hosts/{host_id}")
def delete_host(
    host_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _user_id, is_admin = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if not is_admin:
        return JSONResponse(status_code=403, content={"error": "管理者のみ接続先を削除できます"})
    if not store.delete_host(host_id):
        return JSONResponse(status_code=404, content={"error": "接続先が見つかりません"})
    return JSONResponse({"ok": True})


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


def _connect_error_message(exc: BaseException) -> str:
    if isinstance(exc, session.HostKeyMismatchError):
        return "ホスト鍵が登録済みの値と一致しません。管理者が接続先のホスト鍵を確認してください。"
    if isinstance(exc, session.HostDisabledError):
        return "この接続先は無効です"
    if isinstance(exc, session.SessionLimitError):
        return f"同時接続数の上限（{MAX_SESSIONS}）に達しています"
    if isinstance(exc, asyncssh.PermissionDenied):
        return "ユーザー名またはパスワードが正しくありません"
    if isinstance(exc, asyncssh.HostKeyNotVerifiable):
        return "ホスト鍵を検証できませんでした"
    if isinstance(exc, (asyncssh.DisconnectError, asyncssh.ConnectionLost, OSError)):
        return "SSH 先に接続できませんでした"
    return "SSH 接続に失敗しました"


@app.websocket("/ws")
async def ssh_ws(websocket: WebSocket) -> None:
    auth_err, user_id = _headers_from_ws(websocket)
    if auth_err or not user_id:
        await websocket.close(code=4401)
        return
    await websocket.accept()

    conn: asyncssh.SSHClientConnection | None = None
    proc: asyncssh.SSHClientProcess | None = None
    acquired = False
    host_meta: dict[str, Any] | None = None
    try:
        raw = await websocket.receive_text()
        try:
            first = json.loads(raw)
        except json.JSONDecodeError:
            await _send_json(websocket, {"type": "error", "message": "接続パラメータが不正です"})
            await websocket.close(code=4400)
            return
        if not isinstance(first, dict):
            await _send_json(websocket, {"type": "error", "message": "接続パラメータが不正です"})
            await websocket.close(code=4400)
            return

        host_id = str(first.get("hostId") or first.get("host_id") or "").strip()
        username = str(first.get("username") or "").strip()
        password = str(first.get("password") or "")
        try:
            cols = int(first.get("cols") or 80)
            rows = int(first.get("rows") or 25)
        except (TypeError, ValueError):
            cols, rows = 80, 25

        user_err = store.validate_username(username)
        if user_err:
            await _send_json(websocket, {"type": "error", "message": user_err})
            await websocket.close(code=4400)
            return
        if not password:
            await _send_json(websocket, {"type": "error", "message": "パスワードを入力してください"})
            await websocket.close(code=4400)
            return

        host_row = store.get_host(host_id, include_key=True)
        if host_row is None:
            await _send_json(websocket, {"type": "error", "message": "登録されていない接続先です"})
            await websocket.close(code=4404)
            return
        host_meta = {
            "hostId": host_row["id"],
            "host": host_row["host"],
            "port": host_row["port"],
            "username": username,
        }

        await session.acquire(user_id)
        acquired = True
        conn, proc, _learned = await session.open_connection(
            host_row, username=username, password=password, cols=cols, rows=rows
        )
        await _send_json(websocket, {"type": "ready", **host_meta})

        idle = session.IdleWatch()

        async def pump_stdout() -> None:
            assert proc is not None
            try:
                while True:
                    data = await proc.stdout.read(4096)
                    if not data:
                        break
                    idle.touch()
                    await websocket.send_bytes(data)
            except (asyncssh.Error, WebSocketDisconnect, RuntimeError):
                return

        async def watch_idle() -> None:
            while True:
                await asyncio.sleep(15)
                if idle.expired():
                    await _send_json(
                        websocket,
                        {"type": "error", "message": "一定時間操作がなかったため切断しました"},
                    )
                    await websocket.close(code=4408)
                    return

        stdout_task = asyncio.create_task(pump_stdout())
        idle_task = asyncio.create_task(watch_idle())
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    idle.touch()
                    if proc.stdin:
                        proc.stdin.write(message["bytes"])
                        await proc.stdin.drain()
                    continue
                text = message.get("text")
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                kind = payload.get("type")
                if kind == "input":
                    data = payload.get("data")
                    if isinstance(data, str) and proc.stdin:
                        idle.touch()
                        proc.stdin.write(data.encode("utf-8", errors="surrogateescape"))
                        await proc.stdin.drain()
                elif kind == "resize":
                    try:
                        next_cols = max(20, min(int(payload.get("cols") or cols), 500))
                        next_rows = max(8, min(int(payload.get("rows") or rows), 200))
                    except (TypeError, ValueError):
                        continue
                    idle.touch()
                    proc.change_terminal_size(next_cols, next_rows)
        finally:
            idle_task.cancel()
            stdout_task.cancel()
            await asyncio.gather(idle_task, stdout_task, return_exceptions=True)
            exit_status = None
            if proc is not None:
                try:
                    exit_status = proc.exit_status
                except Exception:  # noqa: BLE001
                    exit_status = None
            try:
                await _send_json(websocket, {"type": "exit", "code": exit_status, **(host_meta or {})})
            except Exception:  # noqa: BLE001
                pass
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await _send_json(websocket, {"type": "error", "message": _connect_error_message(exc)})
        except Exception:  # noqa: BLE001
            pass
        try:
            await websocket.close(code=1011)
        except Exception:  # noqa: BLE001
            pass
    finally:
        if proc is not None:
            try:
                proc.close()
                await proc.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        if conn is not None:
            try:
                conn.close()
                await conn.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        if acquired:
            await session.release(user_id)
