from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent.core.events import AgentEvent
from agent.core.handoff_commands import (
    render_handoff_command,
    render_handoff_preview,
)
from backend.decision_proof_ledger import DECISION_CARD_RECORDED_EVENT
from backend.evidence_ledger import (
    EVIDENCE_ITEM_RECORDED_EVENT,
    evidence_item_recorded_payload,
)
from backend.job_artifact_refs import (
    ACTIVE_JOB_RECORDED_EVENT,
    ARTIFACT_REF_RECORDED_EVENT,
)
from backend.models import EvidenceItemRecord


def test_handoff_preview_renders_current_session_snapshot_without_secrets() -> None:
    secret = "hf_handoffsecret123456789"
    session = _session_from_events(
        make_event(
            sequence=1,
            event_type="phase.started",
            data={
                "session_id": "session-a",
                "phase_id": "prep",
                "phase_name": "Prepare",
            },
        ),
        make_event(
            sequence=2,
            event_type="phase.completed",
            data={
                "session_id": "session-a",
                "phase_id": "prep",
                "phase_name": "Prepare",
            },
        ),
        make_event(
            sequence=3,
            event_type="phase.started",
            data={
                "session_id": "session-a",
                "phase_id": "eval",
                "phase_name": "Evaluate",
            },
        ),
        make_event(
            sequence=4,
            event_type="phase.blocked",
            data={
                "session_id": "session-a",
                "phase_id": "eval",
                "phase_name": "Evaluate",
                "missing_outputs": ["metrics-json"],
            },
        ),
        make_active_job_event(sequence=5),
        make_evidence_event(
            sequence=6,
            title=f"Metric evidence Authorization: Bearer {secret}",
        ),
        make_event(
            sequence=7,
            event_type="approval_required",
            data={
                "tools": [
                    {
                        "tool": "train_model",
                        "arguments": {"token": secret},
                        "tool_call_id": "tc-approve",
                    }
                ],
                "count": 1,
            },
        ),
        make_event(
            sequence=8,
            event_type=DECISION_CARD_RECORDED_EVENT,
            data={
                "session_id": "session-a",
                "decision_id": "decision-1",
                "source_event_sequence": 8,
                "title": "Choose validation metric",
                "decision": f"Use metric without bearer {secret}",
                "status": "accepted",
                "evidence_ids": ["evidence-1"],
                "artifact_ids": ["artifact-1"],
                "metadata": {},
                "privacy_class": "private",
                "redaction_status": "none",
            },
        ),
        make_event(
            sequence=9,
            event_type=ARTIFACT_REF_RECORDED_EVENT,
            data={
                "session_id": "session-a",
                "artifact_id": "artifact-1",
                "source_event_sequence": 9,
                "type": "model_checkpoint",
                "source": "remote_uri",
                "ref_uri": "mlj://session/session-a/artifact/artifact-1",
                "uri": f"https://artifacts.example/model.pt?token={secret}",
                "privacy_class": "private",
                "redaction_status": "none",
            },
        ),
    )

    output = render_handoff_preview(session=session)

    assert output.startswith("Handoff preview\n")
    assert "session: session-a" in output
    assert "status: waiting_approval" in output
    assert "last event: 9" in output
    assert "phase: eval (Evaluate, blocked)" in output
    assert (
        "counts: completed_phases=1 blockers=1 pending_approvals=1 "
        "jobs=1 decisions=1 evidence=1 artifacts=1 failures=0 risks=1"
    ) in output
    assert "prep (Prepare) seq:2" in output
    assert "phase_gate phase:eval missing:metrics-json" in output
    assert "tc-approve tool:train_model" in output
    assert "job-1 running tool:train" in output
    assert "decision-1 Use metric without bearer [REDACTED]" in output
    assert "evidence:evidence-1" in output
    assert "artifact-1 ref:mlj://session/session-a/artifact/artifact-1" in output
    assert "risks:\n    phase_gate -" in output
    assert secret not in output


def test_handoff_preview_handles_empty_missing_and_rejects_args() -> None:
    empty_session = _session_from_events()

    assert render_handoff_preview(session=None) == (
        "Handoff preview\n  no active session"
    )
    assert render_handoff_preview("handoff.md", session=empty_session) == (
        "Handoff preview\n  Usage: /handoff preview"
    )

    output = render_handoff_command("/handoff preview", session=empty_session)

    assert "status: stale" in output
    assert "last event: 0" in output
    assert "phase: -" in output
    assert "completed phases:\n    -" in output


def test_handoff_preview_rejects_unknown_command() -> None:
    with pytest.raises(ValueError, match="Unsupported handoff command"):
        render_handoff_command("/handoff", session=_session_from_events())


async def test_main_handler_dispatches_read_only_handoff_preview(
    monkeypatch,
    capsys,
) -> None:
    import agent.main as main_module

    calls = []
    session = object()

    def fake_render(command: str, arguments: str, **kwargs) -> str:
        calls.append((command, arguments, kwargs.get("session")))
        return "handoff body"

    monkeypatch.setattr(main_module, "render_handoff_command", fake_render)

    result = await main_module._handle_slash_command(
        "/handoff preview",
        config=object(),
        session_holder=[session],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )

    assert result is None
    assert calls == [("/handoff preview", "", session)]
    assert "handoff body" in capsys.readouterr().out


def _session_from_events(*events: AgentEvent):
    redacted = [event.redacted_copy() for event in events]
    return SimpleNamespace(
        session_id="session-a",
        logged_events=[
            {
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type,
                "data": event.data,
            }
            for event in redacted
        ],
        event_metadata=[
            {
                "event_id": event.id,
                "sequence": event.sequence,
                "timestamp": event.timestamp.isoformat(),
                "schema_version": event.schema_version,
                "redaction_status": event.redaction_status,
            }
            for event in redacted
        ],
    )


def make_event(
    *,
    sequence: int,
    event_type: str,
    data: dict,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=data,
    )


def make_active_job_event(*, sequence: int) -> AgentEvent:
    return make_event(
        sequence=sequence,
        event_type=ACTIVE_JOB_RECORDED_EVENT,
        data={
            "session_id": "session-a",
            "job_id": "job-1",
            "source_event_sequence": sequence,
            "tool_call_id": "tc-1",
            "tool": "train",
            "provider": "local",
            "status": "running",
            "redaction_status": "none",
            "started_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    )


def make_evidence_event(*, sequence: int, title: str) -> AgentEvent:
    record = EvidenceItemRecord.model_validate(
        {
            "session_id": "session-a",
            "evidence_id": "evidence-1",
            "source_event_sequence": sequence,
            "kind": "metric",
            "source": "metric",
            "title": title,
            "summary": "Validation metric is ready.",
            "metric_id": "metric-1",
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        }
    )
    return make_event(
        sequence=sequence,
        event_type=EVIDENCE_ITEM_RECORDED_EVENT,
        data=evidence_item_recorded_payload(record),
    )
