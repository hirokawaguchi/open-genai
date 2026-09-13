from __future__ import annotations

from conftest import load_service_module


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("SSH_DB_PATH", str(tmp_path / "ssh.db"))
    store = load_service_module("ssh-app/app/store.py")
    store.reset_connection()
    store.init_db()
    return store


def test_create_and_list_enabled_hosts(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path, monkeypatch)
    created, err = store.create_host(
        {
            "name": "保守用",
            "host": "ops.example.lg.jp",
            "port": 22,
            "default_username": "ops",
            "description": "庁内保守",
        }
    )
    assert err is None
    assert created is not None
    assert created["host"] == "ops.example.lg.jp"
    assert created["has_host_key"] is False

    listed = store.list_hosts(include_disabled=False, include_key=False)
    assert len(listed) == 1
    assert "host_key" not in listed[0]


def test_reject_unknown_host_and_bad_port(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path, monkeypatch)
    _created, err = store.create_host({"name": "x", "host": "not a host", "port": 22})
    assert err is not None
    _created, err = store.create_host({"name": "x", "host": "192.168.0.10", "port": 0})
    assert err is not None
    created, err = store.create_host(
        {"name": "docker", "host": "host.docker.internal", "port": 22}
    )
    assert err is None
    assert created is not None
    assert store.get_host("missing") is None


def test_disabled_host_hidden_from_non_admin_list(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path, monkeypatch)
    created, err = store.create_host(
        {"name": "旧", "host": "old.example.jp", "port": 22, "enabled": False}
    )
    assert err is None
    assert store.list_hosts(include_disabled=False, include_key=False) == []
    assert len(store.list_hosts(include_disabled=True, include_key=True)) == 1
    assert created is not None
    updated, err = store.update_host(created["id"], {"enabled": True})
    assert err is None
    assert updated is not None
    assert updated["enabled"] is True


def test_username_validation() -> None:
    store = load_service_module("ssh-app/app/store.py")
    assert store.validate_username("alice") is None
    assert store.validate_username("bad user") is not None
    assert store.validate_username("") is not None


def test_resolve_loopback_to_docker_host(monkeypatch) -> None:
    store = load_service_module("ssh-app/app/store.py")
    assert store.resolve_connect_host("localhost") == "host.docker.internal"
    assert store.resolve_connect_host("127.0.0.1") == "host.docker.internal"
    assert store.resolve_connect_host("wickoid") == "wickoid"
    monkeypatch.setenv("SSH_LOOPBACK_HOST", "gateway.example")
    store2 = load_service_module("ssh-app/app/store.py")
    assert store2.resolve_connect_host("localhost") == "gateway.example"
