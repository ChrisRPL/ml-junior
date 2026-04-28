from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.evaluator import OfflineFixtureEvaluator
from evals.schemas import GoldenTrace, VerifierVerdict, load_golden_trace, load_verifier_verdict


def test_golden_trace_fixtures_validate(fixtures_root: Path):
    paths = sorted((fixtures_root / "golden_traces").glob("*.json"))

    assert [path.name for path in paths] == ["replay_trace.json"]
    traces = [load_golden_trace(path) for path in paths]

    assert [trace.name for trace in traces] == ["offline_replay_trace"]
    assert all(trace.mode == "offline" for trace in traces)
    assert traces[0].ignore_fields == ["id", "timestamp"]


def test_golden_trace_expected_replay_is_deterministic(fixtures_root: Path):
    trace = load_golden_trace(fixtures_root / "golden_traces" / "replay_trace.json")
    after_sequence = trace.expected["replay_after_sequence"]["sequence"]

    replayed = [
        event
        for event in trace.events
        if event.session_id == trace.inputs["session_id"]
        and event.sequence > after_sequence
    ]

    assert [event.event_type for event in replayed] == ["tool_output", "turn_complete"]
    assert [event.event_type for event in replayed] == trace.expected["replay_after_sequence"]["event_types"]
    assert trace.events[-1].event_type == trace.expected["terminal_event"]
    assert {
        str(event.sequence): event.redaction_status
        for event in trace.events
    } == trace.expected["redaction_status_by_sequence"]
    assert all(set(event.legacy_sse.model_dump()) == {"event_type", "data"} for event in trace.events)


def test_golden_trace_schema_rejects_legacy_sse_mismatch():
    with pytest.raises(ValidationError):
        GoldenTrace.model_validate(
            {
                "schema_version": 1,
                "name": "bad",
                "mode": "offline",
                "inputs": {},
                "events": [
                    {
                        "schema_version": 1,
                        "session_id": "session-a",
                        "sequence": 1,
                        "event_type": "processing",
                        "data": {"message": "one"},
                        "legacy_sse": {
                            "event_type": "processing",
                            "data": {"message": "different"},
                        },
                    }
                ],
                "expected": {},
                "ignore_fields": [],
            }
        )


def test_golden_trace_schema_rejects_duplicate_session_sequence():
    with pytest.raises(ValidationError):
        GoldenTrace.model_validate(
            {
                "schema_version": 1,
                "name": "bad",
                "mode": "offline",
                "inputs": {},
                "events": [
                    {
                        "schema_version": 1,
                        "session_id": "session-a",
                        "sequence": 1,
                        "event_type": "processing",
                        "data": {},
                    },
                    {
                        "schema_version": 1,
                        "session_id": "session-a",
                        "sequence": 1,
                        "event_type": "tool_output",
                        "data": {},
                    },
                ],
                "expected": {},
                "ignore_fields": [],
            }
        )


def test_verifier_verdict_fixtures_validate(fixtures_root: Path):
    paths = sorted((fixtures_root / "verifier_verdicts").glob("*.json"))

    assert [path.name for path in paths] == ["verifier_evidence.json"]
    verdict = load_verifier_verdict(paths[0])

    assert verdict.verdict == "fail"
    assert [check.status for check in verdict.checks] == ["pass", "fail"]
    assert verdict.claims[1].evidence_refs == []


def test_verifier_schema_rejects_missing_evidence_ref():
    with pytest.raises(ValidationError):
        VerifierVerdict.model_validate(
            {
                "claims": [
                    {
                        "id": "claim-a",
                        "text": "A claim with missing evidence.",
                        "evidence_refs": ["missing-evidence"],
                    }
                ],
                "evidence": [],
                "checks": [
                    {
                        "name": "claim-a-supported",
                        "claim_id": "claim-a",
                        "status": "pass",
                        "reason": "Should not validate.",
                    }
                ],
                "verdict": "pass",
                "reason": "Should not validate.",
            }
        )


def test_offline_fixture_evaluator_interface(fixtures_root: Path):
    evaluator = OfflineFixtureEvaluator(fixtures_root)

    evaluator.prepare()
    result = evaluator.evaluate("run-offline-fixture")

    assert result.passed
    assert result.run_id == "run-offline-fixture"
    assert result.golden_traces == 1
    assert result.verifier_verdicts == 1
    assert evaluator.report() == result


def test_non_ci_markers_are_registered(pytestconfig):
    registered = {
        marker.split(":", maxsplit=1)[0]
        for marker in pytestconfig.getini("markers")
    }

    assert {"scheduled", "network", "gpu", "requires_hf_token"} <= registered


def test_fixture_json_is_stable(fixtures_root: Path):
    fixture_paths = sorted(fixtures_root.glob("*/*.json"))

    assert fixture_paths
    for path in fixture_paths:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        assert json.loads(json.dumps(payload, sort_keys=True)) == payload
