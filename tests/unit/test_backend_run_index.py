from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from agent.core.events import AgentEvent
from backend.event_store import SQLiteEventStore
from backend.experiment_ledger import (
    EXPERIMENT_RUN_RECORDED_EVENT,
    experiment_run_recorded_payload,
)
from backend.models import ExperimentRunRecord
from backend.session_store import SESSION_CLOSED, SQLiteSessionStore
import routes.agent as agent_routes
import session_manager as session_module


@pytest.fixture
def run_manager(test_config, tmp_path) -> session_module.SessionManager:
    manager = session_module.SessionManager(
        event_store=SQLiteEventStore(tmp_path / "events.sqlite"),
        session_store=SQLiteSessionStore(tmp_path / "sessions.sqlite"),
    )
    manager.config = test_config
    return manager


async def test_run_index_route_returns_projected_durable_runs(
    run_manager: session_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", run_manager)
    run_manager.session_store.create(
        session_id="session-a",
        owner_id="alice",
        model="test/model",
    )
    run_manager.session_store.create(
        session_id="session-b",
        owner_id="alice",
        model="test/model",
    )

    secret = "hf_runsecret123456789"
    run_manager.event_store.append(
        make_run_event(
            sequence=3,
            run_id="run-2",
            hypothesis="Compare lower learning rate",
            status="completed",
            tracking_uri=f"https://tracking.example/runs/run-2?token={secret}",
        )
    )
    run_manager.event_store.append(
        make_run_event(
            sequence=1,
            run_id="run-other-session",
            session_id="session-b",
            hypothesis="Other session run",
            status="completed",
            tracking_uri="https://tracking.example/runs/other",
        )
    )
    run_manager.event_store.append(
        make_run_event(
            sequence=2,
            run_id="run-1",
            hypothesis="Train baseline",
            status="running",
            tracking_uri="https://tracking.example/runs/run-1",
        )
    )

    response = await agent_routes.list_session_runs(
        "session-a",
        {"user_id": "alice"},
    )
    payload = [record.model_dump(mode="json") for record in response]
    payload_text = json.dumps(payload)

    assert any(
        route.path == "/api/session/{session_id}/runs"
        and "GET" in route.methods
        for route in agent_routes.router.routes
    )
    assert [item["run_id"] for item in payload] == ["run-1", "run-2"]
    assert payload[0]["hypothesis"] == "Train baseline"
    assert payload[1]["status"] == "completed"
    assert "run-other-session" not in payload_text
    assert secret not in payload_text
    assert "[REDACTED]" in payload_text


async def test_run_index_route_handles_empty_durable_session(
    run_manager: session_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", run_manager)
    run_manager.session_store.create(
        session_id="session-empty",
        owner_id="alice",
        model="test/model",
    )

    response = await agent_routes.list_session_runs(
        "session-empty",
        {"user_id": "alice"},
    )

    assert response == []


async def test_run_index_route_returns_runs_for_closed_durable_session(
    run_manager: session_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", run_manager)
    run_manager.session_store.create(
        session_id="session-closed",
        owner_id="alice",
        model="test/model",
        status=SESSION_CLOSED,
    )
    run_manager.event_store.append(
        make_run_event(
            sequence=1,
            session_id="session-closed",
            run_id="run-closed",
            hypothesis="Closed session run",
            status="verified",
            tracking_uri="https://tracking.example/runs/closed",
        )
    )

    response = await agent_routes.list_session_runs(
        "session-closed",
        {"user_id": "alice"},
    )

    assert [record.run_id for record in response] == ["run-closed"]
    assert response[0].hypothesis == "Closed session run"


async def test_run_index_route_enforces_session_access(
    run_manager: session_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", run_manager)
    run_manager.session_store.create(
        session_id="session-a",
        owner_id="alice",
        model="test/model",
    )

    with pytest.raises(HTTPException) as denied:
        await agent_routes.list_session_runs("session-a", {"user_id": "bob"})
    with pytest.raises(HTTPException) as missing:
        await agent_routes.list_session_runs("missing", {"user_id": "alice"})

    assert denied.value.status_code == 403
    assert missing.value.status_code == 404


def make_run_event(
    *,
    sequence: int,
    run_id: str,
    hypothesis: str,
    status: str,
    tracking_uri: str,
    session_id: str = "session-a",
) -> AgentEvent:
    record = ExperimentRunRecord.model_validate(
        {
            "session_id": session_id,
            "run_id": run_id,
            "hypothesis": hypothesis,
            "status": status,
            "source_event_sequence": sequence,
            "phase_id": "train",
            "config": {"learning_rate": 0.001, "token": tracking_uri},
            "seed": 1234,
            "runtime": {
                "provider": "local",
                "started_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
                "hardware": {"accelerator": "cpu"},
            },
            "metrics": [
                {
                    "name": "accuracy",
                    "value": 0.91,
                    "source": "tool",
                }
            ],
            "external_tracking_refs": [
                {
                    "tracking_id": f"tracking-{run_id}",
                    "source": "external_tracking",
                    "provider": "tracking-provider",
                    "uri": tracking_uri,
                }
            ],
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        }
    )
    return AgentEvent(
        id=f"event-{session_id}-{sequence}",
        session_id=session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=EXPERIMENT_RUN_RECORDED_EVENT,
        data=experiment_run_recorded_payload(record),
    )
