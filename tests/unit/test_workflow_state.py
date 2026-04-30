from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.core.events import AgentEvent
from backend.evidence_ledger import (
    EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
    EVIDENCE_ITEM_RECORDED_EVENT,
)
from backend.event_store import SQLiteEventStore
from backend.experiment_ledger import LOG_REF_RECORDED_EVENT, METRIC_RECORDED_EVENT
from backend.human_requests import (
    HUMAN_REQUEST_REQUESTED_EVENT,
    HUMAN_REQUEST_RESOLVED_EVENT,
    human_request_requested_payload,
    human_request_resolved_payload,
)
from backend.job_artifact_refs import (
    ACTIVE_JOB_RECORDED_EVENT,
    ARTIFACT_REF_RECORDED_EVENT,
)
from backend.models import HumanRequestRecord, VerifierVerdictRecord
from backend.operation_store import OPERATION_RUNNING, SQLiteOperationStore
from backend.session_store import SQLiteSessionStore
from backend.verifier_ledger import (
    VERIFIER_COMPLETED_EVENT,
    verifier_completed_payload,
)
from backend.verifier_check_catalog import (
    CHECK_CODE_EXECUTION_OBSERVED,
    CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE,
    CHECK_METRIC_PARSED_FROM_OUTPUT,
)
from backend.workflow_state import build_workflow_state
import routes.agent as agent_routes
import session_manager as session_module


class DeterministicClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self._current
        self._current += timedelta(seconds=1)
        return value


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


def make_active_job_recorded_event(
    *,
    sequence: int,
    job_id: str = "active-job-1",
    status: str = "running",
    session_id: str = "session-a",
    event_id: str | None = None,
    source_event_sequence: int | None = None,
) -> AgentEvent:
    return make_event(
        sequence=sequence,
        event_type=ACTIVE_JOB_RECORDED_EVENT,
        session_id=session_id,
        data={
            "session_id": session_id,
            "job_id": job_id,
            "source_event_sequence": source_event_sequence or sequence,
            "tool_call_id": "tc-1",
            "tool": "hf_jobs",
            "provider": "huggingface_jobs",
            "status": status,
            "url": f"https://jobs.example/{job_id}",
            "label": "Training job",
            "metadata": {"queue": "cpu"},
            "redaction_status": "partial",
            "started_at": "2026-01-02T03:04:00+00:00",
            "updated_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
            "completed_at": (
                f"2026-01-02T03:04:{sequence:02d}+00:00"
                if status in {"completed", "failed", "cancelled"}
                else None
            ),
        },
    ).model_copy(update={"id": event_id or f"event-{sequence}"})


def make_artifact_ref_recorded_event(
    *,
    sequence: int,
    artifact_id: str = "artifact-1",
    label: str = "Best checkpoint",
    session_id: str = "session-a",
    event_id: str | None = None,
    source_event_sequence: int | None = None,
) -> AgentEvent:
    return make_event(
        sequence=sequence,
        event_type=ARTIFACT_REF_RECORDED_EVENT,
        session_id=session_id,
        data={
            "session_id": session_id,
            "artifact_id": artifact_id,
            "source_event_sequence": source_event_sequence or sequence,
            "type": "model_checkpoint",
            "source": "job",
            "source_tool_call_id": "tc-1",
            "source_job_id": "active-job-1",
            "path": f"/tmp/{artifact_id}.pt",
            "uri": f"file:///tmp/{artifact_id}.pt",
            "digest": f"sha256:{artifact_id}",
            "label": label,
            "metadata": {"epoch": sequence},
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    ).model_copy(update={"id": event_id or f"event-{sequence}"})


def make_human_request_event(
    *,
    sequence: int,
    request_id: str = "hr-1",
    status: str = "requested",
    summary: str | None = "Need dataset choice",
    session_id: str = "session-a",
) -> AgentEvent:
    record = HumanRequestRecord(
        session_id=session_id,
        request_id=request_id,
        source_event_sequence=sequence,
        status=status,
        channel="in_app",
        summary=summary,
        metadata={},
        privacy_class="unknown",
        redaction_status="none",
        created_at="2026-01-02T03:04:01+00:00",
        updated_at=f"2026-01-02T03:04:{sequence:02d}+00:00",
        resolved_at=(
            f"2026-01-02T03:04:{sequence:02d}+00:00"
            if status != "requested"
            else None
        ),
        resolution_summary="Answered in chat" if status == "answered" else None,
    )
    event_type = (
        HUMAN_REQUEST_REQUESTED_EVENT
        if status == "requested"
        else HUMAN_REQUEST_RESOLVED_EVENT
    )
    payload = (
        human_request_requested_payload(record)
        if status == "requested"
        else human_request_resolved_payload(record)
    )
    return make_event(
        sequence=sequence,
        event_type=event_type,
        session_id=session_id,
        data=payload,
    )


def make_metric_recorded_event(
    *,
    sequence: int,
    metric_id: str = "metric-1",
    name: str = "accuracy",
    value: float = 0.91,
    session_id: str = "session-a",
    event_id: str | None = None,
    source_event_sequence: int | None = None,
) -> AgentEvent:
    return make_event(
        sequence=sequence,
        event_type=METRIC_RECORDED_EVENT,
        session_id=session_id,
        data={
            "session_id": session_id,
            "metric_id": metric_id,
            "source_event_sequence": source_event_sequence or sequence,
            "name": name,
            "value": value,
            "source": "tool",
            "step": 3,
            "unit": "ratio",
            "recorded_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    ).model_copy(update={"id": event_id or f"event-{sequence}"})


def make_log_ref_recorded_event(
    *,
    sequence: int,
    log_id: str = "log-1",
    label: str = "training log",
    session_id: str = "session-a",
    event_id: str | None = None,
    source_event_sequence: int | None = None,
) -> AgentEvent:
    return make_event(
        sequence=sequence,
        event_type=LOG_REF_RECORDED_EVENT,
        session_id=session_id,
        data={
            "session_id": session_id,
            "log_id": log_id,
            "source_event_sequence": source_event_sequence or sequence,
            "source": "stdout",
            "uri": f"file:///tmp/{log_id}.log",
            "label": label,
        },
    ).model_copy(update={"id": event_id or f"event-{sequence}"})


def make_evidence_item_recorded_event(
    *,
    sequence: int,
    evidence_id: str = "evidence-1",
    title: str = "Validation accuracy evidence",
    session_id: str = "session-a",
    event_id: str | None = None,
    source_event_sequence: int | None = None,
) -> AgentEvent:
    return make_event(
        sequence=sequence,
        event_type=EVIDENCE_ITEM_RECORDED_EVENT,
        session_id=session_id,
        data={
            "session_id": session_id,
            "evidence_id": evidence_id,
            "source_event_sequence": source_event_sequence or sequence,
            "kind": "metric",
            "source": "metric",
            "title": title,
            "summary": "Accuracy improved over baseline",
            "metric_id": "metric-1",
            "metadata": {"split": "validation"},
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    ).model_copy(update={"id": event_id or f"event-{sequence}"})


def make_evidence_claim_link_recorded_event(
    *,
    sequence: int,
    link_id: str = "evidence-link-1",
    evidence_id: str = "evidence-1",
    claim_id: str = "claim-1",
    session_id: str = "session-a",
    event_id: str | None = None,
    source_event_sequence: int | None = None,
) -> AgentEvent:
    return make_event(
        sequence=sequence,
        event_type=EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
        session_id=session_id,
        data={
            "session_id": session_id,
            "link_id": link_id,
            "claim_id": claim_id,
            "evidence_id": evidence_id,
            "source_event_sequence": source_event_sequence or sequence,
            "relation": "supports",
            "strength": "strong",
            "rationale": "Metric exceeds baseline.",
            "metadata": {"reviewed_by": "synthetic-fixture"},
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    ).model_copy(update={"id": event_id or f"event-{sequence}"})


def make_verifier_completed_event(
    *,
    sequence: int,
    verdict_id: str = "verdict-1",
    verifier_id: str = "final-claims-have-evidence",
    verdict: str = "passed",
    summary: str = "Claims have support.",
    check_ids: list[str | None] | None = None,
    session_id: str = "session-a",
    event_id: str | None = None,
    source_event_sequence: int | None = None,
) -> AgentEvent:
    checks = [
        {
            **({} if check_id is None else {"check_id": check_id}),
            "name": f"Verifier check {index + 1}",
            "status": (
                verdict
                if verdict in {"passed", "failed"}
                else "inconclusive"
            ),
            "summary": summary,
            "evidence_ids": ["evidence-1"],
            "metadata": {"claim_id": "claim-1"},
        }
        for index, check_id in enumerate(
            ["check-1"] if check_ids is None else check_ids
        )
    ]
    record = VerifierVerdictRecord.model_validate(
        {
            "session_id": session_id,
            "verdict_id": verdict_id,
            "verifier_id": verifier_id,
            "source_event_sequence": source_event_sequence or sequence,
            "verdict": verdict,
            "scope": "final_answer",
            "final_answer_ref": "final-answer-1",
            "phase_id": "phase-report",
            "run_id": "run-1",
            "evidence_ids": ["evidence-1"],
            "claim_ids": ["claim-1"],
            "summary": summary,
            "rationale": "Evidence supports the final claim.",
            "checks": checks,
            "metadata": {"source": "synthetic-fixture"},
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        }
    )
    return make_event(
        sequence=sequence,
        event_type=VERIFIER_COMPLETED_EVENT,
        session_id=session_id,
        data=verifier_completed_payload(record),
    ).model_copy(update={"id": event_id or f"event-{sequence}"})


def _summary_item_id(item: dict) -> str | None:
    if "verdict_id" in item:
        return item.get("verdict_id")
    if "link_id" in item:
        return item.get("link_id")
    if "evidence_id" in item and "kind" in item:
        return item.get("evidence_id")
    return item.get("artifact_id") or item.get("metric_id") or item.get("log_id")


def test_plan_update_projects_latest_plan_items():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_event(
                sequence=1,
                event_type="plan_update",
                data={
                    "plan": [
                        {"id": "p1", "content": "Collect data", "status": "done"},
                        {"id": "p2", "content": "Train model", "status": "pending"},
                    ]
                },
            )
        ],
    )

    assert state.plan[0].model_dump() == {
        "id": "p1",
        "content": "Collect data",
        "status": "done",
        "source_event_sequence": 1,
        "updated_at": "2026-01-02T03:04:01+00:00",
    }
    assert state.plan[1].source_event_sequence == 1
    assert state.last_event_sequence == 1


def test_approval_required_projects_pending_approval_refs():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_event(
                sequence=1,
                event_type="approval_required",
                data={
                    "tools": [
                        {
                            "tool": "hf_jobs",
                            "tool_call_id": "tc-1",
                            "arguments": {"hardware": "cpu-basic"},
                        }
                    ],
                    "count": 1,
                },
            )
        ],
    )

    assert state.status == "waiting_approval"
    assert state.pending_approvals == [
        {
            "source": "event",
            "source_event_sequence": 1,
            "updated_at": "2026-01-02T03:04:01+00:00",
            "tool": "hf_jobs",
            "tool_call_id": "tc-1",
            "arguments": {"hardware": "cpu-basic"},
        }
    ]


def test_human_request_events_project_into_workflow_state():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_human_request_event(sequence=1),
            make_human_request_event(
                sequence=2,
                status="answered",
                summary=None,
            ),
        ],
    )

    assert state.human_requests == [
        {
            "source": "event",
            "session_id": "session-a",
            "request_id": "hr-1",
            "source_event_sequence": 2,
            "channel": "in_app",
            "summary": "Need dataset choice",
            "metadata": {},
            "privacy_class": "unknown",
            "redaction_status": "none",
            "created_at": "2026-01-02T03:04:01+00:00",
            "updated_at": "2026-01-02T03:04:02+00:00",
            "status": "answered",
            "resolved_at": "2026-01-02T03:04:02+00:00",
            "resolution_summary": "Answered in chat",
        }
    ]


def test_human_request_projection_uses_latest_event_per_request():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_human_request_event(sequence=1, request_id="hr-1"),
            make_human_request_event(
                sequence=2,
                request_id="hr-2",
                summary="Need metric choice",
            ),
            make_human_request_event(
                sequence=3,
                request_id="hr-1",
                status="answered",
            ),
            make_human_request_event(
                sequence=4,
                request_id="hr-1",
                summary="Need follow-up",
            ),
            make_human_request_event(
                sequence=5,
                request_id="hr-other",
                session_id="session-b",
            ),
        ],
    )

    assert [
        (request["request_id"], request["status"], request["summary"])
        for request in state.human_requests
    ] == [
        ("hr-2", "requested", "Need metric choice"),
        ("hr-1", "requested", "Need follow-up"),
    ]


def test_tool_events_project_active_job_lifecycle():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_event(
                sequence=1,
                event_type="tool_call",
                data={
                    "tool": "hf_jobs",
                    "tool_call_id": "tc-1",
                    "arguments": {"operation": "run"},
                },
            ),
            make_event(
                sequence=2,
                event_type="tool_state_change",
                data={
                    "tool": "hf_jobs",
                    "tool_call_id": "tc-1",
                    "state": "running",
                    "jobUrl": "https://jobs.example/job-1",
                },
            ),
        ],
    )

    assert state.status == "processing"
    assert state.active_jobs == [
        {
            "source": "event",
            "source_event_sequence": 2,
            "updated_at": "2026-01-02T03:04:02+00:00",
            "tool_call_id": "tc-1",
            "tool": "hf_jobs",
            "job_id": None,
            "status": "running",
            "url": "https://jobs.example/job-1",
        }
    ]

    completed = build_workflow_state(
        session_id="session-a",
        events=[
            make_event(
                sequence=1,
                event_type="tool_state_change",
                data={
                    "tool": "hf_jobs",
                    "tool_call_id": "tc-1",
                    "state": "running",
                },
            ),
            make_event(
                sequence=2,
                event_type="tool_output",
                data={
                    "tool": "hf_jobs",
                    "tool_call_id": "tc-1",
                    "output": "done",
                    "success": True,
                },
            ),
        ],
    )

    assert completed.active_jobs == []
    assert completed.status == "completed"


def test_active_job_recorded_projects_active_job_refs_in_workflow_state():
    state = build_workflow_state(
        session_id="session-a",
        events=[make_active_job_recorded_event(sequence=1)],
    )

    assert state.status == "processing"
    assert state.active_jobs == [
        {
            "source": "event",
            "session_id": "session-a",
            "job_id": "active-job-1",
            "source_event_sequence": 1,
            "tool_call_id": "tc-1",
            "tool": "hf_jobs",
            "provider": "huggingface_jobs",
            "status": "running",
            "url": "https://jobs.example/active-job-1",
            "label": "Training job",
            "metadata": {"queue": "cpu"},
            "redaction_status": "partial",
            "started_at": "2026-01-02T03:04:00+00:00",
            "updated_at": "2026-01-02T03:04:01+00:00",
        }
    ]


def test_terminal_active_job_recorded_does_not_show_in_active_jobs():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_active_job_recorded_event(sequence=1, status="running"),
            make_active_job_recorded_event(sequence=2, status="completed"),
        ],
    )

    assert state.active_jobs == []
    assert state.status == "idle"


def test_artifact_ref_recorded_projects_explicit_refs_into_evidence_summary():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_artifact_ref_recorded_event(
                sequence=1,
                artifact_id="artifact-1",
                label="Initial checkpoint",
            ),
            make_artifact_ref_recorded_event(
                sequence=2,
                artifact_id="artifact-2",
                label="Metrics",
            ),
        ],
    )

    assert state.evidence_summary["source"] == "event"
    assert state.evidence_summary["status"] == "available"
    assert state.evidence_summary["artifact_count"] == 2
    assert state.evidence_summary["claim_count"] == 0
    assert state.evidence_summary["claim_link_count"] == 0
    assert state.evidence_summary["evidence_count"] == 0
    assert state.evidence_summary["metric_count"] == 0
    assert state.evidence_summary["log_count"] == 0
    assert [
        (item["artifact_id"], item["label"], item["source"])
        for item in state.evidence_summary["items"]
    ] == [
        ("artifact-1", "Initial checkpoint", "job"),
        ("artifact-2", "Metrics", "job"),
    ]


def test_metric_and_log_ref_recorded_project_into_evidence_summary():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_metric_recorded_event(
                sequence=1,
                metric_id="metric-accuracy",
                name="accuracy",
                value=0.93,
            ),
            make_log_ref_recorded_event(
                sequence=2,
                log_id="log-train",
                label="train stdout",
            ),
            make_artifact_ref_recorded_event(
                sequence=3,
                artifact_id="artifact-model",
                label="Model checkpoint",
            ),
        ],
    )

    assert state.evidence_summary["source"] == "event"
    assert state.evidence_summary["status"] == "available"
    assert state.evidence_summary["artifact_count"] == 1
    assert state.evidence_summary["metric_count"] == 1
    assert state.evidence_summary["log_count"] == 1
    assert [
        item.get("metric_id") or item.get("log_id") or item.get("artifact_id")
        for item in state.evidence_summary["items"]
    ] == ["metric-accuracy", "log-train", "artifact-model"]
    assert state.evidence_summary["items"][0]["name"] == "accuracy"
    assert state.evidence_summary["items"][1]["label"] == "train stdout"


def test_evidence_item_and_claim_link_recorded_project_into_evidence_summary():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_evidence_item_recorded_event(
                sequence=1,
                evidence_id="evidence-accuracy",
                title="Accuracy threshold evidence",
            ),
            make_evidence_claim_link_recorded_event(
                sequence=2,
                link_id="evidence-link-accuracy",
                evidence_id="evidence-accuracy",
                claim_id="claim-accuracy",
            ),
        ],
    )

    assert state.evidence_summary["source"] == "event"
    assert state.evidence_summary["status"] == "available"
    assert state.evidence_summary["evidence_count"] == 1
    assert state.evidence_summary["claim_count"] == 1
    assert state.evidence_summary["claim_link_count"] == 1
    assert state.evidence_summary["artifact_count"] == 0
    assert state.evidence_summary["metric_count"] == 0
    assert state.evidence_summary["log_count"] == 0
    assert [
        _summary_item_id(item)
        for item in state.evidence_summary["items"]
    ] == ["evidence-accuracy", "evidence-link-accuracy"]
    assert state.evidence_summary["items"][0]["title"] == "Accuracy threshold evidence"
    assert state.evidence_summary["items"][1]["link_id"] == "evidence-link-accuracy"


def test_verifier_completed_projects_into_evidence_summary():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_evidence_item_recorded_event(sequence=1, evidence_id="evidence-1"),
            make_verifier_completed_event(
                sequence=2,
                verdict_id="verdict-coverage",
                verdict="passed",
                summary="Coverage verified.",
            ),
            make_verifier_completed_event(
                sequence=3,
                verdict_id="verdict-risk",
                verdict="inconclusive",
                summary="Risk review needs more evidence.",
            ),
        ],
    )

    assert state.evidence_summary["source"] == "event"
    assert state.evidence_summary["status"] == "available"
    assert state.evidence_summary["verifier_count"] == 2
    assert state.evidence_summary["verifier_counts"] == {
        "passed": 1,
        "failed": 0,
        "inconclusive": 1,
    }
    assert state.evidence_summary["verifier_status"] == "inconclusive"
    assert state.evidence_summary["evidence_count"] == 1
    assert state.evidence_summary["claim_count"] == 0
    assert state.evidence_summary["claim_link_count"] == 0
    assert state.evidence_summary["artifact_count"] == 0
    assert state.evidence_summary["metric_count"] == 0
    assert state.evidence_summary["log_count"] == 0
    assert [
        _summary_item_id(item)
        for item in state.evidence_summary["items"]
    ] == ["evidence-1", "verdict-coverage", "verdict-risk"]
    assert state.evidence_summary["items"][1]["summary"] == "Coverage verified."
    assert state.evidence_summary["items"][2]["verdict"] == "inconclusive"


def test_verifier_completed_reconciles_mapped_and_catalog_ids():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_verifier_completed_event(
                sequence=1,
                verdict_id="verdict-metric",
                verifier_id="metric-recorded",
                check_ids=[CHECK_CODE_EXECUTION_OBSERVED],
            ),
        ],
    )

    assert state.evidence_summary["verifier_catalog"] == {
        "source": "flow_verifier_mapping",
        "catalog_check_ids": [
            CHECK_CODE_EXECUTION_OBSERVED,
            CHECK_METRIC_PARSED_FROM_OUTPUT,
        ],
        "direct_catalog_check_ids": [CHECK_CODE_EXECUTION_OBSERVED],
        "mapped_catalog_check_ids": [CHECK_METRIC_PARSED_FROM_OUTPUT],
        "flow_local_verifier_ids": ["metric-recorded"],
        "intentional_unmapped_ids": [],
        "unknown_ids": [],
        "mapping_rows": [
            {
                "flow_verifier_id": "metric-recorded",
                "catalog_check_id": CHECK_METRIC_PARSED_FROM_OUTPUT,
            }
        ],
        "counts": {
            "verdict_count": 1,
            "observed_id_count": 2,
            "catalog_check_id_count": 2,
            "direct_catalog_check_id_count": 1,
            "mapped_catalog_check_id_count": 1,
            "flow_local_verifier_id_count": 1,
            "intentional_unmapped_id_count": 0,
            "unknown_id_count": 0,
        },
    }


def test_verifier_completed_reconciles_intentional_unmapped_ids():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_verifier_completed_event(
                sequence=1,
                verdict_id="verdict-goal",
                verifier_id="goal-is-testable",
                check_ids=[],
            ),
        ],
    )

    assert state.evidence_summary["verifier_catalog"]["catalog_check_ids"] == []
    assert state.evidence_summary["verifier_catalog"]["flow_local_verifier_ids"] == [
        "goal-is-testable"
    ]
    assert state.evidence_summary["verifier_catalog"]["intentional_unmapped_ids"] == [
        "goal-is-testable"
    ]
    assert state.evidence_summary["verifier_catalog"]["unknown_ids"] == []
    assert state.evidence_summary["verifier_catalog"]["counts"][
        "intentional_unmapped_id_count"
    ] == 1


def test_verifier_completed_reconciles_unknown_unmapped_ids():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_verifier_completed_event(
                sequence=1,
                verdict_id="verdict-custom",
                verifier_id="custom-flow-check",
                check_ids=["custom-inner-check"],
            ),
        ],
    )

    assert state.evidence_summary["verifier_catalog"]["catalog_check_ids"] == []
    assert state.evidence_summary["verifier_catalog"]["flow_local_verifier_ids"] == [
        "custom-flow-check",
        "custom-inner-check",
    ]
    assert state.evidence_summary["verifier_catalog"]["intentional_unmapped_ids"] == []
    assert state.evidence_summary["verifier_catalog"]["unknown_ids"] == [
        "custom-flow-check",
        "custom-inner-check",
    ]
    assert state.evidence_summary["verifier_catalog"]["counts"][
        "unknown_id_count"
    ] == 2


def test_recorded_job_and_artifact_events_from_other_sessions_are_ignored():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_active_job_recorded_event(
                sequence=1,
                job_id="active-job-b",
                session_id="session-b",
            ),
            make_artifact_ref_recorded_event(
                sequence=2,
                artifact_id="artifact-b",
                session_id="session-b",
            ),
            make_metric_recorded_event(
                sequence=3,
                metric_id="metric-b",
                session_id="session-b",
            ),
            make_log_ref_recorded_event(
                sequence=4,
                log_id="log-b",
                session_id="session-b",
            ),
            make_evidence_item_recorded_event(
                sequence=5,
                evidence_id="evidence-b",
                session_id="session-b",
            ),
            make_evidence_claim_link_recorded_event(
                sequence=6,
                link_id="evidence-link-b",
                evidence_id="evidence-b",
                session_id="session-b",
            ),
            make_verifier_completed_event(
                sequence=7,
                verdict_id="verdict-b",
                session_id="session-b",
            ),
        ],
    )

    assert state.active_jobs == []
    assert state.evidence_summary == {
        "source": "placeholder",
        "status": "placeholder",
        "claim_count": 0,
        "claim_link_count": 0,
        "evidence_count": 0,
        "artifact_count": 0,
        "metric_count": 0,
        "log_count": 0,
        "items": [],
    }
    assert state.compatibility.stale is True


def test_verifier_completed_replay_retry_keeps_latest_verdict_in_summary():
    initial_verdict = make_verifier_completed_event(
        sequence=1,
        verdict_id="verdict-1",
        verifier_id="custom-flow-check",
        verdict="inconclusive",
        summary="Initial verifier result.",
        check_ids=["custom-inner-check"],
    )
    latest_verdict = make_verifier_completed_event(
        sequence=2,
        verdict_id="verdict-1",
        verifier_id="metric-recorded",
        verdict="failed",
        summary="Retried verifier result.",
        check_ids=[CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE],
        event_id="event-verdict-latest",
    )

    state = build_workflow_state(
        session_id="session-a",
        events=[
            initial_verdict,
            latest_verdict,
            latest_verdict.model_copy(),
        ],
    )

    assert state.evidence_summary["verifier_count"] == 1
    assert state.evidence_summary["verifier_counts"] == {
        "passed": 0,
        "failed": 1,
        "inconclusive": 0,
    }
    assert state.evidence_summary["verifier_status"] == "failed"
    assert [
        _summary_item_id(item)
        for item in state.evidence_summary["items"]
    ] == ["verdict-1"]
    assert (
        state.evidence_summary["items"][0]["summary"]
        == "Retried verifier result."
    )
    assert state.evidence_summary["verifier_catalog"]["catalog_check_ids"] == [
        CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE,
        CHECK_METRIC_PARSED_FROM_OUTPUT,
    ]
    assert state.evidence_summary["verifier_catalog"]["mapped_catalog_check_ids"] == [
        CHECK_METRIC_PARSED_FROM_OUTPUT
    ]
    assert state.evidence_summary["verifier_catalog"]["unknown_ids"] == []


def test_duplicate_replayed_recorded_job_and_artifact_events_are_deterministic():
    initial_job = make_active_job_recorded_event(
        sequence=1,
        job_id="active-job-1",
        status="queued",
    )
    latest_job = make_active_job_recorded_event(
        sequence=2,
        job_id="active-job-1",
        status="running",
    )
    initial_artifact = make_artifact_ref_recorded_event(
        sequence=3,
        artifact_id="artifact-1",
        label="Initial checkpoint",
    )
    latest_artifact = make_artifact_ref_recorded_event(
        sequence=4,
        artifact_id="artifact-1",
        label="Final checkpoint",
    )
    metric = make_metric_recorded_event(sequence=5, metric_id="metric-1")
    log_ref = make_log_ref_recorded_event(sequence=6, log_id="log-1")
    evidence_item = make_evidence_item_recorded_event(
        sequence=7,
        evidence_id="evidence-1",
    )
    claim_link = make_evidence_claim_link_recorded_event(
        sequence=8,
        link_id="evidence-link-1",
        evidence_id="evidence-1",
    )
    verifier_verdict = make_verifier_completed_event(
        sequence=9,
        verdict_id="verdict-1",
    )

    state = build_workflow_state(
        session_id="session-a",
        events=[
            initial_artifact,
            latest_job,
            initial_job,
            latest_artifact,
            latest_job.model_copy(),
            latest_artifact.model_copy(),
            metric,
            metric.model_copy(),
            log_ref,
            log_ref.model_copy(),
            evidence_item,
            evidence_item.model_copy(),
            claim_link,
            claim_link.model_copy(),
            verifier_verdict,
            verifier_verdict.model_copy(),
        ],
    )

    assert len(state.active_jobs) == 1
    assert state.active_jobs[0]["job_id"] == "active-job-1"
    assert state.active_jobs[0]["status"] == "running"
    assert state.evidence_summary["artifact_count"] == 1
    assert state.evidence_summary["metric_count"] == 1
    assert state.evidence_summary["log_count"] == 1
    assert state.evidence_summary["evidence_count"] == 1
    assert state.evidence_summary["claim_count"] == 1
    assert state.evidence_summary["claim_link_count"] == 1
    assert state.evidence_summary["verifier_count"] == 1
    assert state.evidence_summary["verifier_status"] == "passed"
    assert [
        _summary_item_id(item)
        for item in state.evidence_summary["items"]
    ] == [
        "artifact-1",
        "metric-1",
        "log-1",
        "evidence-1",
        "evidence-link-1",
        "verdict-1",
    ]
    assert state.evidence_summary["items"][0]["label"] == "Final checkpoint"


def test_duplicate_evidence_ids_with_new_events_keep_latest_in_workflow_summary():
    initial_evidence = make_evidence_item_recorded_event(
        sequence=1,
        evidence_id="evidence-1",
        title="Initial evidence",
    )
    latest_evidence = make_evidence_item_recorded_event(
        sequence=2,
        evidence_id="evidence-1",
        title="Latest evidence",
        event_id="event-evidence-latest",
    )
    initial_link = make_evidence_claim_link_recorded_event(
        sequence=3,
        link_id="evidence-link-1",
        evidence_id="evidence-1",
        claim_id="claim-initial",
    )
    latest_link = make_evidence_claim_link_recorded_event(
        sequence=4,
        link_id="evidence-link-1",
        evidence_id="evidence-1",
        claim_id="claim-latest",
        event_id="event-link-latest",
    )

    state = build_workflow_state(
        session_id="session-a",
        events=[initial_evidence, latest_evidence, initial_link, latest_link],
    )

    assert state.evidence_summary["evidence_count"] == 1
    assert state.evidence_summary["claim_count"] == 1
    assert state.evidence_summary["claim_link_count"] == 1
    assert [
        _summary_item_id(item)
        for item in state.evidence_summary["items"]
    ] == ["evidence-1", "evidence-link-1"]
    assert state.evidence_summary["items"][0]["title"] == "Latest evidence"
    assert state.evidence_summary["items"][1]["claim_id"] == "claim-latest"


def test_turn_complete_clears_event_pending_approvals_and_marks_completed():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_event(
                sequence=1,
                event_type="approval_required",
                data={
                    "tools": [
                        {
                            "tool": "sandbox",
                            "tool_call_id": "tc-1",
                            "arguments": {},
                        }
                    ],
                    "count": 1,
                },
            ),
            make_event(
                sequence=2,
                event_type="turn_complete",
                data={"history_size": 4},
            ),
        ],
    )

    assert state.pending_approvals == []
    assert state.status == "completed"
    assert state.resume.model_dump() == {
        "event_sequence": 2,
        "can_resume": False,
        "reason": "executable_resume_not_implemented",
    }


def test_durable_pending_approval_and_active_job_refs_are_included(tmp_path):
    clock = DeterministicClock()
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite", clock=clock)
    record = store.create(
        session_id="session-a",
        owner_id="alice",
        model="test/model",
        pending_approval_refs=[{"tool_call_id": "tc-durable", "tool": "hf_jobs"}],
        active_job_refs=[{"job_id": "job-durable"}],
    )

    state = build_workflow_state(
        session_id="session-a",
        events=[],
        session_record=record,
    )

    assert state.status == "waiting_approval"
    assert state.pending_approvals == [
        {"source": "durable", "tool_call_id": "tc-durable", "tool": "hf_jobs"}
    ]
    assert state.active_jobs == [{"source": "durable", "job_id": "job-durable"}]
    assert state.compatibility.stale is True


def test_duplicate_replay_events_are_deduplicated():
    event = make_event(
        sequence=1,
        event_type="tool_state_change",
        data={
            "tool": "hf_jobs",
            "tool_call_id": "tc-1",
            "state": "running",
        },
    )

    state = build_workflow_state(
        session_id="session-a",
        events=[event, event.model_copy()],
    )

    assert len(state.active_jobs) == 1
    assert state.last_event_sequence == 1


def test_phase_events_project_current_workflow_phase():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_event(
                sequence=1,
                event_type="phase.started",
                data={
                    "session_id": "session-a",
                    "project_id": "session:session-a",
                    "template_id": "mnist-baseline",
                    "template_version": "v1",
                    "phase_id": "train",
                    "phase_name": "Train",
                    "to_status": "active",
                },
            ),
            make_event(
                sequence=2,
                event_type="phase.completed",
                data={
                    "session_id": "session-a",
                    "project_id": "session:session-a",
                    "template_id": "mnist-baseline",
                    "template_version": "v1",
                    "phase_id": "train",
                    "phase_name": "Train",
                    "to_status": "complete",
                    "gate_status": "satisfied",
                    "waiver_records": [
                        {"output_id": "metrics-json", "approved_by": "alice"}
                    ],
                },
            ),
        ],
    )

    assert state.status == "completed"
    assert state.phase.model_dump() == {
        "id": "train",
        "label": "Train",
        "status": "complete",
        "started_at": "2026-01-02T03:04:01+00:00",
        "updated_at": "2026-01-02T03:04:02+00:00",
    }
    assert state.blockers == []


def test_phase_blocked_event_projects_gate_blocker_with_verifier_pending():
    state = build_workflow_state(
        session_id="session-a",
        events=[
            make_event(
                sequence=1,
                event_type="phase.blocked",
                data={
                    "session_id": "session-a",
                    "project_id": "session:session-a",
                    "template_id": "mnist-baseline",
                    "template_version": "v1",
                    "phase_id": "train",
                    "phase_name": "Train",
                    "requested_status": "complete",
                    "to_status": "blocked",
                    "gate_status": "verifier_pending",
                    "missing_outputs": [],
                    "pending_verifiers": ["accuracy-threshold"],
                    "failed_verifiers": [],
                    "waiver_records": [],
                },
            )
        ],
    )

    assert state.status == "blocked"
    assert state.phase.id == "train"
    assert state.phase.status == "blocked"
    assert state.blockers == [
        {
            "source": "event",
            "type": "phase_gate",
            "source_event_sequence": 1,
            "updated_at": "2026-01-02T03:04:01+00:00",
            "phase_id": "train",
            "gate_status": "verifier_pending",
            "requested_status": "complete",
            "to_status": "blocked",
            "missing_outputs": [],
            "pending_verifiers": ["accuracy-threshold"],
            "failed_verifiers": [],
            "waiver_records": [],
        }
    ]


def test_stale_no_event_session_uses_explicit_placeholders(tmp_path):
    clock = DeterministicClock()
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite", clock=clock)
    record = store.create(
        session_id="session-a",
        owner_id="alice",
        model="test/model",
    )

    state = build_workflow_state(
        session_id="session-a",
        events=[],
        session_record=record,
    )

    assert state.status == "stale"
    assert state.objective.model_dump() == {
        "text": None,
        "source": "placeholder",
        "updated_at": None,
    }
    assert state.live_tracking_refs == [
        {
            "provider": "trackio",
            "enabled": False,
            "status": "placeholder",
            "space_id": None,
            "project": "session:session-a",
            "run_id": None,
            "tool_call_id": None,
            "url": None,
            "source": "compatibility",
        }
    ]
    assert state.compatibility.model_dump() == {
        "stale": True,
        "missing_producers": [
            "workflow_events",
            "budget_ledger",
            "evidence_ledger",
            "live_tracking",
        ],
    }


def test_operation_refs_exclude_operation_payload_result_and_error(tmp_path):
    clock = DeterministicClock()
    store = SQLiteOperationStore(tmp_path / "operations.sqlite", clock=clock)
    created = store.create(
        operation_id="op-1",
        session_id="session-a",
        operation_type="user_input",
        payload={"secret": "kept out"},
        idempotency_key="idem-1",
    )
    store.transition_status("op-1", OPERATION_RUNNING)

    state = build_workflow_state(
        session_id="session-a",
        events=[],
        operations=store.list_by_session("session-a"),
    )

    assert state.operation_refs == [
        {
            "id": "op-1",
            "type": "user_input",
            "status": "running",
            "idempotency_key": "idem-1",
            "created_at": created.created_at.isoformat(),
            "updated_at": "2026-01-02T03:04:06+00:00",
        }
    ]
    assert "payload" not in state.operation_refs[0]
    assert "result" not in state.operation_refs[0]
    assert "error" not in state.operation_refs[0]


async def test_workflow_route_returns_for_durable_only_session(monkeypatch, tmp_path):
    clock = DeterministicClock()
    manager = session_module.SessionManager(
        event_store=SQLiteEventStore(tmp_path / "events.sqlite"),
        operation_store=SQLiteOperationStore(tmp_path / "operations.sqlite", clock=clock),
        session_store=SQLiteSessionStore(tmp_path / "sessions.sqlite", clock=clock),
    )
    manager.session_store.create(
        session_id="session-durable",
        owner_id="alice",
        model="test/model",
        active_job_refs=[{"job_id": "job-1"}],
    )
    assert manager.sessions == {}

    monkeypatch.setattr(agent_routes, "session_manager", manager)

    state = await agent_routes.get_session_workflow(
        "session-durable",
        {"user_id": "alice"},
    )

    assert state.session_id == "session-durable"
    assert state.project_id == "session:session-durable"
    assert state.status == "processing"
    assert state.active_jobs == [{"source": "durable", "job_id": "job-1"}]
