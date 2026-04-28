from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.flow_templates import (
    FlowTemplateError,
    load_flow_template,
    parse_flow_template,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "flow_templates"
BUILTIN_DIR = Path(__file__).resolve().parent.parent.parent / "backend" / "builtin_flow_templates"
EXPECTED_BUILTIN_IDS = [
    "build-evaluation-harness",
    "dataset-audit",
    "fine-tune-model",
    "implement-architecture",
    "literature-overview",
    "reproduce-paper",
]


def test_valid_template_fixture_parses() -> None:
    template = load_flow_template(FIXTURE_DIR / "valid_v1.json")

    assert template.id == "mnist-baseline"
    assert template.name == "MNIST Baseline"
    assert template.version == "v1"
    assert template.inputs[0].model_dump() == {
        "id": "metric",
        "type": "string",
        "required": True,
        "default": "accuracy",
        "description": "Primary validation metric.",
    }
    assert template.budgets.model_dump() == {
        "max_gpu_hours": 4.0,
        "max_runs": 2,
        "max_wall_clock_hours": 8.0,
        "max_llm_usd": 1.25,
    }
    assert template.permissions[0].model_dump() == {
        "id": "hf-token",
        "risk": "low",
        "action": "read",
        "target": "huggingface-profile",
        "description": "Read the configured Hugging Face identity.",
    }
    assert template.approval_points[0].model_dump() == {
        "id": "gpu-run",
        "risk": "medium",
        "action": "launch",
        "target": "huggingface-job",
        "description": "Start a remote GPU job.",
    }
    assert template.required_outputs[0].id == "metrics-json"
    assert template.artifacts[0].id == "model-card"
    assert template.verifiers[0].model_dump() == {
        "id": "accuracy-threshold",
        "type": "metric",
        "description": "Accuracy is present and above the configured threshold.",
        "required": True,
    }
    assert template.phases[0].model_dump() == {
        "id": "train",
        "name": "Train",
        "objective": "Train a baseline model and capture metrics.",
        "status": "pending",
        "order": 1,
        "required_outputs": ["metrics-json"],
        "approval_points": ["gpu-run"],
        "verifiers": ["accuracy-threshold"],
    }


def test_parser_accepts_dicts() -> None:
    raw = json.loads((FIXTURE_DIR / "valid_v1.json").read_text())

    template = parse_flow_template(raw)

    assert template.id == "mnist-baseline"
    assert template.phases[0].approval_points == ["gpu-run"]


def test_builtin_templates_have_stable_ids_and_validate() -> None:
    templates = [
        load_flow_template(path)
        for path in sorted(BUILTIN_DIR.glob("*.json"))
    ]

    assert [template.id for template in templates] == EXPECTED_BUILTIN_IDS
    assert [f"{template.id}.json" for template in templates] == [
        path.name for path in sorted(BUILTIN_DIR.glob("*.json"))
    ]

    for template in templates:
        assert template.version == "v1"
        assert template.inputs
        assert any(input_.required for input_ in template.inputs)
        assert template.permissions
        assert template.approval_points
        assert template.phases
        assert template.required_outputs
        assert template.artifacts
        assert template.verifiers
        assert any(
            value is not None
            for value in template.budgets.model_dump().values()
        )
        assert any(phase.approval_points for phase in template.phases)
        assert any(phase.verifiers for phase in template.phases)


def test_builtin_template_families_cover_required_gate_paths() -> None:
    loaded_templates = [
        load_flow_template(path)
        for path in sorted(BUILTIN_DIR.glob("*.json"))
    ]
    templates = {template.id: template for template in loaded_templates}

    assert set(templates) == set(EXPECTED_BUILTIN_IDS)

    for template_id, template in templates.items():
        approval_refs = {
            approval_id
            for phase in template.phases
            for approval_id in phase.approval_points
        }
        verifier_refs = {
            verifier_id
            for phase in template.phases
            for verifier_id in phase.verifiers
        }
        budget_values = template.budgets.model_dump()

        assert approval_refs, template_id
        assert verifier_refs, template_id
        assert any(value is not None for value in budget_values.values()), template_id

    assert "launch-reproduction-job" in {
        approval_id
        for phase in templates["reproduce-paper"].phases
        for approval_id in phase.approval_points
    }
    assert "run-smoke-training" in {
        approval_id
        for phase in templates["implement-architecture"].phases
        for approval_id in phase.approval_points
    }
    assert "launch-training" in {
        approval_id
        for phase in templates["fine-tune-model"].phases
        for approval_id in phase.approval_points
    }
    assert "review-sensitive-samples" in {
        approval_id
        for phase in templates["dataset-audit"].phases
        for approval_id in phase.approval_points
    }
    assert "approve-source-scope" in {
        approval_id
        for phase in templates["literature-overview"].phases
        for approval_id in phase.approval_points
    }
    assert "run-eval-suite" in {
        approval_id
        for phase in templates["build-evaluation-harness"].phases
        for approval_id in phase.approval_points
    }


@pytest.mark.parametrize(
    ("fixture_name", "expected_message"),
    [
        ("missing_version.json", "version is required"),
        ("unsupported_version.json", "Unsupported schema version 'v2'"),
        ("duplicate_input_ids.json", "duplicate input id: paper_url"),
        ("duplicate_phase_ids.json", "duplicate phase id: train"),
        (
            "unknown_approval_reference.json",
            "unknown phase train approval_points reference: gpu-run",
        ),
        ("empty_phases.json", "phases must contain at least one phase"),
    ],
)
def test_invalid_fixtures_fail_with_useful_errors(
    fixture_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(FlowTemplateError, match=expected_message):
        load_flow_template(FIXTURE_DIR / fixture_name)
