"""ノートの対話を、棟・チーム・利用者の組で分ける。

共有の作業ディレクトリは持たない。Hermes のイメージが指定され、
NOTEBOOK_HERMES_DOCKER=1 のときだけ、一時ディスクだけのコンテナを起動する。
イメージが無いあいだは、同じ道具をノートのプロセスで実行する。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass

MAX_SESSIONS = int(os.environ.get("NOTEBOOK_AGENT_MAX", "4"))
IDLE_SECONDS = int(os.environ.get("NOTEBOOK_AGENT_IDLE_SECONDS", "1800"))
_FORBIDDEN = ("/storage", "/mail", "/work", "/models")


class PoolFull(Exception):
    pass


class HermesUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SessionKey:
    tenant: str
    team: str
    user: str

    def label(self) -> str:
        return f"{self.tenant}|{self.team}|{self.user}"


def assert_mounts(volumes: dict) -> None:
    """共有の作業場所、ファイルサーバ、モデルの重みを載せない。"""
    for host, spec in volumes.items():
        bind = ""
        if isinstance(spec, dict):
            bind = str(spec.get("bind") or "")
        text = f"{host} {bind}".lower()
        if ".gguf" in text or "mmproj" in text or text.rstrip("/").endswith("/models"):
            raise ValueError("agent session must not mount model weights")
        path = bind.rstrip("/") or "/"
        if any(path == root or path.startswith(root + "/") for root in _FORBIDDEN):
            raise ValueError("agent session must not mount a shared work directory")
        if volumes:
            raise ValueError("agent session must not mount a shared work directory")


def container_spec(key: SessionKey, image: str) -> dict:
    digest = hashlib.sha256(key.label().encode()).hexdigest()[:16]
    return {
        "name": f"og-hermes-{digest}",
        "image": image,
        "volumes": {},
        "tmpfs": {"/root/.hermes": "rw,size=64m", "/tmp": "rw,size=64m"},
        "network": os.environ.get("NOTEBOOK_HERMES_NETWORK", "open-genai_default"),
    }


class Pool:
    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def acquire(self, key: SessionKey) -> str:
        now = time.monotonic()
        stale = [k for k, touched in self._seen.items() if now - touched > IDLE_SECONDS]
        for item in stale:
            self._seen.pop(item, None)
        label = key.label()
        if label not in self._seen and len(self._seen) >= MAX_SESSIONS:
            raise PoolFull("同時に動かせる対話の上限です。しばらくしてからもう一度送ってください。")
        self._seen[label] = now
        spec = container_spec(key, os.environ.get("NOTEBOOK_HERMES_IMAGE", "").strip() or "unset")
        assert_mounts(spec["volumes"])
        image = os.environ.get("NOTEBOOK_HERMES_IMAGE", "").strip()
        if image and os.environ.get("NOTEBOOK_HERMES_DOCKER") == "1":
            _start(spec)
            return "container"
        return "inprocess"


def _start(spec: dict) -> None:
    cmd = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        spec["name"],
        "--network",
        spec["network"],
        "--tmpfs",
        "/root/.hermes:rw,size=64m",
        "--tmpfs",
        "/tmp:rw,size=64m",
        "-e",
        "HERMES_EMBEDDED=1",
        spec["image"],
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise HermesUnavailable("Hermes のコンテナを起動できませんでした。") from e


pool = Pool()
