from __future__ import annotations

from pathlib import Path

import pytest

from backend.flow_templates import load_flow_template
from backend.models import (
    PhaseState,
    WorkflowCompatibility,
    WorkflowObjective,
    WorkflowResumeState,
    WorkflowState,
)
from backend.phase_gates import (
    PhaseTransitionError,
    evaluate_phase_gate,
    plan_phase_transition,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "flow_templates"
)


def make_workflow_state(
    *,
    phase_id: str = "train",
    phase_status: str = "active",
) -> WorkflowState:
    return WorkflowState(
        snapshot_version=1,
        session_id="session-a",
        project_id="session:session-a",
        status="processing",
        objective=WorkflowObjective(),
        phase=PhaseState(
            id=phase_id,
            label="Train",
            status=phase_status,
        ),
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
        compatibility=WorkflowCompatibility(
            stale=False,
            missing_producers=[],
        ),
        last_event_sequence=7,
        updated_at="2026-01-02T03:04:05+00:00",
    )


def test_valid_completion_transition_returns_phase_events() -> None:
    template = load_flow_template(FIXTURE_DIR / "valid_v1.json")

    result = plan_phase_transition(
        template,
        make_workflow_state(),
        "train",
        "complete",
        available_outputs=["metrics-json"],
        verifier_results={"accuracy-threshold": "passed"},
    )

    assert result.allowed is True
    assert result.from_status == "active"
    assert result.to_status == "complete"
    assert result.gate.can_complete is True
    assert [event["event_type"] for event in result.events] == [
        "phase.verified",
        "phase.completed",
    ]
    assert result.events[-1]["data"] == {
        "session_id": "session-a",
        "project_id": "session:session-a",
        "template_id": "mnist-baseline",
        "template_version": "v1",
        "phase_id": "train",
        "phase_name": "Train",
        "phase_order": 1,
        "from_status": "active",
        "requested_status": "complete",
        "to_status": "complete",
        "allowed": True,
        "gate_status": "satisfied",
        "can_complete": True,
        "required_outputs": ["metrics-json"],
        "available_outputs": ["metrics-json"],
        "waived_outputs": [],
        "missing_outputs": [],
        "required_verifiers": ["accuracy-threshold"],
        "passed_verifiers": ["accuracy-threshold"],
        "pending_verifiers": [],
        "failed_verifiers": [],
        "waiver_records": [],
    }


def test_invalid_transition_raises_without_events() -> None:
    template = load_flow_template(FIXTURE_DIR / "valid_v1.json")

    with pytest.raises(
        PhaseTransitionError,
        match="Invalid phase transition: complete -> active",
    ):
        plan_phase_transition(
            template,
            make_workflow_state(phase_status="complete"),
            "train",
            "active",
        )


def test_missing_required_output_blocks_completion() -> None:
    template = load_flow_template(FIXTURE_DIR / "valid_v1.json")

    result = plan_phase_transition(
        template,
        make_workflow_state(),
        "train",
        "complete",
        verifier_results={"accuracy-threshold": "passed"},
    )

    assert result.allowed is False
    assert result.to_status == "blocked"
    assert result.gate.status == "blocked"
    assert result.gate.missing_outputs == ("metrics-json",)
    assert [event["event_type"] for event in result.events] == ["phase.blocked"]
    assert result.events[0]["data"]["requested_status"] == "complete"
    assert result.events[0]["data"]["to_status"] == "blocked"


def test_output_waiver_allows_completion_without_output() -> None:
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

    assert result.allowed is True
    assert result.gate.missing_outputs == ()
    assert result.gate.waived_outputs == ("metrics-json",)
    assert result.events[-1]["event_type"] == "phase.completed"
    assert result.events[-1]["data"]["waiver_records"] == [
        {
            "required_output_id": "metrics-json",
            "reason": "manual evidence accepted",
            "approved_by": "alice",
            "output_id": "metrics-json",
        }
    ]


def test_verifier_pending_status_blocks_completion_until_result_exists() -> None:
    template = load_flow_template(FIXTURE_DIR / "valid_v1.json")

    gate = evaluate_phase_gate(
        template,
        "train",
        available_outputs=["metrics-json"],
    )
    result = plan_phase_transition(
        template,
        make_workflow_state(),
        "train",
        "complete",
        available_outputs=["metrics-json"],
    )

    assert gate.status == "verifier_pending"
    assert gate.pending_verifiers == ("accuracy-threshold",)
    assert gate.can_complete is False
    assert result.allowed is False
    assert result.to_status == "blocked"
    assert result.events[0]["event_type"] == "phase.blocked"
    assert result.events[0]["data"]["gate_status"] == "verifier_pending"
