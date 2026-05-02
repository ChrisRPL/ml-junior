from __future__ import annotations

import httpx
import pytest

from agent.core.backend_index_client import (
    BackendIndexClient,
    BackendIndexClientError,
    BackendIndexConfig,
    BackendIndexConfigError,
    BackendIndexNotFoundError,
    render_backend_index_command,
)
from backend.models import ArtifactRefRecord, ExperimentRunRecord


def test_backend_index_config_is_explicit_opt_in() -> None:
    assert BackendIndexConfig.from_env({}) is None

    with pytest.raises(BackendIndexConfigError, match="MLJ_BACKEND_BASE_URL"):
        BackendIndexConfig.from_env({"MLJ_BACKEND_BASE_URL": "http://backend"})

    config = BackendIndexConfig.from_env(
        {
            "MLJ_BACKEND_BASE_URL": "http://backend",
            "MLJ_BACKEND_SESSION_ID": "session-a",
            "MLJ_BACKEND_BEARER_TOKEN": "hf_backendtoken123456789",
            "MLJ_BACKEND_TIMEOUT_SECONDS": "1.5",
        }
    )

    assert config == BackendIndexConfig(
        base_url="http://backend",
        session_id="session-a",
        bearer_token="hf_backendtoken123456789",
        timeout_seconds=1.5,
    )


def test_backend_index_config_rejects_bad_timeout() -> None:
    with pytest.raises(BackendIndexConfigError, match="greater than zero"):
        BackendIndexConfig.from_env(
            {
                "MLJ_BACKEND_BASE_URL": "http://backend",
                "MLJ_BACKEND_SESSION_ID": "session-a",
                "MLJ_BACKEND_TIMEOUT_SECONDS": "0",
            }
        )


async def test_render_backend_index_commands_fetch_read_only_records() -> None:
    secret = "hf_backendsecret123456789"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == f"Bearer {secret}"
        if request.url.path == "/api/session/session-a/runs":
            return httpx.Response(200, json=[_run_json(secret)])
        if request.url.path == "/api/session/session-a/runs/run-1":
            return httpx.Response(200, json=_run_json(secret))
        if request.url.path == "/api/session/session-a/artifacts":
            return httpx.Response(200, json=[_artifact_json(secret)])
        raise AssertionError(f"Unexpected path: {request.url.path}")

    config = BackendIndexConfig(
        base_url="http://backend.example",
        session_id="session-a",
        bearer_token=secret,
    )
    transport = httpx.MockTransport(handler)
    client = BackendIndexClient(config, transport=transport)

    runs = await render_backend_index_command("/runs", config=config, client=client)
    metrics = await render_backend_index_command(
        "/metrics",
        "accuracy",
        config=config,
        client=client,
    )
    detail = await render_backend_index_command(
        "/run show",
        "run-1",
        config=config,
        client=client,
    )
    artifacts = await render_backend_index_command(
        "/artifacts",
        "checkpoint",
        config=config,
        client=client,
    )

    assert "run-1  completed  phase:train" in runs
    assert "backend read Authorization: Bearer [REDACTED]" in runs
    assert "run-1  accuracy=0.91  source:tool" in metrics
    assert "tracking-run-1" in detail
    assert "token=[REDACTED]" in detail
    assert "artifact-1  model_checkpoint" in artifacts
    assert secret not in "\n".join([runs, metrics, detail, artifacts])
    assert [request.url.path for request in requests] == [
        "/api/session/session-a/runs",
        "/api/session/session-a/runs",
        "/api/session/session-a/runs/run-1",
        "/api/session/session-a/artifacts",
    ]


async def test_backend_index_client_maps_status_errors() -> None:
    secret = "hf_missingbackendsecret123456789"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/runs/missing") or request.url.path.endswith(
            f"/runs/{secret}"
        ):
            return httpx.Response(404, json={"detail": "missing"})
        return httpx.Response(403, json={"detail": "denied"})

    config = BackendIndexConfig(base_url="http://backend.example", session_id="s")
    client = BackendIndexClient(config, transport=httpx.MockTransport(handler))

    with pytest.raises(BackendIndexNotFoundError):
        await client.get_run("missing")
    not_found = await render_backend_index_command(
        "/run show",
        secret,
        config=config,
        client=client,
    )
    assert not_found == "Experiment run\n  run not found: [REDACTED]"
    with pytest.raises(BackendIndexClientError, match="not authorized"):
        await client.list_runs()


async def test_backend_index_client_maps_timeout() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow backend")

    config = BackendIndexConfig(base_url="http://backend.example", session_id="s")
    client = BackendIndexClient(config, transport=httpx.MockTransport(handler))

    with pytest.raises(BackendIndexClientError, match="timed out"):
        await client.list_artifacts()


def _run_json(secret: str) -> dict[str, object]:
    return ExperimentRunRecord.model_validate(
        {
            "session_id": "session-a",
            "run_id": "run-1",
            "hypothesis": f"backend read Authorization: Bearer {secret}",
            "status": "completed",
            "source_event_sequence": 1,
            "phase_id": "train",
            "runtime": {"provider": "local"},
            "metrics": [{"name": "accuracy", "value": 0.91, "source": "tool"}],
            "external_tracking_refs": [
                {
                    "tracking_id": "tracking-run-1",
                    "source": "external_tracking",
                    "provider": "tracking-provider",
                    "uri": f"https://tracking.example/run-1?token={secret}",
                }
            ],
            "created_at": "2026-01-02T03:04:05+00:00",
        }
    ).model_dump(mode="json", exclude_none=True)


def _artifact_json(secret: str) -> dict[str, object]:
    return ArtifactRefRecord.model_validate(
        {
            "session_id": "session-a",
            "artifact_id": "artifact-1",
            "source_event_sequence": 2,
            "type": "model_checkpoint",
            "source": "remote_uri",
            "ref_uri": "mlj://session/session-a/artifact/artifact-1",
            "uri": f"https://artifacts.example/checkpoint.pt?token={secret}",
            "label": "checkpoint",
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": "2026-01-02T03:04:06+00:00",
        }
    ).model_dump(mode="json", exclude_none=True)
