from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.flow_templates import get_builtin_flow_template
from backend.verifier_check_catalog import CHECK_METRIC_PARSED_FROM_OUTPUT
import routes.agent as agent_routes


EXPECTED_BUILTIN_IDS = [
    "build-evaluation-harness",
    "compare-models",
    "create-model-card",
    "dataset-audit",
    "dataset-card-review",
    "debug-failed-training-run",
    "distill-model",
    "fine-tune-model",
    "hyperparameter-sweep",
    "implement-architecture",
    "literature-overview",
    "metric-selection-review",
    "model-card-refresh",
    "paper-to-implementation-plan",
    "publish-to-hub",
    "rag-evaluation",
    "reproduce-paper",
]


async def test_flow_catalog_route_lists_every_builtin_without_session_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", object())

    catalog = await agent_routes.list_flows({"user_id": "dev"})
    payload = [item.model_dump() for item in catalog]

    assert [item["id"] for item in payload] == EXPECTED_BUILTIN_IDS
    for item in payload:
        assert item["metadata"]["category"]
        assert item["metadata"]["runtime_class"]
        assert item["metadata"]["tags"]
        assert item["template_source"]["kind"] == "builtin"
        assert item["template_source"]["path"] == (
            f"backend/builtin_flow_templates/{item['id']}.json"
        )
        assert item["phase_count"] > 0
        assert item["required_inputs"]


@pytest.mark.parametrize("template_id", EXPECTED_BUILTIN_IDS)
async def test_flow_preview_route_returns_full_read_only_contract(
    template_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", object())

    response = await agent_routes.get_flow_preview(template_id, {"user_id": "dev"})
    payload = response.model_dump()

    assert payload["id"] == template_id
    assert payload["metadata"]["category"]
    assert payload["metadata"]["runtime_class"]
    assert payload["metadata"]["tags"]
    assert payload["template_source"] == {
        "kind": "builtin",
        "path": f"backend/builtin_flow_templates/{template_id}.json",
        "schema_version": "v1",
        "template_version": "v1",
    }
    assert payload["phases"]
    assert payload["required_inputs"]
    assert payload["budgets"]
    assert payload["approval_points"]
    assert payload["required_outputs"]
    assert payload["artifacts"]
    assert payload["verifier_checks"]
    assert payload["verifier_catalog_coverage"]["verifier_count"] == len(
        payload["verifier_checks"]
    )
    assert (
        payload["verifier_catalog_coverage"]["mapped_count"]
        + payload["verifier_catalog_coverage"]["unmapped_count"]
        == payload["verifier_catalog_coverage"]["verifier_count"]
    )
    assert payload["verifier_catalog_coverage"]["unknown_unmapped_verifier_ids"] == []
    for check in payload["verifier_checks"]:
        assert check["mapping_status"] in {
            "mapped",
            "intentional_unmapped",
            "unknown_unmapped",
        }
        assert "catalog_check_id" in check
        assert "catalog_check_name" in check
        assert "catalog_check_category" in check
        assert "catalog_check_type" in check
        assert isinstance(check["catalog_evidence_ref_types"], list)
    assert payload["risky_operations"]
    assert {operation["id"] for operation in payload["risky_operations"]} == {
        approval["id"] for approval in payload["approval_points"]
    }


async def test_flow_preview_route_enriches_verifiers_with_catalog_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_routes, "session_manager", object())
    template_before = get_builtin_flow_template("reproduce-paper").model_dump()

    response = await agent_routes.get_flow_preview(
        "reproduce-paper",
        {"user_id": "dev"},
    )
    payload = response.model_dump()
    checks = {check["id"]: check for check in payload["verifier_checks"]}

    assert list(checks) == [verifier["id"] for verifier in template_before["verifiers"]]
    assert checks["metric-recorded"]["mapping_status"] == "mapped"
    assert checks["metric-recorded"]["catalog_check_id"] == (
        CHECK_METRIC_PARSED_FROM_OUTPUT
    )
    assert checks["metric-recorded"]["catalog_check_name"] == (
        "Metric parsed from actual output"
    )
    assert checks["metric-recorded"]["catalog_check_category"] == "evaluation"
    assert checks["metric-recorded"]["catalog_check_type"] == "metric"
    assert checks["metric-recorded"]["catalog_evidence_ref_types"] == [
        "metric",
        "evidence",
        "experiment",
    ]
    assert checks["goal-is-testable"]["mapping_status"] == "intentional_unmapped"
    assert checks["goal-is-testable"]["catalog_check_id"] is None
    assert checks["goal-is-testable"]["catalog_check_name"] is None
    assert checks["goal-is-testable"]["catalog_check_category"] is None
    assert checks["goal-is-testable"]["catalog_check_type"] is None
    assert checks["goal-is-testable"]["catalog_evidence_ref_types"] == []
    assert payload["verifier_catalog_coverage"] == {
        "verifier_count": len(checks),
        "mapped_count": len(checks) - 1,
        "unmapped_count": 1,
        "intentional_unmapped_verifier_ids": ["goal-is-testable"],
        "unknown_unmapped_verifier_ids": [],
    }
    assert get_builtin_flow_template("reproduce-paper").model_dump() == template_before


async def test_flow_preview_route_returns_clear_not_found_error() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await agent_routes.get_flow_preview("missing-flow", {"user_id": "dev"})

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {
        "error": "flow_template_not_found",
        "template_id": "missing-flow",
        "message": "Unknown built-in flow template: missing-flow",
    }
