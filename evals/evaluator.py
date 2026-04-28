from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from evals.schemas import GoldenTrace, VerifierVerdict, load_golden_trace, load_verifier_verdict


@dataclass(frozen=True)
class EvaluationReport:
    run_id: str
    golden_traces: int
    verifier_verdicts: int
    failures: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures


class Evaluator(Protocol):
    def prepare(self) -> None:
        """Load local fixture metadata and perform deterministic setup."""

    def evaluate(self, run_id: str) -> EvaluationReport:
        """Evaluate an offline fixture run."""

    def report(self) -> EvaluationReport:
        """Return the latest offline evaluation report."""


class OfflineFixtureEvaluator:
    """Small fixture-backed evaluator until ledger/verifier APIs exist."""

    def __init__(self, fixtures_root: Path) -> None:
        self.fixtures_root = fixtures_root
        self._golden_traces: list[GoldenTrace] = []
        self._verifier_verdicts: list[VerifierVerdict] = []
        self._report: EvaluationReport | None = None

    def prepare(self) -> None:
        trace_dir = self.fixtures_root / "golden_traces"
        verdict_dir = self.fixtures_root / "verifier_verdicts"

        self._golden_traces = [
            load_golden_trace(path)
            for path in sorted(trace_dir.glob("*.json"))
        ]
        self._verifier_verdicts = [
            load_verifier_verdict(path)
            for path in sorted(verdict_dir.glob("*.json"))
        ]

    def evaluate(self, run_id: str) -> EvaluationReport:
        if not self._golden_traces and not self._verifier_verdicts:
            self.prepare()

        failures = []
        for trace in self._golden_traces:
            if trace.mode != "offline":
                failures.append(f"{trace.name}: bootstrap evaluator only runs offline traces")

        self._report = EvaluationReport(
            run_id=run_id,
            golden_traces=len(self._golden_traces),
            verifier_verdicts=len(self._verifier_verdicts),
            failures=tuple(failures),
        )
        return self._report

    def report(self) -> EvaluationReport:
        if self._report is None:
            raise RuntimeError("evaluate(run_id) must run before report()")
        return self._report
