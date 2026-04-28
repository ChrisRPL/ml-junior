from __future__ import annotations

import socket
from pathlib import Path

import pytest


EVALS_ROOT = Path(__file__).resolve().parent
FIXTURES_ROOT = EVALS_ROOT / "fixtures"
NON_CI_MARKERS = ("scheduled", "network", "gpu", "requires_hf_token")


def pytest_configure(config):
    for marker in NON_CI_MARKERS:
        config.addinivalue_line(
            "markers",
            f"{marker}: opt-in non-default eval marker; skipped by offline bootstrap tests",
        )


@pytest.fixture(autouse=True)
def _block_network_calls(monkeypatch):
    def blocked_connect(*_args, **_kwargs):
        raise AssertionError("evals bootstrap must not open sockets")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_connect)


@pytest.fixture
def fixtures_root() -> Path:
    return FIXTURES_ROOT
