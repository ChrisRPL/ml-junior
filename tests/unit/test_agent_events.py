from __future__ import annotations

import json

import pytest
from litellm import Message
from pydantic import ValidationError

from agent.core.events import AgentEvent, EVENT_PAYLOAD_MODELS
from agent.core.session import Event, Session
from backend.human_requests import (
    HUMAN_REQUEST_REQUESTED_EVENT,
    HUMAN_REQUEST_RESOLVED_EVENT,
)


def make_session(event_queue, test_config, fake_tool_router) -> Session:
    return Session(
        event_queue,
        config=test_config,
        tool_router=fake_tool_router,
        stream=False,
    )


async def test_send_event_envelopes_legacy_event_with_session_sequence(
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)

    await session.send_event(Event("processing", {"message": "one"}))
    await session.send_event(Event("assistant_message", {"content": "two"}))

    events = await event_collector(event_queue)

    assert [event.event_type for event in events] == [
        "processing",
        "assistant_message",
    ]
    assert [event.data for event in events] == [
        {"message": "one"},
        {"content": "two"},
    ]
    assert [event.sequence for event in events] == [1, 2]
    assert {event.session_id for event in events} == {session.session_id}
    assert all(isinstance(event, AgentEvent) for event in events)
    assert all(event.schema_version == 1 for event in events)
    assert all(event.redaction_status == "none" for event in events)
    assert events[0].id != events[1].id


async def test_legacy_sse_serialization_omits_envelope_metadata(
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)

    await session.send_event(Event("turn_complete", {"history_size": 3}))

    [event] = await event_collector(event_queue)

    assert event.to_legacy_sse() == {
        "event_type": "turn_complete",
        "data": {"history_size": 3},
    }
    assert set(event.to_legacy_sse()) == {"event_type", "data"}


async def test_logged_events_remain_legacy_trajectory_shape(
    event_queue,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)

    await session.send_event(Event("error", {"error": "boom"}))

    assert len(session.logged_events) == 1
    assert session.logged_events[0]["event_type"] == "error"
    assert session.logged_events[0]["data"] == {"error": "boom"}
    assert "timestamp" in session.logged_events[0]
    assert "sequence" not in session.logged_events[0]
    assert "redaction_status" not in session.logged_events[0]


async def test_send_event_nowait_uses_same_envelope_and_log_path(
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)

    session.send_event_nowait(Event("tool_log", {"tool": "sandbox", "log": "ready"}))

    [event] = await event_collector(event_queue)
    assert isinstance(event, AgentEvent)
    assert event.session_id == session.session_id
    assert event.sequence == 1
    assert event.to_legacy_sse() == {
        "event_type": "tool_log",
        "data": {"tool": "sandbox", "log": "ready"},
    }
    assert session.logged_events == [
        {
            "timestamp": event.timestamp.isoformat(),
            "event_type": "tool_log",
            "data": {"tool": "sandbox", "log": "ready"},
        }
    ]


async def test_events_are_redacted_before_queue_and_log(
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)
    secret = "hf_eventsecret123456789"

    await session.send_event(
        Event(
            "tool_output",
            {
                "tool": "hf_jobs",
                "tool_call_id": "tc_1",
                "output": f"Authorization: Bearer {secret}",
                "success": True,
            },
        )
    )

    [event] = await event_collector(event_queue)

    assert event.redaction_status == "partial"
    assert secret not in event.data["output"]
    assert event.to_legacy_sse() == {
        "event_type": "tool_output",
        "data": {
            "tool": "hf_jobs",
            "tool_call_id": "tc_1",
            "output": "Authorization: Bearer [REDACTED]",
            "success": True,
        },
    }
    assert secret not in str(session.logged_events)
    assert session.logged_events[0]["data"] == event.data


async def test_trajectory_includes_redacted_event_metadata_without_changing_events(
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)
    secret = "hf_exportsecret123456789"

    await session.send_event(
        Event(
            "tool_output",
            {
                "tool": "hf_jobs",
                "tool_call_id": "tc_export",
                "output": f"Authorization: Bearer {secret}",
                "success": True,
            },
        )
    )

    [event] = await event_collector(event_queue)
    trajectory = session.get_trajectory()

    assert trajectory["events"] == session.logged_events
    assert trajectory["events"][0] == {
        "timestamp": event.timestamp.isoformat(),
        "event_type": "tool_output",
        "data": {
            "tool": "hf_jobs",
            "tool_call_id": "tc_export",
            "output": "Authorization: Bearer [REDACTED]",
            "success": True,
        },
    }
    assert trajectory["event_metadata"] == [
        {
            "logged_event_index": 0,
            "event_id": event.id,
            "event_type": "tool_output",
            "sequence": 1,
            "timestamp": event.timestamp.isoformat(),
            "schema_version": 1,
            "redaction_status": "partial",
        }
    ]
    assert secret not in str(trajectory)


async def test_local_trajectory_save_exports_event_metadata_without_raw_secret(
    event_queue,
    fake_tool_router,
    test_config,
    tmp_path,
):
    session = make_session(event_queue, test_config, fake_tool_router)
    secret = "hf_savedsecret123456789"

    await session.send_event(
        Event(
            "tool_output",
            {
                "tool": "hf_jobs",
                "tool_call_id": "tc_saved",
                "output": f"Authorization: Bearer {secret}",
                "success": True,
            },
        )
    )

    filepath = session.save_trajectory_local(directory=str(tmp_path))

    assert filepath is not None
    saved = json.loads((tmp_path / filepath.split("/")[-1]).read_text())
    assert saved["events"] == session.logged_events
    assert saved["event_metadata"][0]["redaction_status"] == "partial"
    assert saved["event_metadata"][0]["logged_event_index"] == 0
    assert "redaction_status" not in saved["events"][0]
    assert secret not in json.dumps(saved)


def test_trajectory_redacts_messages_without_mutating_live_context(
    event_queue,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)
    secret = "hf_contextsecret123456789"
    raw_content = f"Use HF_TOKEN={secret} from /Users/alice/project"
    session.context_manager.add_message(Message(role="user", content=raw_content))

    trajectory = session.get_trajectory()

    assert secret in session.context_manager.items[-1].content
    assert "/Users/alice/project" in session.context_manager.items[-1].content
    assert secret not in str(trajectory["messages"])
    assert "/Users/alice" not in str(trajectory["messages"])
    assert "HF_TOKEN=[REDACTED]" in str(trajectory["messages"])
    assert "/Users/[USER]/project" in str(trajectory["messages"])


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("ready", {"message": "Agent initialized"}),
        ("processing", {"message": "Processing user input"}),
        ("assistant_message", {"content": "done"}),
        ("assistant_chunk", {"content": "chunk"}),
        ("assistant_stream_end", {}),
        (
            "tool_call",
            {"tool": "echo", "arguments": {"value": 1}, "tool_call_id": "tc_1"},
        ),
        (
            "tool_output",
            {
                "tool": "echo",
                "tool_call_id": "tc_1",
                "output": "ok",
                "success": True,
            },
        ),
        ("tool_log", {"tool": "system", "log": "working"}),
        (
            "approval_required",
            {
                "tools": [
                    {
                        "tool": "hf_jobs",
                        "arguments": {"operation": "run"},
                        "tool_call_id": "tc_2",
                    }
                ],
                "count": 1,
            },
        ),
        (
            "tool_state_change",
            {"tool": "hf_jobs", "tool_call_id": "tc_2", "state": "running"},
        ),
        ("turn_complete", {"history_size": 4}),
        ("compacted", {"old_tokens": 20, "new_tokens": 10}),
        ("error", {"error": "boom"}),
        ("shutdown", {}),
        ("interrupted", {}),
        ("undo_complete", {}),
        (
            "plan_update",
            {"plan": [{"id": "1", "content": "Do it", "status": "pending"}]},
        ),
    ],
)
def test_current_event_payloads_are_modeled(event_type, payload):
    event = AgentEvent(
        session_id="session-a",
        sequence=1,
        event_type=event_type,
        data=payload,
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data == payload


def _valid_human_request_requested_payload() -> dict:
    return {
        "session_id": "session-a",
        "request_id": "hr-1",
        "source_event_sequence": 12,
        "status": "requested",
        "channel": "in_app",
        "summary": "Need dataset choice",
        "metadata": {"phase_id": "phase-1"},
        "privacy_class": "unknown",
        "redaction_status": "none",
        "created_at": "2026-01-02T03:04:05+00:00",
        "updated_at": "2026-01-02T03:04:05+00:00",
    }


def _valid_human_request_resolved_payload() -> dict:
    return {
        "session_id": "session-a",
        "request_id": "hr-1",
        "source_event_sequence": 13,
        "status": "answered",
        "channel": "in_app",
        "summary": "Need dataset choice",
        "metadata": {"answer_ref": "message-2"},
        "privacy_class": "unknown",
        "redaction_status": "partial",
        "created_at": "2026-01-02T03:04:05+00:00",
        "updated_at": "2026-01-02T03:04:06+00:00",
        "resolved_at": "2026-01-02T03:04:06+00:00",
        "resolution_summary": "Answered in chat",
    }


@pytest.mark.parametrize(
    ("event_type", "payload_factory"),
    [
        (HUMAN_REQUEST_REQUESTED_EVENT, _valid_human_request_requested_payload),
        (HUMAN_REQUEST_RESOLVED_EVENT, _valid_human_request_resolved_payload),
    ],
)
def test_human_request_payloads_validate(event_type, payload_factory):
    payload = payload_factory()

    event = AgentEvent(
        session_id="session-a",
        sequence=1,
        event_type=event_type,
        data=payload,
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data == payload


@pytest.mark.parametrize(
    ("event_type", "payload_factory", "path"),
    [
        (
            HUMAN_REQUEST_REQUESTED_EVENT,
            _valid_human_request_requested_payload,
            ("request_id",),
        ),
        (
            HUMAN_REQUEST_REQUESTED_EVENT,
            _valid_human_request_requested_payload,
            ("summary",),
        ),
        (
            HUMAN_REQUEST_RESOLVED_EVENT,
            _valid_human_request_resolved_payload,
            ("session_id",),
        ),
    ],
)
def test_human_request_payloads_reject_empty_required_text(
    event_type,
    payload_factory,
    path,
):
    payload = payload_factory()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = " "

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=1,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory", "field", "value"),
    [
        (
            HUMAN_REQUEST_REQUESTED_EVENT,
            _valid_human_request_requested_payload,
            "unexpected",
            True,
        ),
        (
            HUMAN_REQUEST_REQUESTED_EVENT,
            _valid_human_request_requested_payload,
            "status",
            "answered",
        ),
        (
            HUMAN_REQUEST_RESOLVED_EVENT,
            _valid_human_request_resolved_payload,
            "status",
            "requested",
        ),
        (
            HUMAN_REQUEST_RESOLVED_EVENT,
            _valid_human_request_resolved_payload,
            "redaction_status",
            "complete",
        ),
    ],
)
def test_human_request_payloads_reject_invalid_values(
    event_type,
    payload_factory,
    field,
    value,
):
    payload = payload_factory()
    payload[field] = value

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=1,
            event_type=event_type,
            data=payload,
        )


def _valid_experiment_run_recorded_payload() -> dict:
    return {
        "session_id": " session-a ",
        "run_id": "run-1",
        "hypothesis": "Train baseline with frozen encoder",
        "status": "completed",
        "source_event_sequence": 7,
        "phase_id": "train",
        "dataset_snapshot_refs": [
            {
                "snapshot_id": "dataset-1",
                "source": "dataset_registry",
                "name": "training-set",
                "digest": "sha256:data",
            }
        ],
        "code_snapshot_refs": [
            {
                "snapshot_id": "code-1",
                "source": "git",
                "git_commit": "abcdef123456",
                "git_ref": "main",
            }
        ],
        "config": {"learning_rate": 0.001, "epochs": 3},
        "seed": 1234,
        "runtime": {
            "provider": "local",
            "started_at": "2026-04-29T10:00:00Z",
            "ended_at": "2026-04-29T10:15:00Z",
            "duration_seconds": 900.0,
            "hardware": {"accelerator": "cpu"},
        },
        "metrics": [
            {
                "name": "accuracy",
                "value": 0.91,
                "source": "tool",
                "step": 3,
                "unit": "ratio",
            }
        ],
        "log_refs": [
            {
                "log_id": "log-1",
                "source": "stdout",
                "label": "training log",
            }
        ],
        "artifact_refs": [
            {
                "artifact_id": "artifact-1",
                "type": "model_checkpoint",
                "source": "local_path",
                "uri": "file:///tmp/model.pt",
            }
        ],
        "verifier_refs": [
            {
                "verifier_id": "verifier-1",
                "type": "metric",
                "status": "passed",
                "source": "flow_template",
            }
        ],
        "external_tracking_refs": [
            {
                "tracking_id": "tracking-1",
                "source": "external_tracking",
                "provider": "tracking-provider",
                "uri": "https://tracking.example/runs/tracking-1",
            }
        ],
        "created_at": "2026-04-29T10:16:00Z",
    }


def _valid_dataset_snapshot_recorded_payload() -> dict:
    return {
        "session_id": " session-a ",
        "snapshot_id": " dataset-1 ",
        "source_event_sequence": 6,
        "source": "dataset_registry",
        "dataset_id": " dataset-main ",
        "name": " Training Set ",
        "path": " /tmp/data ",
        "uri": " file:///tmp/data ",
        "split": " train ",
        "revision": " v1 ",
        "schema": {"columns": [{"name": "text", "type": "string"}]},
        "sample_count": 42,
        "library_fingerprint": " datasets:4.4.1 ",
        "manifest_hash": " sha256:manifest ",
        "license": " mit ",
        "lineage_refs": [{"event_id": "event-1"}],
        "diff_refs": [{"snapshot_id": "dataset-0"}],
        "privacy_class": "private",
        "redaction_status": "partial",
        "created_at": " 2026-04-29T10:01:00Z ",
    }


def _valid_code_snapshot_recorded_payload() -> dict:
    return {
        "session_id": " session-a ",
        "snapshot_id": " code-1 ",
        "source_event_sequence": 7,
        "source": "git",
        "repo": " example/repo ",
        "path": " /tmp/repo ",
        "uri": " https://example.test/repo.git ",
        "git_commit": " abcdef123456 ",
        "git_ref": " main ",
        "diff_hash": " sha256:diff ",
        "changed_files": [" agent/core/events.py ", " backend/models.py "],
        "generated_artifact_refs": [{"artifact_id": "artifact-1"}],
        "manifest_hash": " sha256:manifest ",
        "digest": " sha256:digest ",
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": " 2026-04-29T10:02:00Z ",
    }


def _valid_active_job_recorded_payload() -> dict:
    return {
        "session_id": " session-a ",
        "job_id": " active-job-1 ",
        "source_event_sequence": 8,
        "tool_call_id": " tc-1 ",
        "tool": " hf_jobs ",
        "provider": "huggingface_jobs",
        "status": "running",
        "url": " https://example.test/jobs/1 ",
        "label": " Training Job ",
        "metadata": {"queue": "cpu"},
        "redaction_status": "partial",
        "started_at": " 2026-04-29T10:03:00Z ",
        "updated_at": " 2026-04-29T10:04:00Z ",
        "completed_at": None,
    }


def _valid_artifact_ref_recorded_payload() -> dict:
    return {
        "session_id": " session-a ",
        "artifact_id": " artifact-1 ",
        "source_event_sequence": 9,
        "type": " model_checkpoint ",
        "source": "job",
        "source_tool_call_id": " tc-1 ",
        "source_job_id": " active-job-1 ",
        "path": " /tmp/model.pt ",
        "uri": " file:///tmp/model.pt ",
        "digest": " sha256:model ",
        "label": " Best checkpoint ",
        "metadata": {"epoch": 3},
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": " 2026-04-29T10:05:00Z ",
    }


def _valid_metric_recorded_payload() -> dict:
    return {
        "session_id": " session-a ",
        "metric_id": " metric-1 ",
        "source_event_sequence": 10,
        "name": " accuracy ",
        "value": 0.91,
        "source": "tool",
        "step": 3,
        "unit": " ratio ",
        "recorded_at": " 2026-04-29T10:06:00Z ",
    }


def _valid_log_ref_recorded_payload() -> dict:
    return {
        "session_id": " session-a ",
        "log_id": " log-1 ",
        "source_event_sequence": 11,
        "source": "stdout",
        "uri": " file:///tmp/train.log ",
        "label": " Training log ",
    }


def _valid_evidence_item_recorded_payload() -> dict:
    return {
        "session_id": " session-a ",
        "evidence_id": " evidence-1 ",
        "source_event_sequence": 12,
        "kind": "metric",
        "source": "metric",
        "title": " Validation accuracy ",
        "summary": " Accuracy improved over baseline ",
        "metric_id": " metric-1 ",
        "metadata": {"split": "validation"},
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": " 2026-04-29T10:07:00Z ",
    }


def _valid_evidence_claim_link_recorded_payload() -> dict:
    return {
        "session_id": " session-a ",
        "link_id": " evidence-link-1 ",
        "claim_id": " claim-1 ",
        "evidence_id": " evidence-1 ",
        "source_event_sequence": 13,
        "relation": "supports",
        "strength": "strong",
        "rationale": " Metric exceeds baseline. ",
        "metadata": {"reviewed_by": "synthetic-fixture"},
        "created_at": " 2026-04-29T10:08:00Z ",
    }


def _valid_verifier_completed_payload() -> dict:
    return {
        "session_id": " session-a ",
        "verdict_id": " verdict-1 ",
        "verifier_id": " final-claims-have-evidence ",
        "source_event_sequence": 14,
        "verdict": "passed",
        "scope": " final_answer ",
        "final_answer_ref": " final-answer-1 ",
        "phase_id": " phase-report ",
        "run_id": " run-1 ",
        "evidence_ids": [" evidence-1 "],
        "claim_ids": [" claim-1 "],
        "summary": " Claims have support. ",
        "rationale": " Evidence supports the final claim. ",
        "checks": [
            {
                "check_id": " check-1 ",
                "name": " Claim coverage ",
                "status": "passed",
                "summary": " Claim is linked to evidence. ",
                "evidence_ids": [" evidence-1 "],
                "metadata": {"claim_id": "claim-1"},
            }
        ],
        "metadata": {"source": "synthetic-fixture"},
        "redaction_status": "none",
        "created_at": " 2026-04-29T10:09:00Z ",
    }


def test_dataset_snapshot_recorded_payload_validates_and_normalizes():
    event = AgentEvent(
        session_id="session-a",
        sequence=9,
        event_type="dataset_snapshot.recorded",
        data=_valid_dataset_snapshot_recorded_payload(),
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data["session_id"] == "session-a"
    assert event.data["snapshot_id"] == "dataset-1"
    assert event.data["dataset_id"] == "dataset-main"
    assert event.data["name"] == "Training Set"
    assert event.data["path"] == "/tmp/data"
    assert event.data["schema"] == {"columns": [{"name": "text", "type": "string"}]}
    assert event.data["created_at"] == "2026-04-29T10:01:00Z"


def test_code_snapshot_recorded_payload_validates_and_normalizes():
    event = AgentEvent(
        session_id="session-a",
        sequence=10,
        event_type="code_snapshot.recorded",
        data=_valid_code_snapshot_recorded_payload(),
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data["session_id"] == "session-a"
    assert event.data["snapshot_id"] == "code-1"
    assert event.data["repo"] == "example/repo"
    assert event.data["path"] == "/tmp/repo"
    assert event.data["changed_files"] == [
        "agent/core/events.py",
        "backend/models.py",
    ]


@pytest.mark.parametrize(
    ("event_type", "payload_factory"),
    [
        ("dataset_snapshot.recorded", _valid_dataset_snapshot_recorded_payload),
        ("code_snapshot.recorded", _valid_code_snapshot_recorded_payload),
    ],
)
def test_snapshot_recorded_payloads_reject_unknown_top_level_fields(
    event_type,
    payload_factory,
):
    payload = payload_factory()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=11,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory", "path"),
    [
        (
            "dataset_snapshot.recorded",
            _valid_dataset_snapshot_recorded_payload,
            ("session_id",),
        ),
        (
            "dataset_snapshot.recorded",
            _valid_dataset_snapshot_recorded_payload,
            ("snapshot_id",),
        ),
        (
            "dataset_snapshot.recorded",
            _valid_dataset_snapshot_recorded_payload,
            ("name",),
        ),
        (
            "code_snapshot.recorded",
            _valid_code_snapshot_recorded_payload,
            ("session_id",),
        ),
        (
            "code_snapshot.recorded",
            _valid_code_snapshot_recorded_payload,
            ("snapshot_id",),
        ),
        (
            "code_snapshot.recorded",
            _valid_code_snapshot_recorded_payload,
            ("changed_files", 0),
        ),
    ],
)
def test_snapshot_recorded_payloads_reject_empty_required_ids_and_text(
    event_type,
    payload_factory,
    path,
):
    payload = payload_factory()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = ""

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=11,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory", "field", "value"),
    [
        (
            "dataset_snapshot.recorded",
            _valid_dataset_snapshot_recorded_payload,
            "source",
            "ad_hoc",
        ),
        (
            "dataset_snapshot.recorded",
            _valid_dataset_snapshot_recorded_payload,
            "privacy_class",
            "internal",
        ),
        (
            "dataset_snapshot.recorded",
            _valid_dataset_snapshot_recorded_payload,
            "redaction_status",
            "complete",
        ),
        (
            "code_snapshot.recorded",
            _valid_code_snapshot_recorded_payload,
            "source",
            "working_tree",
        ),
        (
            "code_snapshot.recorded",
            _valid_code_snapshot_recorded_payload,
            "privacy_class",
            "internal",
        ),
        (
            "code_snapshot.recorded",
            _valid_code_snapshot_recorded_payload,
            "redaction_status",
            "complete",
        ),
    ],
)
def test_snapshot_recorded_payloads_reject_invalid_literals(
    event_type,
    payload_factory,
    field,
    value,
):
    payload = payload_factory()
    payload[field] = value

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=11,
            event_type=event_type,
            data=payload,
        )


def test_active_job_recorded_payload_validates_and_normalizes():
    event = AgentEvent(
        session_id="session-a",
        sequence=12,
        event_type="active_job.recorded",
        data=_valid_active_job_recorded_payload(),
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data["session_id"] == "session-a"
    assert event.data["job_id"] == "active-job-1"
    assert event.data["tool_call_id"] == "tc-1"
    assert event.data["tool"] == "hf_jobs"
    assert event.data["url"] == "https://example.test/jobs/1"
    assert event.data["label"] == "Training Job"
    assert event.data["started_at"] == "2026-04-29T10:03:00Z"
    assert "completed_at" not in event.data


def test_artifact_ref_recorded_payload_validates_and_normalizes():
    event = AgentEvent(
        session_id="session-a",
        sequence=13,
        event_type="artifact_ref.recorded",
        data=_valid_artifact_ref_recorded_payload(),
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data["session_id"] == "session-a"
    assert event.data["artifact_id"] == "artifact-1"
    assert event.data["type"] == "model_checkpoint"
    assert event.data["source_tool_call_id"] == "tc-1"
    assert event.data["source_job_id"] == "active-job-1"
    assert event.data["path"] == "/tmp/model.pt"
    assert event.data["label"] == "Best checkpoint"


def test_metric_recorded_payload_validates_and_normalizes():
    event = AgentEvent(
        session_id="session-a",
        sequence=14,
        event_type="metric.recorded",
        data=_valid_metric_recorded_payload(),
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data["session_id"] == "session-a"
    assert event.data["metric_id"] == "metric-1"
    assert event.data["name"] == "accuracy"
    assert event.data["unit"] == "ratio"
    assert event.data["recorded_at"] == "2026-04-29T10:06:00Z"


def test_log_ref_recorded_payload_validates_and_normalizes():
    event = AgentEvent(
        session_id="session-a",
        sequence=15,
        event_type="log_ref.recorded",
        data=_valid_log_ref_recorded_payload(),
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data["session_id"] == "session-a"
    assert event.data["log_id"] == "log-1"
    assert event.data["uri"] == "file:///tmp/train.log"
    assert event.data["label"] == "Training log"


def test_evidence_item_recorded_payload_validates_and_normalizes():
    event = AgentEvent(
        session_id="session-a",
        sequence=16,
        event_type="evidence_item.recorded",
        data=_valid_evidence_item_recorded_payload(),
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data["session_id"] == "session-a"
    assert event.data["evidence_id"] == "evidence-1"
    assert event.data["title"] == "Validation accuracy"
    assert event.data["summary"] == "Accuracy improved over baseline"
    assert event.data["metric_id"] == "metric-1"


def test_evidence_claim_link_recorded_payload_validates_and_normalizes():
    event = AgentEvent(
        session_id="session-a",
        sequence=17,
        event_type="evidence_claim_link.recorded",
        data=_valid_evidence_claim_link_recorded_payload(),
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data["session_id"] == "session-a"
    assert event.data["link_id"] == "evidence-link-1"
    assert event.data["claim_id"] == "claim-1"
    assert event.data["evidence_id"] == "evidence-1"
    assert event.data["rationale"] == "Metric exceeds baseline."


def test_verifier_completed_payload_validates_and_normalizes():
    event = AgentEvent(
        session_id="session-a",
        sequence=18,
        event_type="verifier.completed",
        data=_valid_verifier_completed_payload(),
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data["session_id"] == "session-a"
    assert event.data["verdict_id"] == "verdict-1"
    assert event.data["verifier_id"] == "final-claims-have-evidence"
    assert event.data["verdict"] == "passed"
    assert event.data["scope"] == "final_answer"
    assert event.data["evidence_ids"] == ["evidence-1"]
    assert event.data["claim_ids"] == ["claim-1"]
    assert event.data["checks"][0]["name"] == "Claim coverage"
    assert event.data["checks"][0]["evidence_ids"] == ["evidence-1"]


def test_verifier_completed_payload_rejects_unknown_fields():
    payload = _valid_verifier_completed_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=18,
            event_type="verifier.completed",
            data=payload,
        )

    payload = _valid_verifier_completed_payload()
    payload["checks"][0]["unexpected"] = True

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=18,
            event_type="verifier.completed",
            data=payload,
        )


@pytest.mark.parametrize(
    "path",
    [
        ("session_id",),
        ("verdict_id",),
        ("verifier_id",),
        ("scope",),
        ("evidence_ids", 0),
        ("checks", 0, "name"),
        ("checks", 0, "evidence_ids", 0),
    ],
)
def test_verifier_completed_payload_rejects_empty_required_ids_and_text(path):
    payload = _valid_verifier_completed_payload()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = ""

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=18,
            event_type="verifier.completed",
            data=payload,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_event_sequence", 0),
        ("verdict", "blocked"),
        ("redaction_status", "complete"),
    ],
)
def test_verifier_completed_payload_rejects_invalid_values(field, value):
    payload = _valid_verifier_completed_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=18,
            event_type="verifier.completed",
            data=payload,
        )


def test_verifier_completed_payload_rejects_invalid_check_status():
    payload = _valid_verifier_completed_payload()
    payload["checks"][0]["status"] = "blocked"

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=18,
            event_type="verifier.completed",
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory"),
    [
        ("evidence_item.recorded", _valid_evidence_item_recorded_payload),
        (
            "evidence_claim_link.recorded",
            _valid_evidence_claim_link_recorded_payload,
        ),
    ],
)
def test_evidence_payloads_reject_unknown_top_level_fields(
    event_type,
    payload_factory,
):
    payload = payload_factory()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=18,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory", "path"),
    [
        (
            "evidence_item.recorded",
            _valid_evidence_item_recorded_payload,
            ("session_id",),
        ),
        (
            "evidence_item.recorded",
            _valid_evidence_item_recorded_payload,
            ("evidence_id",),
        ),
        ("evidence_item.recorded", _valid_evidence_item_recorded_payload, ("title",)),
        (
            "evidence_claim_link.recorded",
            _valid_evidence_claim_link_recorded_payload,
            ("link_id",),
        ),
        (
            "evidence_claim_link.recorded",
            _valid_evidence_claim_link_recorded_payload,
            ("claim_id",),
        ),
        (
            "evidence_claim_link.recorded",
            _valid_evidence_claim_link_recorded_payload,
            ("evidence_id",),
        ),
    ],
)
def test_evidence_payloads_reject_empty_required_ids_and_text(
    event_type,
    payload_factory,
    path,
):
    payload = payload_factory()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = ""

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=18,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory", "field", "value"),
    [
        (
            "evidence_item.recorded",
            _valid_evidence_item_recorded_payload,
            "kind",
            "score",
        ),
        (
            "evidence_item.recorded",
            _valid_evidence_item_recorded_payload,
            "source_event_sequence",
            0,
        ),
        (
            "evidence_claim_link.recorded",
            _valid_evidence_claim_link_recorded_payload,
            "relation",
            "proves",
        ),
        (
            "evidence_claim_link.recorded",
            _valid_evidence_claim_link_recorded_payload,
            "strength",
            "absolute",
        ),
    ],
)
def test_evidence_payloads_reject_invalid_values(
    event_type,
    payload_factory,
    field,
    value,
):
    payload = payload_factory()
    payload[field] = value

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=18,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory"),
    [
        ("metric.recorded", _valid_metric_recorded_payload),
        ("log_ref.recorded", _valid_log_ref_recorded_payload),
    ],
)
def test_standalone_metric_log_payloads_reject_unknown_top_level_fields(
    event_type,
    payload_factory,
):
    payload = payload_factory()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=16,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory", "path"),
    [
        ("metric.recorded", _valid_metric_recorded_payload, ("session_id",)),
        ("metric.recorded", _valid_metric_recorded_payload, ("metric_id",)),
        ("metric.recorded", _valid_metric_recorded_payload, ("name",)),
        ("metric.recorded", _valid_metric_recorded_payload, ("unit",)),
        ("log_ref.recorded", _valid_log_ref_recorded_payload, ("session_id",)),
        ("log_ref.recorded", _valid_log_ref_recorded_payload, ("log_id",)),
        ("log_ref.recorded", _valid_log_ref_recorded_payload, ("label",)),
    ],
)
def test_standalone_metric_log_payloads_reject_empty_required_ids_and_text(
    event_type,
    payload_factory,
    path,
):
    payload = payload_factory()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = ""

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=16,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory", "field", "value"),
    [
        ("metric.recorded", _valid_metric_recorded_payload, "source", "scan"),
        ("metric.recorded", _valid_metric_recorded_payload, "step", -1),
        ("log_ref.recorded", _valid_log_ref_recorded_payload, "source", "scan"),
        (
            "log_ref.recorded",
            _valid_log_ref_recorded_payload,
            "source_event_sequence",
            0,
        ),
    ],
)
def test_standalone_metric_log_payloads_reject_invalid_values(
    event_type,
    payload_factory,
    field,
    value,
):
    payload = payload_factory()
    payload[field] = value

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=16,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory"),
    [
        ("active_job.recorded", _valid_active_job_recorded_payload),
        ("artifact_ref.recorded", _valid_artifact_ref_recorded_payload),
    ],
)
def test_job_artifact_payloads_reject_unknown_top_level_fields(
    event_type,
    payload_factory,
):
    payload = payload_factory()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=14,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory", "path"),
    [
        ("active_job.recorded", _valid_active_job_recorded_payload, ("session_id",)),
        ("active_job.recorded", _valid_active_job_recorded_payload, ("job_id",)),
        ("active_job.recorded", _valid_active_job_recorded_payload, ("label",)),
        (
            "artifact_ref.recorded",
            _valid_artifact_ref_recorded_payload,
            ("session_id",),
        ),
        (
            "artifact_ref.recorded",
            _valid_artifact_ref_recorded_payload,
            ("artifact_id",),
        ),
        ("artifact_ref.recorded", _valid_artifact_ref_recorded_payload, ("type",)),
    ],
)
def test_job_artifact_payloads_reject_empty_required_ids_and_text(
    event_type,
    payload_factory,
    path,
):
    payload = payload_factory()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = ""

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=14,
            event_type=event_type,
            data=payload,
        )


@pytest.mark.parametrize(
    ("event_type", "payload_factory", "field", "value"),
    [
        (
            "active_job.recorded",
            _valid_active_job_recorded_payload,
            "provider",
            "github_actions",
        ),
        (
            "active_job.recorded",
            _valid_active_job_recorded_payload,
            "status",
            "paused",
        ),
        (
            "active_job.recorded",
            _valid_active_job_recorded_payload,
            "redaction_status",
            "complete",
        ),
        (
            "artifact_ref.recorded",
            _valid_artifact_ref_recorded_payload,
            "source",
            "scan",
        ),
        (
            "artifact_ref.recorded",
            _valid_artifact_ref_recorded_payload,
            "privacy_class",
            "internal",
        ),
        (
            "artifact_ref.recorded",
            _valid_artifact_ref_recorded_payload,
            "redaction_status",
            "complete",
        ),
    ],
)
def test_job_artifact_payloads_reject_invalid_literals(
    event_type,
    payload_factory,
    field,
    value,
):
    payload = payload_factory()
    payload[field] = value

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=14,
            event_type=event_type,
            data=payload,
        )


def test_experiment_run_recorded_payload_validates_and_normalizes():
    event = AgentEvent(
        session_id="session-a",
        sequence=8,
        event_type="experiment.run_recorded",
        data=_valid_experiment_run_recorded_payload(),
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data["session_id"] == "session-a"
    assert event.data["run_id"] == "run-1"
    assert event.data["status"] == "completed"
    assert event.data["dataset_snapshot_refs"][0]["source"] == "dataset_registry"
    assert event.data["runtime"]["provider"] == "local"
    assert event.data["metrics"][0]["name"] == "accuracy"


def test_experiment_run_recorded_rejects_unknown_top_level_fields():
    payload = _valid_experiment_run_recorded_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=8,
            event_type="experiment.run_recorded",
            data=payload,
        )


def test_experiment_run_recorded_rejects_unknown_nested_fields():
    payload = _valid_experiment_run_recorded_payload()
    payload["metrics"][0]["unexpected"] = True

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=8,
            event_type="experiment.run_recorded",
            data=payload,
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("session_id",), ""),
        (("run_id",), ""),
        (("hypothesis",), ""),
        (("dataset_snapshot_refs", 0, "snapshot_id"), ""),
        (("metrics", 0, "name"), ""),
    ],
)
def test_experiment_run_recorded_rejects_empty_required_ids_and_text(path, value):
    payload = _valid_experiment_run_recorded_payload()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=8,
            event_type="experiment.run_recorded",
            data=payload,
        )


def test_experiment_run_recorded_rejects_unmodeled_source_literals():
    payload = _valid_experiment_run_recorded_payload()
    payload["dataset_snapshot_refs"][0]["source"] = "ad_hoc"

    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=8,
            event_type="experiment.run_recorded",
            data=payload,
        )


def test_known_event_payloads_validate_required_fields():
    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=1,
            event_type="assistant_message",
            data={},
        )


def test_unknown_event_types_remain_compatible_for_migration():
    event = AgentEvent(
        session_id="session-a",
        sequence=1,
        event_type="experimental_event",
        data={"anything": True},
    )

    assert event.to_legacy_sse() == {
        "event_type": "experimental_event",
        "data": {"anything": True},
    }
