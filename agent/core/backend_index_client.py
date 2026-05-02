"""Opt-in read-only backend index reads for CLI commands."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from agent.core.redaction import redact_string
from agent.core.index_commands import (
    render_artifact_records,
    render_metric_records,
    render_run_record_detail,
    render_run_records,
)
from backend.models import ArtifactRefRecord, ExperimentRunRecord


DEFAULT_BACKEND_INDEX_TIMEOUT_SECONDS = 3.0


class BackendIndexConfigError(ValueError):
    """Raised when backend index opt-in configuration is incomplete."""


class BackendIndexClientError(RuntimeError):
    """Raised when a read-only backend index request fails."""


class BackendIndexNotFoundError(BackendIndexClientError):
    """Raised when the backend reports a requested index record is missing."""


@dataclass(frozen=True, slots=True)
class BackendIndexConfig:
    """Explicit opt-in settings for backend-backed CLI index reads."""

    base_url: str
    session_id: str
    bearer_token: str | None = None
    timeout_seconds: float = DEFAULT_BACKEND_INDEX_TIMEOUT_SECONDS

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "BackendIndexConfig | None":
        """Return backend read config only when explicitly enabled by env."""

        if env is None:
            env = os.environ
        base_url = (env.get("MLJ_BACKEND_BASE_URL") or "").strip()
        session_id = (env.get("MLJ_BACKEND_SESSION_ID") or "").strip()
        if not base_url and not session_id:
            return None
        if not base_url or not session_id:
            raise BackendIndexConfigError(
                "Backend index mode requires MLJ_BACKEND_BASE_URL and "
                "MLJ_BACKEND_SESSION_ID."
            )

        timeout_raw = (env.get("MLJ_BACKEND_TIMEOUT_SECONDS") or "").strip()
        timeout_seconds = DEFAULT_BACKEND_INDEX_TIMEOUT_SECONDS
        if timeout_raw:
            try:
                timeout_seconds = float(timeout_raw)
            except ValueError as exc:
                raise BackendIndexConfigError(
                    "MLJ_BACKEND_TIMEOUT_SECONDS must be a number."
                ) from exc
            if timeout_seconds <= 0:
                raise BackendIndexConfigError(
                    "MLJ_BACKEND_TIMEOUT_SECONDS must be greater than zero."
                )

        return cls(
            base_url=base_url,
            session_id=session_id,
            bearer_token=(env.get("MLJ_BACKEND_BEARER_TOKEN") or "").strip() or None,
            timeout_seconds=timeout_seconds,
        )


class BackendIndexClient:
    """Tiny HTTP adapter for durable backend index routes."""

    def __init__(
        self,
        config: BackendIndexConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    async def list_runs(self) -> list[ExperimentRunRecord]:
        data = await self._get_json(f"{self._session_path()}/runs")
        if not isinstance(data, list):
            raise BackendIndexClientError("Backend run index returned invalid JSON.")
        return [ExperimentRunRecord.model_validate(item) for item in data]

    async def get_run(self, run_id: str) -> ExperimentRunRecord:
        data = await self._get_json(f"{self._session_path()}/runs/{_path_part(run_id)}")
        if not isinstance(data, dict):
            raise BackendIndexClientError("Backend run detail returned invalid JSON.")
        return ExperimentRunRecord.model_validate(data)

    async def list_artifacts(self) -> list[ArtifactRefRecord]:
        data = await self._get_json(f"{self._session_path()}/artifacts")
        if not isinstance(data, list):
            raise BackendIndexClientError(
                "Backend artifact index returned invalid JSON."
            )
        return [ArtifactRefRecord.model_validate(item) for item in data]

    def _session_path(self) -> str:
        return f"/api/session/{_path_part(self.config.session_id)}"

    async def _get_json(self, path: str) -> Any:
        headers = {}
        if self.config.bearer_token:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"

        try:
            async with httpx.AsyncClient(
                base_url=self.config.base_url.rstrip("/"),
                headers=headers,
                timeout=self.config.timeout_seconds,
                follow_redirects=True,
                transport=self._transport,
            ) as client:
                response = await client.get(path)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            _raise_status_error(exc)
        except httpx.TimeoutException as exc:
            raise BackendIndexClientError("Backend index read timed out.") from exc
        except httpx.RequestError as exc:
            raise BackendIndexClientError(
                f"Backend index read failed: {exc.__class__.__name__}."
            ) from exc
        except ValueError as exc:
            raise BackendIndexClientError(
                "Backend index read returned invalid JSON."
            ) from exc


async def render_backend_index_command(
    command: str,
    arguments: str = "",
    *,
    config: BackendIndexConfig,
    client: BackendIndexClient | None = None,
) -> str:
    """Render a CLI index command from read-only backend API records."""

    client = client or BackendIndexClient(config)
    if command == "/runs":
        return render_run_records(arguments, runs=await client.list_runs())
    if command == "/run show":
        run_id = arguments.strip()
        if not run_id:
            return "Experiment run\n  Usage: /run show <id>"
        try:
            return render_run_record_detail(await client.get_run(run_id))
        except BackendIndexNotFoundError:
            return f"Experiment run\n  run not found: {redact_string(run_id).value}"
    if command == "/metrics":
        return render_metric_records(arguments, runs=await client.list_runs())
    if command == "/artifacts":
        return render_artifact_records(arguments, artifacts=await client.list_artifacts())
    raise ValueError(f"Unsupported backend index command: {command}")


def _path_part(value: str) -> str:
    return quote(value, safe="")


def _raise_status_error(exc: httpx.HTTPStatusError) -> None:
    status = exc.response.status_code
    if status in {401, 403}:
        raise BackendIndexClientError(
            f"Backend index read was not authorized (HTTP {status})."
        ) from exc
    if status == 404:
        raise BackendIndexNotFoundError("Backend index record was not found.") from exc
    raise BackendIndexClientError(
        f"Backend index read failed with HTTP {status}."
    ) from exc
