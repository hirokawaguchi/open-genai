"""生成中の手順名。画面が待ちのあいだに読む。"""

from __future__ import annotations

from threading import Lock

_lock = Lock()
_steps: dict[str, list[str]] = {}
_turns: dict[str, str] = {}


def begin(session_id: str, turn_id: str = "") -> None:
    with _lock:
        _turns[session_id] = turn_id
        _steps[session_id] = []


def note(session_id: str, name: str) -> None:
    text = (name or "").strip()
    if not text:
        return
    with _lock:
        steps = _steps.setdefault(session_id, [])
        if steps and steps[-1] == text:
            return
        steps.append(text)


def snapshot(session_id: str, turn_id: str = "") -> list[str]:
    with _lock:
        if turn_id and _turns.get(session_id) != turn_id:
            return []
        return list(_steps.get(session_id) or [])
