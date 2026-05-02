from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from agent.core.events import AgentEvent
from backend.event_store import SQLiteEventStore
from backend.job_artifact_refs import (
    ARTIFACT_REF_RECORDED_EVENT,
    artifact_ref_recorded_payload,
)
from backend.models import ArtifactRefRecord, canonical_artifact_ref_uri
from backend.session_store import SESSION_CLOSED, SQLiteSessionStore
import routes.agent as agent_routes
import session_manager as session_module


@pytest.fixture
def artifact_manager(test_config, tmp_path) -> session_module.SessionManager:
    manager = session_module.SessionManager(
        event_store=SQLiteEventStore(tmp_path / "events.sqlite"),
        session_store=SQLiteSessionStore(tmp_path / "sessions.sqlite"),
    )
    manager.config = test_config
    return manager


async def test_artifact_index_route_returns_projected_durable_refs(
    artifact_manager: session_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", artifact_manager)
    artifact_manager.session_store.create(
        session_id="session-a",
        owner_id="alice",
        model="test/model",
    )
    artifact_manager.session_store.create(
        session_id="session-b",
        owner_id="alice",
        model="test/model",
    )

    secret = "hf_artifactsecret123456789"
    artifact_manager.event_store.append(
        make_artifact_event(
            sequence=1,
            artifact_id="artifact-1",
            label="Initial checkpoint",
            uri="https://artifacts.example/old.pt",
        )
    )
    artifact_manager.event_store.append(
        make_artifact_event(
            sequence=2,
            artifact_id="artifact-other-session",
            session_id="session-b",
            label="Other session",
            uri="https://artifacts.example/other.pt",
        )
    )
    artifact_manager.event_store.append(
        make_artifact_event(
            sequence=3,
            artifact_id="artifact-2",
            label="Metrics",
            uri="https://artifacts.example/metrics.json",
        )
    )
    artifact_manager.event_store.append(
        make_artifact_event(
            sequence=4,
            artifact_id="artifact-1",
            label="Best checkpoint",
            uri=f"https://artifacts.example/best.pt?token={secret}",
            producer={"api_key": secret},
        )
    )

    response = await agent_routes.list_session_artifacts(
        "session-a",
        {"user_id": "alice"},
    )
    payload = [record.model_dump(mode="json") for record in response]
    payload_text = json.dumps(payload)

    assert any(
        route.path == "/api/session/{session_id}/artifacts"
        and "GET" in route.methods
        for route in agent_routes.router.routes
    )
    assert [item["artifact_id"] for item in payload] == [
        "artifact-2",
        "artifact-1",
    ]
    assert payload[0]["label"] == "Metrics"
    assert payload[1]["label"] == "Best checkpoint"
    assert payload[1]["ref_uri"] == canonical_artifact_ref_uri(
        "session-a",
        "artifact-1",
    )
    assert "artifact-other-session" not in payload_text
    assert secret not in payload_text
    assert "[REDACTED]" in payload_text


async def test_artifact_index_route_handles_empty_durable_session(
    artifact_manager: session_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", artifact_manager)
    artifact_manager.session_store.create(
        session_id="session-empty",
        owner_id="alice",
        model="test/model",
    )

    response = await agent_routes.list_session_artifacts(
        "session-empty",
        {"user_id": "alice"},
    )

    assert response == []


async def test_artifact_index_route_returns_refs_for_closed_durable_session(
    artifact_manager: session_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", artifact_manager)
    artifact_manager.session_store.create(
        session_id="session-closed",
        owner_id="alice",
        model="test/model",
        status=SESSION_CLOSED,
    )
    artifact_manager.event_store.append(
        make_artifact_event(
            sequence=1,
            session_id="session-closed",
            artifact_id="artifact-closed",
            label="Closed session report",
            uri="https://artifacts.example/report.json",
        )
    )

    response = await agent_routes.list_session_artifacts(
        "session-closed",
        {"user_id": "alice"},
    )

    assert [record.artifact_id for record in response] == ["artifact-closed"]
    assert response[0].label == "Closed session report"


async def test_artifact_detail_route_returns_latest_projected_ref(
    artifact_manager: session_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", artifact_manager)
    artifact_manager.session_store.create(
        session_id="session-a",
        owner_id="alice",
        model="test/model",
    )
    artifact_manager.session_store.create(
        session_id="session-b",
        owner_id="alice",
        model="test/model",
    )

    secret = "hf_artifactdetailsecret123456789"
    artifact_manager.event_store.append(
        make_artifact_event(
            sequence=1,
            artifact_id="artifact-1",
            label="Initial checkpoint",
            uri="https://artifacts.example/old.pt",
        )
    )
    artifact_manager.event_store.append(
        make_artifact_event(
            sequence=2,
            artifact_id="artifact-1",
            session_id="session-b",
            label="Other session checkpoint",
            uri="https://artifacts.example/other.pt",
        )
    )
    artifact_manager.event_store.append(
        make_artifact_event(
            sequence=3,
            artifact_id="artifact-1",
            label="Best checkpoint",
            uri=f"https://artifacts.example/best.pt?token={secret}",
            producer={"api_key": secret},
        )
    )

    response = await agent_routes.get_session_artifact(
        "session-a",
        "artifact-1",
        {"user_id": "alice"},
    )
    payload = response.model_dump(mode="json")
    payload_text = json.dumps(payload)

    assert any(
        route.path == "/api/session/{session_id}/artifacts/{artifact_id}"
        and "GET" in route.methods
        for route in agent_routes.router.routes
    )
    assert payload["artifact_id"] == "artifact-1"
    assert payload["label"] == "Best checkpoint"
    assert payload["source_event_sequence"] == 3
    assert payload["ref_uri"] == canonical_artifact_ref_uri("session-a", "artifact-1")
    assert "Initial checkpoint" not in payload_text
    assert "Other session checkpoint" not in payload_text
    assert secret not in payload_text
    assert "[REDACTED]" in payload_text


async def test_artifact_detail_route_enforces_access_and_missing_artifact(
    artifact_manager: session_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", artifact_manager)
    artifact_manager.session_store.create(
        session_id="session-a",
        owner_id="alice",
        model="test/model",
    )
    artifact_manager.event_store.append(
        make_artifact_event(
            sequence=1,
            artifact_id="artifact-1",
            label="Checkpoint",
            uri="https://artifacts.example/model.pt",
        )
    )

    with pytest.raises(HTTPException) as denied:
        await agent_routes.get_session_artifact(
            "session-a",
            "artifact-1",
            {"user_id": "bob"},
        )
    with pytest.raises(HTTPException) as missing_session:
        await agent_routes.get_session_artifact(
            "missing",
            "artifact-1",
            {"user_id": "alice"},
        )
    with pytest.raises(HTTPException) as missing_artifact:
        await agent_routes.get_session_artifact(
            "session-a",
            "missing-artifact",
            {"user_id": "alice"},
        )

    assert denied.value.status_code == 403
    assert missing_session.value.status_code == 404
    assert missing_artifact.value.status_code == 404
    assert missing_artifact.value.detail == "Artifact not found"


async def test_artifact_index_route_enforces_session_access(
    artifact_manager: session_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", artifact_manager)
    artifact_manager.session_store.create(
        session_id="session-a",
        owner_id="alice",
        model="test/model",
    )

    with pytest.raises(HTTPException) as denied:
        await agent_routes.list_session_artifacts("session-a", {"user_id": "bob"})
    with pytest.raises(HTTPException) as missing:
        await agent_routes.list_session_artifacts("missing", {"user_id": "alice"})

    assert denied.value.status_code == 403
    assert missing.value.status_code == 404


def make_artifact_event(
    *,
    sequence: int,
    artifact_id: str,
    label: str,
    uri: str,
    session_id: str = "session-a",
    producer: dict | None = None,
) -> AgentEvent:
    record = ArtifactRefRecord.model_validate(
        {
            "session_id": session_id,
            "artifact_id": artifact_id,
            "source_event_sequence": sequence,
            "type": "model_checkpoint",
            "source": "remote_uri",
            "ref_uri": canonical_artifact_ref_uri(session_id, artifact_id),
            "locator": {"type": "remote_uri", "uri": uri},
            "uri": uri,
            "label": label,
            "producer": producer,
            "metadata": {"sequence": sequence},
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        }
    )
    return AgentEvent(
        id=f"event-{session_id}-{sequence}",
        session_id=session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=ARTIFACT_REF_RECORDED_EVENT,
        data=artifact_ref_recorded_payload(record),
    )
