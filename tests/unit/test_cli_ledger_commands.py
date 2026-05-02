from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent.core.events import AgentEvent
from agent.core.ledger_commands import render_ledger_command, render_ledger_index


def test_ledger_index_renders_current_session_event_metadata_and_filters() -> None:
    secret = "hf_ledgersecret123456789"
    session = _session_from_events(
        make_tool_output_event(
            sequence=2,
            tool="shell",
            output=f"training complete Authorization: Bearer {secret}",
        ),
        make_assumption_event(
            sequence=1,
            assumption_id="assumption-labels",
            statement=f"Labels are stable with token={secret}.",
        ),
        make_custom_event(
            sequence=3,
            event_type="custom.progress",
            data={"phase_id": "phase-eval", "note": "Evaluation started."},
        ),
    )

    output = render_ledger_index(session=session)
    filtered = render_ledger_command("/ledger", "assumption-labels", session=session)

    assert output.startswith("Ledger\n")
    assert "counts: events=3" in output
    assert output.index("event-assumption-1") < output.index("event-tool-2")
    assert "assumption.recorded" in output
    assert "tool_output" in output
    assert "custom.progress" in output
    assert "refs: session:session-a  assumption:assumption-labels" in output
    assert "refs: tool:shell  tool_call:tool-call-2" in output
    assert "refs: phase:phase-eval" in output
    assert "data keys:" in output
    assert "assumption_id" in output
    assert "output,success,tool,tool_call_id" in output
    assert secret not in output
    assert "Authorization: Bearer" not in output
    assert "assumption-labels" in filtered
    assert "tool_output" not in filtered
    assert secret not in filtered


def test_ledger_index_handles_empty_missing_and_secret_filters() -> None:
    empty_session = _session_from_events()
    secret = "hf_ledgerfilter123456789"

    assert render_ledger_index(session=None) == "Ledger\n  no active session"
    assert render_ledger_index(session=empty_session) == (
        "Ledger\n  no ledger events recorded for this session"
    )
    assert render_ledger_index(secret, session=empty_session) == (
        "Ledger\n  no ledger events match filter: [REDACTED]"
    )


def test_ledger_command_dispatch_rejects_unexpected_commands() -> None:
    with pytest.raises(ValueError, match="Unsupported ledger command"):
        render_ledger_command("/ledger verify", session=_session_from_events())


async def test_main_handler_dispatches_read_only_ledger_command(
    monkeypatch,
    capsys,
) -> None:
    import agent.main as main_module

    calls = []
    session = object()

    def fake_render(command: str, arguments: str, **kwargs) -> str:
        calls.append((command, arguments, kwargs.get("session")))
        return "ledger body"

    monkeypatch.setattr(main_module, "render_ledger_command", fake_render)

    result = await main_module._handle_slash_command(
        "/ledger tool_output",
        config=object(),
        session_holder=[session],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )

    assert result is None
    assert calls == [("/ledger", "tool_output", session)]
    assert "ledger body" in capsys.readouterr().out


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


def make_tool_output_event(*, sequence: int, tool: str, output: str) -> AgentEvent:
    return AgentEvent(
        id=f"event-tool-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type="tool_output",
        data={
            "tool": tool,
            "tool_call_id": f"tool-call-{sequence}",
            "output": output,
            "success": True,
        },
    )


def make_assumption_event(
    *,
    sequence: int,
    assumption_id: str,
    statement: str,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-assumption-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type="assumption.recorded",
        data={
            "session_id": "session-a",
            "assumption_id": assumption_id,
            "source_event_sequence": sequence,
            "title": "Dataset label stability",
            "statement": statement,
            "status": "open",
            "confidence": "unknown",
            "decision_ids": [],
            "evidence_ids": [],
            "claim_ids": [],
            "artifact_ids": [],
            "proof_bundle_ids": [],
            "metadata": {},
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    )


def make_custom_event(
    *,
    sequence: int,
    event_type: str,
    data: dict[str, object],
) -> AgentEvent:
    return AgentEvent(
        id=f"event-custom-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=data,
    )
