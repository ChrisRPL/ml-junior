"""Flow start API tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from agent.core.events import AgentEvent
from backend.event_store import SQLiteEventStore
from backend.flow_templates import (
    FlowStartError,
    get_builtin_flow_template,
    start_flow,
)
from backend.models import FlowStartRequest
import routes.agent as agent_routes


@pytest.fixture
def memory_event_store():
    store = SQLiteEventStore(":memory:")
    yield store
    store.close()


def test_start_flow_creates_phase_started_event(memory_event_store):
    template = get_builtin_flow_template("literature-overview")
    result = start_flow(
        template,
        "session-test",
        append_callable=memory_event_store.append,
    )

    assert result["template_id"] == "literature-overview"
    assert result["session_id"] == "session-test"
    assert result["status"] == "active"
    assert result["phase_id"] == template.phases[0].id
    assert result["phase_name"] == template.phases[0].name
    assert result["template_version"] == "v1"
    assert result["flow_id"].startswith("flow-")
    assert result["started_at"]

    replayed = memory_event_store.replay("session-test")
    assert len(replayed) == 1
    event = replayed[0]
    assert event.event_type == "phase.started"
    assert event.data["template_id"] == "literature-overview"
    assert event.data["phase_id"] == template.phases[0].id
    assert event.data["to_status"] == "active"
    assert event.data["flow_id"] == result["flow_id"]


def test_start_flow_persists_inputs(memory_event_store):
    template = get_builtin_flow_template("literature-overview")
    result = start_flow(
        template,
        "session-inputs",
        append_callable=memory_event_store.append,
        inputs={"topic": "transformers", "depth": "survey"},
    )

    replayed = memory_event_store.replay("session-inputs")
    assert replayed[0].data["inputs"] == {"topic": "transformers", "depth": "survey"}


def test_start_flow_uses_lowest_order_phase(memory_event_store):
    template = get_builtin_flow_template("fine-tune-model")
    result = start_flow(
        template,
        "session-phase",
        append_callable=memory_event_store.append,
    )

    first_phase = min(template.phases, key=lambda p: p.order)
    assert result["phase_id"] == first_phase.id


def test_start_flow_rejects_empty_template():
    from backend.flow_templates import FlowTemplate

    empty_template = FlowTemplate.model_construct(
        id="empty",
        name="Empty",
        version="v1",
        phases=[],
    )

    with pytest.raises(FlowStartError, match="no phases"):
        start_flow(
            empty_template,
            "session-empty",
            append_callable=lambda e: e,
        )


def test_start_flow_rejects_invalid_append_callable():
    template = get_builtin_flow_template("literature-overview")

    with pytest.raises(FlowStartError, match="valid event"):
        start_flow(
            template,
            "session-bad",
            append_callable=lambda e: "not-an-event",
        )


async def test_flow_start_route_returns_flow_handle(monkeypatch, memory_event_store):
    template_id = "literature-overview"
    session_id = "session-route"

    class FakeSessionManager:
        def __init__(self, store):
            self._store = store

        @property
        def event_store(self):
            return self._store

        def get_session_info(self, session_id):
            return {"is_active": True, "user_id": "dev"}

        def verify_session_access(self, session_id, user_id):
            return True

    monkeypatch.setattr(
        agent_routes, "session_manager", FakeSessionManager(memory_event_store)
    )

    response = await agent_routes.post_flow_start(
        template_id,
        FlowStartRequest(session_id=session_id),
        {"user_id": "dev"},
    )

    assert response.template_id == template_id
    assert response.session_id == session_id
    assert response.status == "active"
    assert response.flow_id.startswith("flow-")
    assert response.phase_id == get_builtin_flow_template(template_id).phases[0].id


async def test_flow_start_route_rejects_unknown_template(monkeypatch, memory_event_store):
    class FakeSessionManager:
        def __init__(self, store):
            self._store = store

        @property
        def event_store(self):
            return self._store

        def get_session_info(self, session_id):
            return {"is_active": True, "user_id": "dev"}

        def verify_session_access(self, session_id, user_id):
            return True

    monkeypatch.setattr(
        agent_routes, "session_manager", FakeSessionManager(memory_event_store)
    )

    with pytest.raises(HTTPException) as exc_info:
        await agent_routes.post_flow_start(
            "unknown-template",
            FlowStartRequest(session_id="session-route"),
            {"user_id": "dev"},
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error"] == "flow_template_not_found"


async def test_flow_start_route_rejects_inactive_session(monkeypatch, memory_event_store):
    class FakeSessionManager:
        def __init__(self, store):
            self._store = store

        @property
        def event_store(self):
            return self._store

        def get_session_info(self, session_id):
            return {"is_active": False, "user_id": "dev"}

        def verify_session_access(self, session_id, user_id):
            return True

    monkeypatch.setattr(
        agent_routes, "session_manager", FakeSessionManager(memory_event_store)
    )

    with pytest.raises(HTTPException) as exc_info:
        await agent_routes.post_flow_start(
            "literature-overview",
            FlowStartRequest(session_id="session-inactive"),
            {"user_id": "dev"},
        )

    assert exc_info.value.status_code == 404


def test_start_flow_preserves_ordering_evidence(memory_event_store):
    template = get_builtin_flow_template("dataset-audit")

    start_flow(
        template,
        "session-order",
        append_callable=memory_event_store.append,
    )

    replayed = memory_event_store.replay("session-order")
    assert len(replayed) == 1
    assert replayed[0].sequence == 1
    assert replayed[0].event_type == "phase.started"


def test_start_flow_event_is_redacted_compatible(memory_event_store):
    template = get_builtin_flow_template("literature-overview")
    result = start_flow(
        template,
        "session-redact",
        append_callable=memory_event_store.append,
    )

    replayed = memory_event_store.replay("session-redact")
    event = replayed[0]
    redacted = event.redacted_copy()
    assert redacted.data["template_id"] == "literature-overview"
    assert redacted.data["phase_id"] == result["phase_id"]
