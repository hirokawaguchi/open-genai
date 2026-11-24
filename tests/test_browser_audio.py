from pathlib import Path

from conftest import load_service_module

audio = load_service_module("browser-app/app/audio.py")


def test_pulse_command_uses_session_socket_and_virtual_devices(tmp_path: Path) -> None:
    socket = audio.pulse_socket(tmp_path)
    command = audio.pulse_command(socket)
    text = " ".join(command)
    assert "pulseaudio" in command[0]
    assert f"socket={socket}" in text
    assert "sink_name=speakers" in text
    assert "sink_name=mic_in" in text
    assert "source_name=microphone" in text
    assert audio.playback_frame_bytes() == 48000 * 2 * 2 * 20 // 1000


def test_apply_env_points_pulse_at_the_profile(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    socket = audio.apply_env(tmp_path, env)
    assert env["PULSE_SERVER"] == f"unix:{socket}"
    assert Path(env["XDG_RUNTIME_DIR"]).is_dir()
    assert socket.parent.is_dir()
