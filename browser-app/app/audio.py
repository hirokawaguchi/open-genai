"""セッションごとの音声。

Chromium の再生はスピーカー用の仮想デバイスから取り、見ている PC へ渡す。
PC のマイクはマイク用の仮想デバイスへ書き、Chromium の入力にする。
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from collections.abc import Callable
from pathlib import Path

RATE = 48000
PLAYBACK_CHANNELS = 2
MIC_CHANNELS = 1
FRAME_MS = 20
_MAX_MIC_BYTES = 64 * 1024


def playback_frame_bytes() -> int:
    return RATE * PLAYBACK_CHANNELS * 2 * FRAME_MS // 1000


def pulse_socket(profile: Path) -> Path:
    return profile / "run" / "pulse" / "native"


def pulse_command(socket: Path) -> list[str]:
    speakers = "sink_name=speakers rate=48000 channels=2"
    mic_sink = "sink_name=mic_in rate=48000 channels=1"
    mic_source = "master=mic_in.monitor source_name=microphone"
    return [
        "pulseaudio",
        "--daemonize=no",
        "--exit-idle-time=-1",
        "--use-pid-file=no",
        "--log-target=stderr",
        "-n",
        f"--load=module-native-protocol-unix auth-anonymous=1 socket={socket}",
        f"--load=module-null-sink {speakers}",
        f"--load=module-null-sink {mic_sink}",
        f"--load=module-remap-source {mic_source}",
    ]


def apply_env(profile: Path, env: dict[str, str]) -> Path:
    socket = pulse_socket(profile)
    runtime = socket.parent.parent
    runtime.mkdir(parents=True, exist_ok=True)
    os.chmod(runtime, 0o700)
    socket.parent.mkdir(parents=True, exist_ok=True)
    env["XDG_RUNTIME_DIR"] = str(runtime)
    env["PULSE_SERVER"] = f"unix:{socket}"
    env["PULSE_LATENCY_MSEC"] = "30"
    return socket


async def stop_procs(procs: list[asyncio.subprocess.Process]) -> None:
    for proc in list(procs):
        if proc.returncode is None and proc.pid:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for proc in list(procs):
        if proc.returncode is not None:
            continue
        try:
            await asyncio.wait_for(proc.wait(), timeout=1)
        except asyncio.TimeoutError:
            if proc.pid:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


async def _pactl(env: dict[str, str], *args: str) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "pactl",
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
    except FileNotFoundError:
        return
    await proc.wait()


async def launch(profile: Path, env: dict[str, str]) -> asyncio.subprocess.Process | None:
    """PulseAudio をセッションの中で起動する。失敗しても画面は開ける。"""
    socket = apply_env(profile, env)
    try:
        proc = await asyncio.create_subprocess_exec(
            *pulse_command(socket),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError:
        return None
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if proc.returncode is not None:
            return None
        if socket.exists():
            await _pactl(env, "set-default-sink", "speakers")
            await _pactl(env, "set-default-source", "microphone")
            return proc
        await asyncio.sleep(0.1)
    await stop_procs([proc])
    return None


async def bridge(
    env: dict[str, str],
    websocket,
    procs: list[asyncio.subprocess.Process],
    current: Callable[[], bool],
) -> None:
    """再生の PCM を送り、マイクの PCM を仮想マイクへ書く。"""
    try:
        play = await asyncio.create_subprocess_exec(
            "parec",
            "-d",
            "speakers.monitor",
            "--raw",
            "--format=s16le",
            f"--rate={RATE}",
            f"--channels={PLAYBACK_CHANNELS}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        mic = await asyncio.create_subprocess_exec(
            "pacat",
            "--playback",
            "-d",
            "mic_in",
            "--raw",
            "--format=s16le",
            f"--rate={RATE}",
            f"--channels={MIC_CHANNELS}",
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError:
        await websocket.send_text(
            json.dumps({"type": "error", "message": "音声を起動できませんでした"}, ensure_ascii=False)
        )
        return
    procs.extend((play, mic))
    await websocket.send_text(
        json.dumps(
            {
                "type": "ready",
                "rate": RATE,
                "channels": PLAYBACK_CHANNELS,
                "format": "s16le",
                "micRate": RATE,
                "micChannels": MIC_CHANNELS,
            },
            ensure_ascii=False,
        )
    )

    async def pump_out() -> None:
        assert play.stdout is not None
        frame = playback_frame_bytes()
        while current():
            data = await play.stdout.read(frame)
            if not data or not current():
                return
            await websocket.send_bytes(data)

    async def pump_in() -> None:
        assert mic.stdin is not None
        while current():
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect" or not current():
                return
            data = message.get("bytes")
            if not data or len(data) > _MAX_MIC_BYTES:
                continue
            if len(data) % 2:
                data = data[:-1]
            if not data:
                continue
            mic.stdin.write(data)
            await mic.stdin.drain()

    tasks = {asyncio.create_task(pump_out()), asyncio.create_task(pump_in())}
    try:
        _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        await stop_procs([play, mic])
