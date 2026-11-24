from __future__ import annotations

import os

import pytest

from conftest import load_service_module


@pytest.fixture()
def cpu_limit(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "EMBED_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        monkeypatch.delenv(name, raising=False)
    return load_service_module("embed-app/app/cpu_limit.py")


def test_default_threads_is_two(cpu_limit) -> None:
    assert cpu_limit.embed_num_threads() == 2


def test_explicit_threads(cpu_limit, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_NUM_THREADS", "4")
    assert cpu_limit.embed_num_threads() == 4


@pytest.mark.parametrize("raw", ["0", "-3", "many", ""])
def test_invalid_threads_fall_back(cpu_limit, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("EMBED_NUM_THREADS", raw)
    assert cpu_limit.embed_num_threads() == 2


def test_blas_env_does_not_override(cpu_limit, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMP_NUM_THREADS", "8")
    cpu_limit.apply_blas_env(2)
    assert os.environ["OMP_NUM_THREADS"] == "8"
    assert os.environ["MKL_NUM_THREADS"] == "2"
    assert os.environ["OPENBLAS_NUM_THREADS"] == "2"
