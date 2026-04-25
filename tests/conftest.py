"""Shared pytest harness for offline ML Junior characterization tests."""

from __future__ import annotations

import asyncio
import inspect
import socket
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from agent.config import Config
from agent.core.session import Event


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

for path in (PROJECT_ROOT, BACKEND_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_network: permit real socket connections for an explicitly networked test",
    )


@pytest.fixture(autouse=True)
def _block_network_calls(monkeypatch, request):
    """Block accidental network sockets in the offline Phase 0 suite."""

    if request.node.get_closest_marker("allow_network"):
        return

    def blocked_connect(*_args, **_kwargs):
        raise AssertionError(
            "Network access is disabled in tests. Mark the test with "
            "@pytest.mark.allow_network only for explicit network smoke tests."
        )

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_connect)


class FakeToolRouter:
    """Small tool router for agent-loop tests.

    The real router pulls in network-capable HF/MCP tooling. Phase 0 tests use
    this fixture to characterize the loop without network access.
    """

    def __init__(
        self,
        handlers: dict[str, Callable[[dict[str, Any]], Awaitable[tuple[str, bool]]]]
        | None = None,
        specs: list[dict[str, Any]] | None = None,
    ) -> None:
        self.handlers = handlers or {}
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []
        self._specs = specs or [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"Fake {name} tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for name in self.handlers
        ]

    def get_tool_specs_for_llm(self) -> list[dict[str, Any]]:
        return self._specs

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session: Any = None,
        tool_call_id: str | None = None,
    ) -> tuple[str, bool]:
        self.calls.append((tool_name, arguments, tool_call_id))
        handler = self.handlers.get(tool_name)
        if handler is None:
            return f"Unknown tool: {tool_name}", False
        return await handler(arguments)


@pytest.fixture
def test_config() -> Config:
    """Config that avoids autosave and keeps loop tests bounded."""

    return Config(
        model_name="test/model",
        mcpServers={},
        save_sessions=False,
        max_iterations=3,
        reasoning_effort=None,
    )


@pytest.fixture
def event_queue() -> asyncio.Queue:
    return asyncio.Queue()


@pytest.fixture
def fake_tool_router() -> FakeToolRouter:
    async def echo(args: dict[str, Any]) -> tuple[str, bool]:
        return f"echo:{args}", True

    return FakeToolRouter({"echo": echo})


async def collect_events(queue: asyncio.Queue) -> list[Event]:
    """Drain all currently queued events without blocking."""

    events: list[Event] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


@pytest.fixture
def event_collector() -> Callable[[asyncio.Queue], Awaitable[list[Event]]]:
    return collect_events


def pytest_pyfunc_call(pyfuncitem):
    """Run async test functions without requiring an async pytest plugin."""

    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(test_func(**kwargs))
    return True
