from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent.core.events import AgentEvent, EVENT_PAYLOAD_MODELS
from backend.event_store import SQLiteEventStore
from backend.models import (
    PhaseState,
    WorkflowCompatibility,
    WorkflowObjective,
    WorkflowResumeState,
    WorkflowState,
)
from backend.project_continuity import (
    checkpoint_created_payload,
    checkpoint_from_event,
    fork_point_created_payload,
    fork_point_from_event,
    generate_handoff_summary,
    handoff_summary_created_payload,
)


def make_event(
    *,
    sequence: int,
    event_type: str,
    data: dict,
    session_id: str = "session-a",
) -> AgentEvent:
    return AgentEvent(
        id=f"event-{sequence}",
        session_id=session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=data,
    )


def make_workflow_state(
    *,
    objective: WorkflowObjective | None = None,
    phase: PhaseState | None = None,
    blockers: list[dict] | None = None,
    active_jobs: list[dict] | None = None,
    evidence_summary: dict | None = None,
    last_event_sequence: int = 0,
) -> WorkflowState:
    return WorkflowState(
        snapshot_version=1,
        session_id="session-a",
        project_id="session:session-a",
        status="idle",
        objective=objective or WorkflowObjective(),
        phase=phase
        or PhaseState(
            id="compatibility-session",
            label="Session",
            status="placeholder",
        ),
        plan=[],
        blockers=blockers or [],
        pending_approvals=[],
        active_jobs=active_jobs or [],
        operation_refs=[],
        human_requests=[],
        budget={},
        evidence_summary=evidence_summary or {},
        live_tracking_refs=[],
        resume=WorkflowResumeState(event_sequence=last_event_sequence),
        compatibility=WorkflowCompatibility(stale=False, missing_producers=[]),
        last_event_sequence=last_event_sequence,
        updated_at=None,
    )


def test_continuity_event_payload_names_are_modeled():
    assert EVENT_PAYLOAD_MODELS["checkpoint.created"]
    assert EVENT_PAYLOAD_MODELS["fork_point.created"]
    assert EVENT_PAYLOAD_MODELS["handoff.summary_created"]


def test_checkpoint_created_event_validates_metadata_only_payload():
    event = make_event(
        sequence=3,
        event_type="checkpoint.created",
        data={
            "session_id": "session-a",
            "checkpoint_id": "checkpoint-1",
            "reason": "before approval",
            "phase_id": "train",
            "source_event_sequence": 2,
            "refs": [
                {"type": "phase", "phase_id": "train"},
                {"type": "event_sequence", "sequence": 2},
            ],
        },
    )

    checkpoint = checkpoint_from_event(event)

    assert checkpoint.model_dump(exclude_none=True) == {
        "session_id": "session-a",
        "checkpoint_id": "checkpoint-1",
        "reason": "before approval",
        "phase_id": "train",
        "source_event_sequence": 2,
        "refs": [
            {"type": "phase", "phase_id": "train"},
            {"type": "event_sequence", "sequence": 2},
        ],
    }

    with pytest.raises(ValidationError):
        make_event(
            sequence=4,
            event_type="checkpoint.created",
            data={
                "session_id": "session-a",
                "checkpoint_id": "checkpoint-2",
                "reason": "bad payload",
                "metrics": {"accuracy": 0.99},
            },
        )


def test_fork_point_accepts_only_typed_refs_without_creating_records():
    event = make_event(
        sequence=5,
        event_type="fork_point.created",
        data={
            "session_id": "session-a",
            "fork_point_id": "fork-1",
            "reason": "try alternate dataset",
            "source_event_sequence": 4,
            "refs": [
                {"type": "phase", "phase_id": "eval"},
                {"type": "run", "run_id": "run-7"},
                {"type": "code_snapshot", "snapshot_id": "code-3"},
                {"type": "dataset_snapshot", "snapshot_id": "data-2"},
                {"type": "model_checkpoint", "checkpoint_id": "model-5"},
                {"type": "event_sequence", "sequence": 4},
            ],
        },
    )

    fork_point = fork_point_from_event(event)

    assert [ref.type for ref in fork_point.refs] == [
        "phase",
        "run",
        "code_snapshot",
        "dataset_snapshot",
        "model_checkpoint",
        "event_sequence",
    ]
    assert "created_record" not in fork_point.model_dump()

    with pytest.raises(ValidationError):
        make_event(
            sequence=6,
            event_type="fork_point.created",
            data={
                "session_id": "session-a",
                "fork_point_id": "fork-2",
                "refs": [{"type": "dataset", "id": "implicit-create"}],
            },
        )


def test_checkpoint_created_payload_builder_validates_supported_refs():
    payload = checkpoint_created_payload(
        session_id="session-a",
        checkpoint_id="checkpoint-refs",
        reason="before publish",
        phase_id="publish",
        source_event_sequence=42,
        refs=[
            {"type": "phase", "phase_id": "publish"},
            {"type": "run", "run_id": "run-7"},
            {"type": "code_snapshot", "snapshot_id": "code-3"},
            {"type": "dataset_snapshot", "snapshot_id": "data-2"},
            {"type": "model_checkpoint", "checkpoint_id": "model-5"},
            {"type": "event_sequence", "sequence": 42},
        ],
    )

    event = make_event(
        sequence=43,
        event_type="checkpoint.created",
        data=payload,
    )
    checkpoint = checkpoint_from_event(event)

    assert payload == {
        "session_id": "session-a",
        "checkpoint_id": "checkpoint-refs",
        "reason": "before publish",
        "phase_id": "publish",
        "source_event_sequence": 42,
        "refs": [
            {"type": "phase", "phase_id": "publish"},
            {"type": "run", "run_id": "run-7"},
            {"type": "code_snapshot", "snapshot_id": "code-3"},
            {"type": "dataset_snapshot", "snapshot_id": "data-2"},
            {"type": "model_checkpoint", "checkpoint_id": "model-5"},
            {"type": "event_sequence", "sequence": 42},
        ],
    }
    assert checkpoint.source_event_sequence == 42


def test_fork_point_created_payload_builder_preserves_refs_and_source_sequence():
    payload = fork_point_created_payload(
        session_id="session-a",
        fork_point_id="fork-refs",
        reason="try alternate model",
        source_event_sequence=51,
        refs=[
            {"type": "phase", "phase_id": "train"},
            {"type": "run", "run_id": "run-9"},
            {"type": "code_snapshot", "snapshot_id": "code-4"},
            {"type": "dataset_snapshot", "snapshot_id": "data-5"},
            {"type": "model_checkpoint", "checkpoint_id": "model-6"},
            {"type": "event_sequence", "sequence": 51},
        ],
    )

    event = make_event(
        sequence=52,
        event_type="fork_point.created",
        data=payload,
    )
    fork_point = fork_point_from_event(event)

    assert payload["source_event_sequence"] == 51
    assert payload["refs"] == [
        {"type": "phase", "phase_id": "train"},
        {"type": "run", "run_id": "run-9"},
        {"type": "code_snapshot", "snapshot_id": "code-4"},
        {"type": "dataset_snapshot", "snapshot_id": "data-5"},
        {"type": "model_checkpoint", "checkpoint_id": "model-6"},
        {"type": "event_sequence", "sequence": 51},
    ]
    assert [ref.type for ref in fork_point.refs] == [
        "phase",
        "run",
        "code_snapshot",
        "dataset_snapshot",
        "model_checkpoint",
        "event_sequence",
    ]


def test_continuity_payload_builders_do_not_infer_refs_or_include_none():
    checkpoint_payload = checkpoint_created_payload(
        session_id="session-a",
        checkpoint_id="checkpoint-minimal",
        reason="manual checkpoint",
    )
    fork_payload = fork_point_created_payload(
        session_id="session-a",
        fork_point_id="fork-minimal",
    )

    assert checkpoint_payload == {
        "session_id": "session-a",
        "checkpoint_id": "checkpoint-minimal",
        "reason": "manual checkpoint",
    }
    assert fork_payload == {
        "session_id": "session-a",
        "fork_point_id": "fork-minimal",
        "refs": [],
    }


@pytest.mark.parametrize(
    ("builder", "kwargs"),
    [
        (
            checkpoint_created_payload,
            {
                "session_id": "session-a",
                "checkpoint_id": "checkpoint-bad",
                "reason": "bad ref",
                "refs": [{"type": "dataset", "id": "implicit-create"}],
            },
        ),
        (
            fork_point_created_payload,
            {
                "session_id": "session-a",
                "fork_point_id": "fork-bad",
                "refs": [{"type": "event_sequence", "sequence": 0}],
            },
        ),
        (
            checkpoint_created_payload,
            {
                "session_id": "session-a",
                "checkpoint_id": "checkpoint-bad-sequence",
                "reason": "bad source sequence",
                "source_event_sequence": 0,
            },
        ),
    ],
)
def test_continuity_payload_builders_fail_invalid_refs_through_models(
    builder,
    kwargs,
):
    with pytest.raises(ValidationError):
        builder(**kwargs)


def test_handoff_summary_unknown_sections_stay_empty_or_not_recorded():
    summary = generate_handoff_summary(
        workflow_state=make_workflow_state(),
        events=[],
    )

    assert summary.model_dump() == {
        "session_id": "session-a",
        "source_event_sequence": 0,
        "goal": None,
        "completed_phases": [],
        "current_phase": None,
        "decisions": [],
        "evidence": [],
        "artifacts": [],
        "jobs": [],
        "failures": [],
        "risks": [],
        "next_action": "not_recorded",
    }


def test_handoff_summary_is_derived_from_supplied_state_and_events_only():
    state = make_workflow_state(
        objective=WorkflowObjective(
            text="Train a small classifier",
            source="event",
            updated_at="2026-01-02T03:04:01+00:00",
        ),
        phase=PhaseState(
            id="eval",
            label="Evaluate",
            status="active",
            started_at="2026-01-02T03:04:04+00:00",
            updated_at="2026-01-02T03:04:05+00:00",
        ),
        blockers=[
            {
                "source": "event",
                "type": "phase_gate",
                "phase_id": "eval",
                "missing_outputs": ["metrics-json"],
            }
        ],
        active_jobs=[
            {
                "source": "event",
                "tool_call_id": "tc-1",
                "job_id": "job-1",
                "status": "running",
            }
        ],
        evidence_summary={
            "source": "durable",
            "items": [{"claim_id": "claim-1", "artifact_id": "artifact-1"}],
        },
        last_event_sequence=8,
    )
    events = [
        make_event(
            sequence=2,
            event_type="phase.completed",
            data={"session_id": "session-a", "phase_id": "prep", "phase_name": "Prep"},
        ),
        make_event(
            sequence=3,
            event_type="decision.recorded",
            data={"session_id": "session-a", "decision_id": "d1", "text": "Use CPU"},
        ),
        make_event(
            sequence=4,
            event_type="artifact.recorded",
            data={"session_id": "session-a", "artifact_id": "artifact-1"},
        ),
        make_event(
            sequence=5,
            event_type="failure.recorded",
            data={"session_id": "session-a", "failure_id": "f1", "status": "open"},
        ),
        make_event(
            sequence=6,
            event_type="risk.recorded",
            data={"session_id": "session-a", "risk_id": "r1", "status": "open"},
        ),
        make_event(
            sequence=7,
            event_type="next_action.recorded",
            data={"session_id": "session-a", "next_action": "collect metrics"},
        ),
    ]

    summary = generate_handoff_summary(workflow_state=state, events=events)

    assert summary.goal == "Train a small classifier"
    assert summary.completed_phases == [
        {
            "phase_id": "prep",
            "phase_name": "Prep",
            "source_event_sequence": 2,
            "updated_at": "2026-01-02T03:04:02+00:00",
        }
    ]
    assert summary.current_phase == {
        "phase_id": "eval",
        "phase_name": "Evaluate",
        "status": "active",
        "started_at": "2026-01-02T03:04:04+00:00",
        "updated_at": "2026-01-02T03:04:05+00:00",
    }
    assert summary.decisions[0]["decision_id"] == "d1"
    assert summary.evidence == [{"claim_id": "claim-1", "artifact_id": "artifact-1"}]
    assert summary.artifacts[0]["artifact_id"] == "artifact-1"
    assert summary.jobs == [
        {
            "source": "event",
            "tool_call_id": "tc-1",
            "job_id": "job-1",
            "status": "running",
        }
    ]
    assert summary.failures[0]["failure_id"] == "f1"
    assert summary.risks[0]["type"] == "phase_gate"
    assert summary.risks[1]["risk_id"] == "r1"
    assert summary.next_action == "collect metrics"


def test_handoff_summary_created_payload_validates_as_agent_event():
    summary = generate_handoff_summary(
        workflow_state=make_workflow_state(last_event_sequence=1),
        events=[],
    )
    payload = handoff_summary_created_payload(
        handoff_id="handoff-1",
        summary=summary,
    )

    event = make_event(
        sequence=2,
        event_type="handoff.summary_created",
        data=payload,
    )

    assert event.data["session_id"] == "session-a"
    assert event.data["summary"]["next_action"] == "not_recorded"

    with pytest.raises(ValidationError):
        make_event(
            sequence=3,
            event_type="handoff.summary_created",
            data={
                **payload,
                "summary": {**payload["summary"], "session_id": "other-session"},
            },
        )


def test_continuity_events_persist_in_generic_agent_event_store(tmp_path):
    database_path = tmp_path / "events.sqlite"
    store = SQLiteEventStore(database_path)
    store.append(
        make_event(
            sequence=1,
            event_type="checkpoint.created",
            data={
                "session_id": "session-a",
                "checkpoint_id": "checkpoint-1",
                "reason": "before fork",
            },
        )
    )

    replayed = store.replay("session-a")
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()

    assert [event.event_type for event in replayed] == ["checkpoint.created"]
    assert tables == {"agent_events"}
