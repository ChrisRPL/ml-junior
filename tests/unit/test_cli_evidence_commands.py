from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent.core.evidence_commands import (
    render_assumption_index,
    render_decision_index,
    render_evidence_command,
    render_evidence_index,
)
from agent.core.events import AgentEvent
from backend.assumption_ledger import ASSUMPTION_RECORDED_EVENT
from backend.decision_proof_ledger import (
    DECISION_CARD_RECORDED_EVENT,
    PROOF_BUNDLE_RECORDED_EVENT,
)
from backend.evidence_ledger import (
    EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
    EVIDENCE_ITEM_RECORDED_EVENT,
    evidence_claim_link_recorded_payload,
    evidence_item_recorded_payload,
)
from backend.experiment_ledger import LOG_REF_RECORDED_EVENT, METRIC_RECORDED_EVENT
from backend.job_artifact_refs import ARTIFACT_REF_RECORDED_EVENT
from backend.models import EvidenceClaimLinkRecord, EvidenceItemRecord
from backend.verifier_ledger import VERIFIER_COMPLETED_EVENT


def test_evidence_index_renders_latest_records_and_filters_redacted() -> None:
    secret = "hf_evidencesecret123456789"
    session = _session_from_events(
        make_evidence_item_event(
            sequence=1,
            evidence_id="evidence-accuracy",
            title="Initial evidence",
            summary="Superseded",
        ),
        make_evidence_item_event(
            sequence=2,
            evidence_id="evidence-accuracy",
            title=f"Accuracy threshold Authorization: Bearer {secret}",
            summary=f"Validation metric is above baseline with token={secret}",
            uri=f"https://evidence.example/item?token={secret}",
        ),
        make_claim_link_event(
            sequence=3,
            link_id="evidence-link-accuracy",
            evidence_id="evidence-accuracy",
            claim_id="claim-accuracy",
            rationale=f"Metric supports claim with bearer {secret}",
        ),
    )

    output = render_evidence_index(session=session)
    filtered = render_evidence_command("/evidence", "claim-accuracy", session=session)

    assert output.startswith("Evidence\n")
    assert "counts: evidence=1 claim_links=1" in output
    assert "evidence-accuracy  metric  source:metric  metric:metric-1" in output
    assert "Initial evidence" not in output
    assert "Accuracy threshold Authorization: Bearer [REDACTED]" in output
    assert "token=[REDACTED]" in output
    assert "link:evidence-link-accuracy  supports" in output
    assert secret not in output
    assert "evidence-link-accuracy" in filtered
    assert "Accuracy threshold" not in filtered
    assert secret not in filtered


def test_evidence_index_handles_empty_missing_and_secret_filters() -> None:
    empty_session = _session_from_events()
    secret = "hf_evidencefilter123456789"

    assert render_evidence_index(session=None) == "Evidence\n  no active session"
    assert render_evidence_index(session=empty_session) == (
        "Evidence\n  no evidence recorded for this session"
    )
    assert render_evidence_index(secret, session=empty_session) == (
        "Evidence\n  no evidence match filter: [REDACTED]"
    )


def test_evidence_index_renders_workflow_evidence_summary_rows() -> None:
    secret = "hf_summarysecret123456789"
    session = _session_from_events(
        make_metric_event(sequence=1, metric_id="metric-loss"),
        make_log_event(sequence=2, log_id="log-train"),
        make_artifact_event(
            sequence=3,
            artifact_id="artifact-model",
            uri=f"https://artifacts.example/model.pt?token={secret}",
        ),
        make_verifier_event(sequence=4, verdict_id="verdict-claims"),
        make_decision_event(sequence=5, decision_id="decision-metric"),
        make_assumption_event(sequence=6, assumption_id="assumption-labels"),
        make_proof_event(sequence=7, proof_bundle_id="proof-report"),
    )

    output = render_evidence_index(session=session)

    assert (
        "counts: artifacts=1 metrics=1 logs=1 decisions=1 assumptions=1 "
        "proof_bundles=1 verifiers=1"
    ) in output
    assert "metric:metric-loss  loss=0.2  source:tool  step:3" in output
    assert "log:log-train  source:stdout  ref:file:///tmp/log-train.log" in output
    assert "artifact:artifact-model  model_checkpoint  source:remote_uri" in output
    assert "token=[REDACTED]" in output
    assert "verifier:verdict-claims  verdict:passed" in output
    assert "decision:decision-metric  status:accepted" in output
    assert "assumption:assumption-labels  status:open  confidence:unknown" in output
    assert "statement: Validation labels are stable." in output
    assert "proof_bundle:proof-report  status:complete" in output
    assert secret not in output


def test_evidence_index_rejects_unknown_command() -> None:
    with pytest.raises(ValueError, match="Unsupported evidence command"):
        render_evidence_command("/ledger", session=_session_from_events())


def test_decision_index_renders_decision_cards_and_filters_redacted() -> None:
    secret = "hf_decisionfilter123456789"
    session = _session_from_events(
        make_decision_event(
            sequence=1,
            decision_id="decision-metric-old",
            title="Superseded metric",
            decision="Use accuracy.",
        ),
        make_decision_event(
            sequence=2,
            decision_id="decision-metric",
            title=f"Choose validation metric {secret}",
            decision=f"Use validation loss with token={secret}.",
            rationale=f"Stable across runs Authorization: Bearer {secret}",
        ),
        make_evidence_item_event(
            sequence=3,
            evidence_id="evidence-loss",
            title="Loss evidence",
            summary="Supports the decision.",
        ),
    )

    output = render_decision_index(session=session)
    filtered = render_evidence_command(
        "/decisions",
        "validation loss",
        session=session,
    )

    assert output.startswith("Decisions\n")
    assert "counts: decisions=2" in output
    assert "decision:decision-metric  status:accepted  event:2" in output
    assert "evidence:evidence-1" in output
    assert "artifacts:artifact-model" in output
    assert "proof_bundles:proof-report" in output
    assert "Choose validation metric [REDACTED]" in output
    assert "token=[REDACTED]" in output
    assert "Authorization: Bearer [REDACTED]" in output
    assert "Loss evidence" not in output
    assert "decision-metric" in filtered
    assert "decision-metric-old" not in filtered
    assert secret not in output
    assert secret not in filtered


def test_decision_index_handles_empty_missing_and_secret_filters() -> None:
    empty_session = _session_from_events()
    secret = "hf_decisionfilter123456789"

    assert render_decision_index(session=None) == "Decisions\n  no active session"
    assert render_decision_index(session=empty_session) == (
        "Decisions\n  no decisions recorded for this session"
    )
    assert render_decision_index(secret, session=empty_session) == (
        "Decisions\n  no decisions match filter: [REDACTED]"
    )


def test_assumption_index_renders_assumption_records_and_filters_redacted() -> None:
    secret = "hf_assumptionfilter123456789"
    session = _session_from_events(
        make_assumption_event(
            sequence=1,
            assumption_id="assumption-old",
            title="Old assumption",
            statement="Superseded assumption.",
        ),
        make_assumption_event(
            sequence=2,
            assumption_id="assumption-labels",
            title=f"Dataset label stability {secret}",
            statement=f"Validation labels are stable with token={secret}.",
            rationale=f"Dataset card says this Authorization: Bearer {secret}",
            validation_notes=f"Refresh after update {secret}.",
            phase_id="phase-eval",
            run_id="run-gpqa",
        ),
        make_decision_event(
            sequence=3,
            decision_id="decision-metric",
            title="Decision should not render",
        ),
    )

    output = render_assumption_index(session=session)
    filtered = render_evidence_command(
        "/assumptions",
        "validation labels",
        session=session,
    )

    assert output.startswith("Assumptions\n")
    assert "counts: assumptions=2" in output
    assert (
        "assumption:assumption-labels  status:open  confidence:unknown  event:2"
        in output
    )
    assert "phase:phase-eval" in output
    assert "run:run-gpqa" in output
    assert "decisions:decision-metric" in output
    assert "evidence:evidence-1" in output
    assert "artifacts:artifact-model" in output
    assert "proof_bundles:proof-report" in output
    assert "Dataset label stability [REDACTED]" in output
    assert "token=[REDACTED]" in output
    assert "Authorization: Bearer [REDACTED]" in output
    assert "Decision should not render" not in output
    assert "assumption-labels" in filtered
    assert "assumption-old" not in filtered
    assert secret not in output
    assert secret not in filtered


def test_assumption_index_handles_empty_missing_and_secret_filters() -> None:
    empty_session = _session_from_events()
    secret = "hf_assumptionfilter123456789"

    assert render_assumption_index(session=None) == "Assumptions\n  no active session"
    assert render_assumption_index(session=empty_session) == (
        "Assumptions\n  no assumptions recorded for this session"
    )
    assert render_assumption_index(secret, session=empty_session) == (
        "Assumptions\n  no assumptions match filter: [REDACTED]"
    )


async def test_main_handler_dispatches_read_only_evidence_command(
    monkeypatch,
    capsys,
) -> None:
    import agent.main as main_module

    calls = []
    session = object()

    def fake_render(command: str, arguments: str, **kwargs) -> str:
        calls.append((command, arguments, kwargs.get("session")))
        return "evidence body"

    monkeypatch.setattr(main_module, "render_evidence_command", fake_render)

    result = await main_module._handle_slash_command(
        "/evidence accuracy",
        config=object(),
        session_holder=[session],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )

    assert result is None
    assert calls == [("/evidence", "accuracy", session)]
    assert "evidence body" in capsys.readouterr().out


async def test_main_handler_dispatches_read_only_decisions_command(
    monkeypatch,
    capsys,
) -> None:
    import agent.main as main_module

    calls = []
    session = object()

    def fake_render(command: str, arguments: str, **kwargs) -> str:
        calls.append((command, arguments, kwargs.get("session")))
        return "decisions body"

    monkeypatch.setattr(main_module, "render_evidence_command", fake_render)

    result = await main_module._handle_slash_command(
        "/decisions metric",
        config=object(),
        session_holder=[session],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )

    assert result is None
    assert calls == [("/decisions", "metric", session)]
    assert "decisions body" in capsys.readouterr().out


async def test_main_handler_dispatches_read_only_assumptions_command(
    monkeypatch,
    capsys,
) -> None:
    import agent.main as main_module

    calls = []
    session = object()

    def fake_render(command: str, arguments: str, **kwargs) -> str:
        calls.append((command, arguments, kwargs.get("session")))
        return "assumptions body"

    monkeypatch.setattr(main_module, "render_evidence_command", fake_render)

    result = await main_module._handle_slash_command(
        "/assumptions labels",
        config=object(),
        session_holder=[session],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )

    assert result is None
    assert calls == [("/assumptions", "labels", session)]
    assert "assumptions body" in capsys.readouterr().out


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


def make_evidence_item_event(
    *,
    sequence: int,
    evidence_id: str,
    title: str,
    summary: str,
    uri: str | None = None,
) -> AgentEvent:
    record = EvidenceItemRecord.model_validate(
        {
            "session_id": "session-a",
            "evidence_id": evidence_id,
            "source_event_sequence": sequence,
            "kind": "metric",
            "source": "metric",
            "title": title,
            "summary": summary,
            "metric_id": "metric-1",
            "uri": uri,
            "metadata": {"note": "not-rendered"},
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        }
    )
    return AgentEvent(
        id=f"event-evidence-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=EVIDENCE_ITEM_RECORDED_EVENT,
        data=evidence_item_recorded_payload(record),
    )


def make_claim_link_event(
    *,
    sequence: int,
    link_id: str,
    evidence_id: str,
    claim_id: str,
    rationale: str,
) -> AgentEvent:
    record = EvidenceClaimLinkRecord.model_validate(
        {
            "session_id": "session-a",
            "link_id": link_id,
            "claim_id": claim_id,
            "evidence_id": evidence_id,
            "source_event_sequence": sequence,
            "relation": "supports",
            "strength": "strong",
            "rationale": rationale,
            "metadata": {"note": "not-rendered"},
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        }
    )
    return AgentEvent(
        id=f"event-link-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
        data=evidence_claim_link_recorded_payload(record),
    )


def make_metric_event(*, sequence: int, metric_id: str) -> AgentEvent:
    return AgentEvent(
        id=f"event-metric-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=METRIC_RECORDED_EVENT,
        data={
            "session_id": "session-a",
            "metric_id": metric_id,
            "source_event_sequence": sequence,
            "name": "loss",
            "value": 0.2,
            "source": "tool",
            "step": 3,
            "unit": "ratio",
            "recorded_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    )


def make_log_event(*, sequence: int, log_id: str) -> AgentEvent:
    return AgentEvent(
        id=f"event-log-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=LOG_REF_RECORDED_EVENT,
        data={
            "session_id": "session-a",
            "log_id": log_id,
            "source_event_sequence": sequence,
            "source": "stdout",
            "uri": f"file:///tmp/{log_id}.log",
            "label": "training log",
        },
    )


def make_artifact_event(
    *,
    sequence: int,
    artifact_id: str,
    uri: str,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-artifact-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=ARTIFACT_REF_RECORDED_EVENT,
        data={
            "session_id": "session-a",
            "artifact_id": artifact_id,
            "source_event_sequence": sequence,
            "type": "model_checkpoint",
            "source": "remote_uri",
            "ref_uri": "mlj://session/session-a/artifact/artifact-model",
            "uri": uri,
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    )


def make_verifier_event(*, sequence: int, verdict_id: str) -> AgentEvent:
    return AgentEvent(
        id=f"event-verifier-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=VERIFIER_COMPLETED_EVENT,
        data={
            "session_id": "session-a",
            "verdict_id": verdict_id,
            "verifier_id": "final-claims-have-evidence",
            "source_event_sequence": sequence,
            "verdict": "passed",
            "scope": "final_answer",
            "run_id": "run-1",
            "evidence_ids": ["evidence-1"],
            "claim_ids": ["claim-1"],
            "summary": "Claims have evidence.",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    )


def make_decision_event(
    *,
    sequence: int,
    decision_id: str,
    title: str = "Choose validation metric",
    decision: str = "Use validation loss as the promotion metric.",
    rationale: str = "It is stable across runs.",
) -> AgentEvent:
    return AgentEvent(
        id=f"event-decision-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=DECISION_CARD_RECORDED_EVENT,
        data={
            "session_id": "session-a",
            "decision_id": decision_id,
            "source_event_sequence": sequence,
            "title": title,
            "decision": decision,
            "status": "accepted",
            "rationale": rationale,
            "evidence_ids": ["evidence-1"],
            "claim_ids": ["claim-1"],
            "artifact_ids": ["artifact-model"],
            "proof_bundle_ids": ["proof-report"],
            "metadata": {},
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    )


def make_assumption_event(
    *,
    sequence: int,
    assumption_id: str,
    title: str = "Dataset label stability",
    statement: str = "Validation labels are stable.",
    rationale: str = "Dataset card documents this assumption.",
    validation_notes: str = "Needs refresh after data update.",
    phase_id: str | None = None,
    run_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-assumption-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=ASSUMPTION_RECORDED_EVENT,
        data={
            "session_id": "session-a",
            "assumption_id": assumption_id,
            "source_event_sequence": sequence,
            "title": title,
            "statement": statement,
            "status": "open",
            "confidence": "unknown",
            "phase_id": phase_id,
            "run_id": run_id,
            "decision_ids": ["decision-metric"],
            "evidence_ids": ["evidence-1"],
            "claim_ids": ["claim-1"],
            "artifact_ids": ["artifact-model"],
            "proof_bundle_ids": ["proof-report"],
            "rationale": rationale,
            "validation_notes": validation_notes,
            "metadata": {},
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    )


def make_proof_event(*, sequence: int, proof_bundle_id: str) -> AgentEvent:
    return AgentEvent(
        id=f"event-proof-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=PROOF_BUNDLE_RECORDED_EVENT,
        data={
            "session_id": "session-a",
            "proof_bundle_id": proof_bundle_id,
            "source_event_sequence": sequence,
            "title": "Promotion evidence bundle",
            "summary": "The selected checkpoint has supporting evidence.",
            "status": "complete",
            "scope": "final_report",
            "decision_ids": ["decision-metric"],
            "evidence_ids": ["evidence-1"],
            "claim_ids": ["claim-1"],
            "artifact_ids": ["artifact-model"],
            "verifier_verdict_ids": ["verdict-claims"],
            "metadata": {},
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
    )
