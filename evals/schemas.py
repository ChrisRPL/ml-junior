from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SUPPORTED_SCHEMA_VERSION = 1
TraceMode = Literal["offline", "scheduled"]
RedactionStatus = Literal["none", "partial", "redacted"]
Verdict = Literal["pass", "fail", "inconclusive"]


class LegacySSE(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class GoldenTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    session_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    redaction_status: RedactionStatus = "none"
    legacy_sse: LegacySSE | None = None

    @model_validator(mode="after")
    def legacy_sse_matches_event(self) -> GoldenTraceEvent:
        if self.legacy_sse is None:
            return self
        if self.legacy_sse.event_type != self.event_type:
            raise ValueError("legacy_sse.event_type must match event_type")
        if self.legacy_sse.data != self.data:
            raise ValueError("legacy_sse.data must match data")
        return self


class GoldenTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    name: str = Field(min_length=1)
    mode: TraceMode
    inputs: dict[str, Any] = Field(default_factory=dict)
    events: list[GoldenTraceEvent] = Field(min_length=1)
    expected: dict[str, Any] = Field(default_factory=dict)
    ignore_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_trace_contract(self) -> GoldenTrace:
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SUPPORTED_SCHEMA_VERSION}")

        for event in self.events:
            if event.schema_version != self.schema_version:
                raise ValueError("event schema_version must match trace schema_version")

        previous_by_session: dict[str, int] = {}
        for event in self.events:
            previous = previous_by_session.get(event.session_id, 0)
            if event.sequence <= previous:
                raise ValueError("events must be ordered by sequence within a session")
            previous_by_session[event.session_id] = event.sequence

        return self


class VerdictClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class VerdictEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    ref: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class VerdictCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    status: Verdict
    reason: str = Field(min_length=1)


class VerifierVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[VerdictClaim] = Field(min_length=1)
    evidence: list[VerdictEvidence] = Field(default_factory=list)
    checks: list[VerdictCheck] = Field(min_length=1)
    verdict: Verdict
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_refs_and_outcome(self) -> VerifierVerdict:
        evidence_ids = {item.id for item in self.evidence}
        claim_ids = {claim.id for claim in self.claims}

        for claim in self.claims:
            missing = set(claim.evidence_refs) - evidence_ids
            if missing:
                raise ValueError(f"claim {claim.id} references missing evidence: {sorted(missing)}")

        for check in self.checks:
            if check.claim_id not in claim_ids:
                raise ValueError(f"check {check.name} references missing claim: {check.claim_id}")

        statuses = {check.status for check in self.checks}
        if self.verdict == "pass" and statuses != {"pass"}:
            raise ValueError("pass verdict requires all checks to pass")
        if self.verdict == "fail" and "fail" not in statuses:
            raise ValueError("fail verdict requires at least one failing check")
        if self.verdict == "inconclusive" and "inconclusive" not in statuses:
            raise ValueError("inconclusive verdict requires at least one inconclusive check")

        return self


def load_golden_trace(path: Path) -> GoldenTrace:
    return GoldenTrace.model_validate(_load_json(path))


def load_verifier_verdict(path: Path) -> VerifierVerdict:
    return VerifierVerdict.model_validate(_load_json(path))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
