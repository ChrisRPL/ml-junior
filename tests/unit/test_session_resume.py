"""Server-side session metadata resume tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from agent.core.events import AgentEvent
from backend.event_store import SQLiteEventStore
from backend.operation_store import SQLiteOperationStore
from backend.session_store import SQLiteSessionStore
from backend.models import SessionResumeMetadata
import routes.agent as agent_routes


@pytest.fixture
def resume_stores(tmp_path):
    event_store = SQLiteEventStore(":memory:")
    session_store = SQLiteSessionStore(":memory:")
    operation_store = SQLiteOperationStore(":memory:")
    yield event_store, session_store, operation_store
    event_store.close()
    session_store.close()
    operation_store.close()


class FakeSessionManager:
    def __init__(self, event_store, session_store, operation_store):
        self._event_store = event_store
        self._session_store = session_store
        self._operation_store = operation_store

    @property
    def event_store(self):
        return self._event_store

    @property
    def session_store(self):
        return self._session_store

    @property
    def operation_store(self):
        return self._operation_store

    def get_session_info(self, session_id):
        return {"is_active": True, "user_id": "dev"}

    def verify_session_access(self, session_id, user_id):
        return True

    def get_session_resume_metadata(self, session_id):
        from backend.session_manager import SessionManager
        # Use the actual implementation by calling it directly
        # We'll build a minimal instance just for this method
        manager = SessionManager.__new__(SessionManager)
        manager._event_store = self._event_store
        manager._session_store = self._session_store
        manager._operation_store = self._operation_store
        return manager.get_session_resume_metadata(session_id)


def test_resume_metadata_reconstructs_from_durable_stores(resume_stores):
    event_store, session_store, operation_store = resume_stores

    session_store.create(
        session_id="session-resume",
        owner_id="user-1",
        model="claude-3-5-sonnet",
        pending_approval_refs=[{"tool_call_id": "tc-1"}],
        active_job_refs=[{"job_id": "job-1"}, {"job_id": "job-2"}],
    )

    event_store.append(
        AgentEvent(
            session_id="session-resume",
            sequence=1,
            event_type="phase.started",
            data={
                "session_id": "session-resume",
                "project_id": "session-resume",
                "template_id": "literature-overview",
                "template_version": "v1",
                "phase_id": "phase-1",
                "phase_name": "Review Literature",
                "phase_order": 0,
                "from_status": "not_started",
                "to_status": "active",
                "allowed": True,
                "flow_id": "flow-abc123",
                "inputs": {},
                "started_at": "2026-05-02T12:00:00+00:00",
            },
        )
    )

    operation_store.create(
        operation_id="op-1",
        session_id="session-resume",
        operation_type="user_input",
        payload={"text": "hello"},
        status="succeeded",
    )

    manager = FakeSessionManager(event_store, session_store, operation_store)
    metadata = manager.get_session_resume_metadata("session-resume")

    assert metadata is not None
    assert metadata["session_id"] == "session-resume"
    assert metadata["owner_id"] == "user-1"
    assert metadata["model"] == "claude-3-5-sonnet"
    assert metadata["status"] == "active"
    assert metadata["last_event_sequence"] == 1
    assert metadata["last_operation_id"] is not None
    assert len(metadata["attached_flows"]) == 1
    assert metadata["attached_flows"][0]["flow_id"] == "flow-abc123"
    assert metadata["attached_flows"][0]["template_id"] == "literature-overview"
    assert metadata["workflow_phase_id"] == "phase-1"
    assert metadata["workflow_phase_status"] == "active"
    assert metadata["pending_approval_count"] == 1
    assert metadata["active_job_count"] == 2
    assert metadata["can_resume"] is False
    assert metadata["resume_reason"] == "server_side_resume_not_implemented"


def test_resume_metadata_returns_none_for_missing_session(resume_stores):
    event_store, session_store, operation_store = resume_stores
    manager = FakeSessionManager(event_store, session_store, operation_store)

    metadata = manager.get_session_resume_metadata("missing-session")
    assert metadata is None


def test_resume_metadata_empty_for_fresh_session(resume_stores):
    event_store, session_store, operation_store = resume_stores
    session_store.create(
        session_id="session-fresh",
        owner_id="user-1",
        model="claude-3-5-sonnet",
    )

    manager = FakeSessionManager(event_store, session_store, operation_store)
    metadata = manager.get_session_resume_metadata("session-fresh")

    assert metadata is not None
    assert metadata["last_event_sequence"] == 0
    assert metadata["last_operation_id"] is None
    assert metadata["attached_flows"] == []
    assert metadata["pending_approval_count"] == 0
    assert metadata["active_job_count"] == 0


def test_resume_metadata_survives_store_restart(tmp_path):
    db_path = tmp_path / "resume.sqlite"
    event_store = SQLiteEventStore(db_path)
    session_store = SQLiteSessionStore(db_path)
    operation_store = SQLiteOperationStore(db_path)

    session_store.create(
        session_id="session-survive",
        owner_id="user-1",
        model="gpt-4",
        pending_approval_refs=[{"tool_call_id": "tc-1"}],
    )
    event_store.append(
        AgentEvent(
            session_id="session-survive",
            sequence=1,
            event_type="phase.started",
            data={
                "session_id": "session-survive",
                "template_id": "dataset-audit",
                "phase_id": "phase-1",
                "flow_id": "flow-survive",
                "started_at": "2026-05-02T12:00:00+00:00",
            },
        )
    )

    event_store.close()
    session_store.close()
    operation_store.close()

    # Simulate restart by reopening stores
    event_store2 = SQLiteEventStore(db_path)
    session_store2 = SQLiteSessionStore(db_path)
    operation_store2 = SQLiteOperationStore(db_path)

    manager = FakeSessionManager(event_store2, session_store2, operation_store2)
    metadata = manager.get_session_resume_metadata("session-survive")

    assert metadata is not None
    assert metadata["session_id"] == "session-survive"
    assert metadata["model"] == "gpt-4"
    assert metadata["last_event_sequence"] == 1
    assert len(metadata["attached_flows"]) == 1
    assert metadata["attached_flows"][0]["flow_id"] == "flow-survive"
    assert metadata["pending_approval_count"] == 1

    event_store2.close()
    session_store2.close()
    operation_store2.close()


async def test_resume_route_returns_metadata(monkeypatch, resume_stores):
    event_store, session_store, operation_store = resume_stores
    session_store.create(
        session_id="session-route",
        owner_id="dev",
        model="claude-3-5-sonnet",
    )

    manager = FakeSessionManager(event_store, session_store, operation_store)
    monkeypatch.setattr(agent_routes, "session_manager", manager)

    response = await agent_routes.get_session_resume("session-route", {"user_id": "dev"})

    assert response.session_id == "session-route"
    assert response.model == "claude-3-5-sonnet"
    assert response.can_resume is False


async def test_resume_route_returns_404_for_missing_session(monkeypatch, resume_stores):
    event_store, session_store, operation_store = resume_stores
    manager = FakeSessionManager(event_store, session_store, operation_store)
    monkeypatch.setattr(agent_routes, "session_manager", manager)

    with pytest.raises(HTTPException) as exc_info:
        await agent_routes.get_session_resume("missing-session", {"user_id": "dev"})

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error"] == "session_resume_not_found"


async def test_resume_route_rejects_unauthorized_session(monkeypatch, resume_stores):
    event_store, session_store, operation_store = resume_stores

    class UnauthorizedManager(FakeSessionManager):
        def verify_session_access(self, session_id, user_id):
            return False

    manager = UnauthorizedManager(event_store, session_store, operation_store)
    monkeypatch.setattr(agent_routes, "session_manager", manager)

    with pytest.raises(HTTPException) as exc_info:
        await agent_routes.get_session_resume("session-route", {"user_id": "other"})

    assert exc_info.value.status_code == 403
