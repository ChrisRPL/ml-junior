from __future__ import annotations

from pathlib import Path

import pytest

from backend.event_store import SQLiteEventStore
from backend.flow_templates import load_flow_template
from backend.models import (
    PhaseState,
    WorkflowCompatibility,
    WorkflowObjective,
    WorkflowResumeState,
    WorkflowState,
)
from backend.phase_events import (
    PhaseEventPersistenceError,
    persist_phase_transition_events,
    phase_transition_agent_events,
)
from backend.phase_gates import plan_phase_transition


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "flow_templates"
)


def make_workflow_state() -> WorkflowState:
    return WorkflowState(
        snapshot_version=1,
        session_id="session-a",
        project_id="session:session-a",
        status="processing",
        objective=WorkflowObjective(),
        phase=PhaseState(id="train", label="Train", status="active"),
        plan=[],
        blockers=[],
        pending_approvals=[],
        active_jobs=[],
        operation_refs=[],
        human_requests=[],
        budget={},
        evidence_summary={},
        live_tracking_refs=[],
        resume=WorkflowResumeState(event_sequence=7),
        compatibility=WorkflowCompatibility(stale=False, missing_producers=[]),
        last_event_sequence=7,
    )


def test_persist_phase_transition_events_stores_verified_and_completed(tmp_path):
    template = load_flow_template(FIXTURE_DIR / "valid_v1.json")
    result = plan_phase_transition(
        template,
        make_workflow_state(),
        "train",
        "complete",
        available_outputs=["metrics-json"],
        verifier_results={"accuracy-threshold": "passed"},
    )
    store = SQLiteEventStore(tmp_path / "events.sqlite")

    stored = persist_phase_transition_events(store, result, start_sequence=8)
    replayed = store.replay("session-a")

    assert [event.sequence for event in stored] == [8, 9]
    assert [event.event_type for event in replayed] == [
        "phase.verified",
        "phase.completed",
    ]
    assert replayed[-1].data["phase_id"] == "train"
    assert replayed[-1].data["available_outputs"] == ["metrics-json"]


def test_persist_phase_transition_events_stores_blocked_verifier_pending(tmp_path):
    template = load_flow_template(FIXTURE_DIR / "valid_v1.json")
    result = plan_phase_transition(
        template,
        make_workflow_state(),
        "train",
        "complete",
        available_outputs=["metrics-json"],
    )
    store = SQLiteEventStore(tmp_path / "events.sqlite")

    stored = persist_phase_transition_events(store, result, start_sequence=8)

    assert [event.event_type for event in stored] == ["phase.blocked"]
    assert stored[0].data["gate_status"] == "verifier_pending"
    assert stored[0].data["pending_verifiers"] == ["accuracy-threshold"]


def test_persist_phase_transition_events_stores_waiver_payload(tmp_path):
    template = load_flow_template(FIXTURE_DIR / "valid_v1.json")
    result = plan_phase_transition(
        template,
        make_workflow_state(),
        "train",
        "complete",
        output_waivers=[
            {
                "required_output_id": "metrics-json",
                "reason": "manual evidence accepted",
                "approved_by": "alice",
            }
        ],
        verifier_results={"accuracy-threshold": "passed"},
    )
    store = SQLiteEventStore(tmp_path / "events.sqlite")

    stored = persist_phase_transition_events(store, result, start_sequence=8)

    assert stored[-1].event_type == "phase.completed"
    assert stored[-1].data["waiver_records"] == [
        {
            "required_output_id": "metrics-json",
            "reason": "manual evidence accepted",
            "approved_by": "alice",
            "output_id": "metrics-json",
        }
    ]


def test_phase_transition_agent_events_reject_invalid_sequence() -> None:
    template = load_flow_template(FIXTURE_DIR / "valid_v1.json")
    result = plan_phase_transition(
        template,
        make_workflow_state(),
        "train",
        "active",
        current_status="pending",
    )

    with pytest.raises(PhaseEventPersistenceError, match="start_sequence"):
        phase_transition_agent_events(result, start_sequence=0)
