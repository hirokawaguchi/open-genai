"""利用者ごとの Chromium セッション。

Xvfb の上で Chromium を開き、x11vnc のバイト列を WebSocket へ中継する。
Cookie と履歴は利用者ごとに残す。画面とダウンロードの一時ファイルはセッション終了で消す。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import audio, downloads

IDLE_SECONDS = int(os.environ.get("BROWSER_IDLE_SECONDS", "1800"))
MAX_PER_USER = int(os.environ.get("BROWSER_MAX_SESSIONS_PER_USER", "1"))
MAX_SESSIONS = int(os.environ.get("BROWSER_MAX_SESSIONS", "2"))
EGRESS_PORT = int(os.environ.get("BROWSER_EGRESS_PORT", "18080"))
CONNECT_GRACE_SECONDS = int(os.environ.get("BROWSER_CONNECT_GRACE_SECONDS", "60"))
RUNTIME_ROOT = Path(os.environ.get("BROWSER_RUNTIME_DIR", "/tmp/open-genai-browser"))
PROFILE_ROOT = Path(os.environ.get("BROWSER_PROFILE_DIR", "/data/browser-profiles"))
PROFILE_MAX_BYTES = int(os.environ.get("BROWSER_PROFILE_MAX_BYTES", str(512 * 1024 * 1024)))
DISK_CACHE_BYTES = int(os.environ.get("BROWSER_DISK_CACHE_BYTES", str(64 * 1024 * 1024)))
_ID_OK = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_CACHE_RELATIVE = (
    "Default/Cache",
    "Default/Code Cache",
    "Default/GPUCache",
    "Default/DawnGraphiteCache",
    "Default/DawnWebGPUCache",
    "ShaderCache",
    "GrShaderCache",
    "GraphiteDawnCache",
    "Default/Service Worker/CacheStorage",
    "Default/Service Worker/ScriptCache",
)
_LOCK_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


class SessionLimitError(Exception):
    pass


class BrowserStartError(Exception):
    pass


def screen_size() -> tuple[int, int]:
    raw = os.environ.get("BROWSER_SCREEN", "1280x800").strip().lower()
    if "x" not in raw:
        return 1280, 800
    width_text, _, height_text = raw.partition("x")
    try:
        width = int(width_text)
        height = int(height_text)
    except ValueError:
        return 1280, 800
    return max(800, min(width, 1920)), max(600, min(height, 1200))


def _chromium_args(profile: Path, width: int, height: int) -> list[str]:
    binary = os.environ.get("BROWSER_CHROMIUM_BIN", "chromium")
    return [
        binary,
        f"--user-data-dir={profile / 'chrome'}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-translate",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-breakpad",
        "--disable-crash-reporter",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-features=DnsOverHttps,WebRtcHideLocalIpsWithMdns,MediaRouter,DownloadBubble",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        f"--proxy-server=http://127.0.0.1:{EGRESS_PORT}",
        "--proxy-bypass-list=<-loopback>",
        f"--window-size={width},{height}",
        "--window-position=0,0",
        "--lang=ja",
        "--accept-lang=ja-JP,ja",
        f"--disk-cache-size={DISK_CACHE_BYTES}",
        "--password-store=basic",
        "about:blank",
    ]


def profile_key(user_id: str) -> str:
    """利用者 ID をディレクトリ名にする。メールアドレスはパスに出さない。"""
    uid = (user_id or "").strip()
    if not uid or "\x00" in uid:
        raise BrowserStartError("利用者が分かりません")
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:32]


def chrome_home_for(user_id: str) -> Path:
    return PROFILE_ROOT / profile_key(user_id)


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_symlink() or not item.is_file():
            continue
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


def trim_profile_cache(chrome_dir: Path, limit: int = PROFILE_MAX_BYTES) -> bool:
    """上限を超えていたらキャッシュだけ捨てる。Cookie と履歴は残す。"""
    if directory_size(chrome_dir) <= limit:
        return False
    for relative in _CACHE_RELATIVE:
        shutil.rmtree(chrome_dir / relative, ignore_errors=True)
    return True


def clear_chrome_locks(chrome_dir: Path) -> None:
    for name in _LOCK_NAMES:
        path = chrome_dir / name
        try:
            if path.is_symlink() or path.exists():
                path.unlink()
        except OSError:
            continue


def clear_profile_downloads(chrome_dir: Path) -> None:
    for relative in ("Default/Downloads", "Downloads"):
        shutil.rmtree(chrome_dir / relative, ignore_errors=True)


def prepare_chrome_home(home: Path) -> None:
    try:
        home.mkdir(parents=True, exist_ok=True)
        os.chmod(home, 0o700)
        chrome_dir = home / "chrome"
        chrome_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(chrome_dir, 0o700)
    except OSError as exc:
        raise BrowserStartError("プロファイルを用意できませんでした") from exc
    trim_profile_cache(chrome_dir)
    clear_chrome_locks(chrome_dir)
    clear_profile_downloads(chrome_dir)


@dataclass
class BrowserSession:
    id: str
    user_id: str
    display: int
    vnc_port: int
    width: int
    height: int
    profile: Path
    chrome_home: Path | None = None
    downloads: dict[str, tuple[str, Path]] = field(default_factory=dict)
    download_notes: list[str] = field(default_factory=list)
    watch_task: asyncio.Task | None = None
    env: dict[str, str] = field(default_factory=dict)
    audio_ready: bool = False
    audio_gen: int = 0
    audio_procs: list[asyncio.subprocess.Process] = field(default_factory=list)
    created: float = field(default_factory=time.monotonic)
    touched: float = field(default_factory=time.monotonic)
    attached: bool = False
    reason: str = ""
    stopped: asyncio.Event = field(default_factory=asyncio.Event)
    procs: list[asyncio.subprocess.Process] = field(default_factory=list)
    _killed: bool = False

    def touch(self) -> None:
        self.touched = time.monotonic()

    async def kill(self) -> None:
        if self._killed:
            return
        self._killed = True
        self.stopped.set()
        self.audio_gen += 1
        await audio.stop_procs(self.audio_procs)
        if self.watch_task is not None:
            self.watch_task.cancel()
        for proc in self.procs:
            if proc.returncode is None and proc.pid:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        await asyncio.sleep(0.4)
        for proc in self.procs:
            if proc.returncode is None and proc.pid:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for proc in self.procs:
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except (asyncio.TimeoutError, ProcessLookupError):
                pass
        shutil.rmtree(self.profile, ignore_errors=True)
        if self.chrome_home is not None:
            clear_profile_downloads(self.chrome_home / "chrome")


_lock = asyncio.Lock()
_sessions: dict[str, BrowserSession] = {}
_displays: set[int] = set()


def _alloc_slot() -> tuple[int, int]:
    for offset in range(32):
        display = 100 + offset
        if display not in _displays:
            return display, 5900 + offset
    raise SessionLimitError("同時に開けるブラウザの上限に達しています。時間をおいて再度お試しください。")


def _detach(sess: BrowserSession) -> None:
    _sessions.pop(sess.id, None)
    _displays.discard(sess.display)


def _env(profile: Path, display: int) -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}:
            env.pop(key, None)
    env["DISPLAY"] = f":{display}"
    env["HOME"] = str(profile)
    env["XDG_CONFIG_HOME"] = str(profile / "config")
    env["XDG_CACHE_HOME"] = str(profile / "cache")
    env["LANG"] = "ja_JP.UTF-8"
    env["LANGUAGE"] = "ja_JP:ja"
    env["LC_ALL"] = "ja_JP.UTF-8"
    return env


async def _spawn(cmd: list[str], env: dict[str, str]) -> asyncio.subprocess.Process:
    try:
        return await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise BrowserStartError("ブラウザの実行ファイルが見つかりません") from exc


async def _wait_until(check, proc: asyncio.subprocess.Process, message: str, timeout: float = 8) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.returncode is not None:
            raise BrowserStartError(message)
        if check():
            return
        await asyncio.sleep(0.1)
    raise BrowserStartError(message)


async def _wait_port(port: int, proc: asyncio.subprocess.Process, message: str) -> None:
    async def ready() -> bool:
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            return False
        writer.close()
        await writer.wait_closed()
        return True

    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if proc.returncode is not None:
            raise BrowserStartError(message)
        if await ready():
            return
        await asyncio.sleep(0.1)
    raise BrowserStartError(message)


async def _start_processes(sess: BrowserSession) -> None:
    sess.profile.mkdir(parents=True, exist_ok=True)
    os.chmod(sess.profile, 0o700)
    (sess.profile / "config").mkdir(exist_ok=True)
    (sess.profile / "cache").mkdir(exist_ok=True)
    env = _env(sess.profile, sess.display)
    sess.env = env
    pulse = await audio.launch(sess.profile, env)
    if pulse is not None:
        sess.procs.append(pulse)
        sess.audio_ready = True
    if sess.chrome_home is None:
        raise BrowserStartError("プロファイルを用意できませんでした")
    prepare_chrome_home(sess.chrome_home)
    download_dir = sess.profile / "Downloads"
    downloads.write_download_prefs(sess.chrome_home, download_dir)
    downloads.write_japanese_locale(sess.chrome_home)
    env["XDG_DOWNLOAD_DIR"] = str(download_dir)
    (sess.profile / "config" / "user-dirs.dirs").write_text(
        f'XDG_DOWNLOAD_DIR="{download_dir}"\n',
        encoding="utf-8",
    )
    xvfb = await _spawn(
        [
            "Xvfb",
            f":{sess.display}",
            "-screen",
            "0",
            f"{sess.width}x{sess.height}x24",
            "-nolisten",
            "tcp",
        ],
        env,
    )
    sess.procs.append(xvfb)
    socket_path = f"/tmp/.X11-unix/X{sess.display}"
    await _wait_until(lambda: os.path.exists(socket_path), xvfb, "画面を起動できませんでした")
    vnc = await _spawn(
        [
            "x11vnc",
            "-display",
            f":{sess.display}",
            "-rfbport",
            str(sess.vnc_port),
            "-localhost",
            "-nopw",
            "-forever",
            "-shared",
            "-noxdamage",
            "-repeat",
            # 確定した日本語など、キーマップに無い文字を足してから入れる。
            "-xkb",
            "-add_keysyms",
            "-quiet",
        ],
        env,
    )
    sess.procs.append(vnc)
    await _wait_port(sess.vnc_port, vnc, "画面転送を起動できませんでした")
    chrome = await _spawn(_chromium_args(sess.chrome_home, sess.width, sess.height), env)
    sess.procs.append(chrome)
    await asyncio.sleep(1.2)
    if chrome.returncode is not None:
        raise BrowserStartError("ブラウザを起動できませんでした")


async def _guard(sess: BrowserSession) -> None:
    while not sess.stopped.is_set():
        try:
            await asyncio.wait_for(sess.stopped.wait(), timeout=15)
            return
        except asyncio.TimeoutError:
            pass
        now = time.monotonic()
        if not sess.attached and now - sess.created > CONNECT_GRACE_SECONDS:
            await stop(sess.id, "connect-timeout")
            return
        if sess.attached and now - sess.touched > IDLE_SECONDS:
            await stop(sess.id, "idle")
            return


async def open_session(user_id: str) -> BrowserSession:
    """利用者の既存セッションは閉じてから、同じプロファイルで Chromium を開く。"""
    chrome_home = chrome_home_for(user_id)
    async with _lock:
        old = [s for s in _sessions.values() if s.user_id == user_id]
        others = [s for s in _sessions.values() if s.user_id != user_id]
        if MAX_PER_USER < 1 or len(others) >= MAX_SESSIONS:
            raise SessionLimitError(
                "同時に開けるブラウザの上限に達しています。時間をおいて再度お試しください。"
            )
        for item in old:
            _detach(item)
        display, vnc_port = _alloc_slot()
        width, height = screen_size()
        session_id = secrets.token_urlsafe(18)
        profile = RUNTIME_ROOT / session_id
        sess = BrowserSession(
            id=session_id,
            user_id=user_id,
            display=display,
            vnc_port=vnc_port,
            width=width,
            height=height,
            profile=profile,
            chrome_home=chrome_home,
        )
        _displays.add(display)
        _sessions[session_id] = sess
    for item in old:
        await item.kill()
    try:
        await _start_processes(sess)
    except Exception:
        await stop(sess.id)
        raise
    sess.watch_task = asyncio.create_task(_watch_downloads(sess))
    asyncio.create_task(_guard(sess))
    return sess


async def stop(session_id: str, reason: str = "") -> None:
    async with _lock:
        sess = _sessions.get(session_id)
        if sess is None:
            return
        if reason and not sess.reason:
            sess.reason = reason
        _detach(sess)
        sess.stopped.set()
    await sess.kill()


async def stop_all() -> None:
    async with _lock:
        ids = list(_sessions)
    for session_id in ids:
        await stop(session_id)


async def get_owned(session_id: str, user_id: str) -> BrowserSession | None:
    if not _ID_OK.fullmatch(session_id or ""):
        return None
    async with _lock:
        sess = _sessions.get(session_id)
        if sess is None or sess.user_id != user_id:
            return None
        return sess


def download_dir_of(sess: BrowserSession) -> Path:
    return sess.profile / "Downloads"


async def _note(sess: BrowserSession, text: str) -> None:
    async with _lock:
        if text not in sess.download_notes:
            sess.download_notes.append(text)


async def _watch_downloads(sess: BrowserSession) -> None:
    """完了したファイルを、利用者の画面へ渡せるように控える。"""
    directory = download_dir_of(sess)
    while not sess.stopped.is_set():
        try:
            await asyncio.wait_for(sess.stopped.wait(), timeout=0.5)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await _collect_downloads(sess, directory)
        except Exception:  # noqa: BLE001
            continue


async def _collect_downloads(sess: BrowserSession, directory: Path) -> None:
    if not directory.is_dir():
        return
    for path in list(directory.iterdir()):
        if sess.stopped.is_set() or not path.is_file():
            continue
        name = downloads.safe_download_name(path.name)
        if name is None:
            continue
        size = path.stat().st_size
        await asyncio.sleep(0.4)
        if sess.stopped.is_set() or not path.is_file() or path.stat().st_size != size:
            continue
        if size > downloads.MAX_BYTES:
            path.unlink(missing_ok=True)
            await _note(sess, f"{name} は大きすぎるため保存しませんでした")
            continue
        file_id = secrets.token_urlsafe(12)
        dest = directory / f".ready-{file_id}"
        path.replace(dest)
        async with _lock:
            if len(sess.downloads) >= downloads.MAX_PENDING:
                dest.unlink(missing_ok=True)
                if "受け取り待ちが多いため、新しいダウンロードを捨てました" not in sess.download_notes:
                    sess.download_notes.append("受け取り待ちが多いため、新しいダウンロードを捨てました")
                continue
            sess.downloads[file_id] = (name, dest)


async def list_downloads(session_id: str, user_id: str) -> dict | None:
    async with _lock:
        sess = _sessions.get(session_id)
        if sess is None or sess.user_id != user_id or not _ID_OK.fullmatch(session_id or ""):
            return None
        files = []
        for file_id, (name, path) in sess.downloads.items():
            size = path.stat().st_size if path.is_file() else 0
            files.append({"id": file_id, "name": name, "size": size})
        notes = list(sess.download_notes)
        sess.download_notes.clear()
        return {"files": files, "notes": notes}


async def take_download(session_id: str, user_id: str, file_id: str) -> tuple[str, bytes] | None:
    if not _ID_OK.fullmatch(session_id or "") or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", file_id or ""):
        return None
    async with _lock:
        sess = _sessions.get(session_id)
        if sess is None or sess.user_id != user_id:
            return None
        item = sess.downloads.pop(file_id, None)
    if item is None:
        return None
    name, path = item
    try:
        data = path.read_bytes()
    except OSError:
        return None
    finally:
        path.unlink(missing_ok=True)
    return name, data


async def bridge_audio(sess: BrowserSession, websocket) -> None:
    """再生とマイクを中継する。画面のセッション自体は閉じない。"""
    previous = sess.audio_procs
    sess.audio_gen += 1
    gen = sess.audio_gen
    await audio.stop_procs(previous)
    if not sess.audio_ready:
        await websocket.send_text(
            json.dumps({"type": "error", "message": "音声を起動できませんでした"}, ensure_ascii=False)
        )
        await websocket.close(code=1011)
        return
    mine: list[asyncio.subprocess.Process] = []
    sess.audio_procs = mine

    def current() -> bool:
        return sess.audio_gen == gen and not sess.stopped.is_set()

    await audio.bridge(sess.env, websocket, mine, current)


async def touch(session_id: str, user_id: str) -> bool:
    sess = await get_owned(session_id, user_id)
    if sess is None:
        return False
    sess.touch()
    return True


async def bridge(sess: BrowserSession, websocket) -> None:
    """x11vnc の TCP を WebSocket のバイナリフレームへ中継する。"""
    sess.attached = True
    sess.touch()
    reader, writer = await asyncio.open_connection("127.0.0.1", sess.vnc_port)

    async def ws_to_tcp() -> None:
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                data = message.get("bytes")
                if data is None and message.get("text") is not None:
                    data = message["text"].encode("latin-1", errors="ignore")
                if not data:
                    continue
                writer.write(bytes(data))
                await writer.drain()
        except Exception:  # noqa: BLE001
            return

    async def tcp_to_ws() -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    return
                await websocket.send_bytes(data)
        except Exception:  # noqa: BLE001
            return

    browser_task = asyncio.create_task(ws_to_tcp())
    vnc_task = asyncio.create_task(tcp_to_ws())
    try:
        _done, pending = await asyncio.wait(
            {browser_task, vnc_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(browser_task, vnc_task, return_exceptions=True)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
