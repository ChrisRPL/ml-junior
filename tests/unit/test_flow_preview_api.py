from __future__ import annotations

import pytest
from fastapi import HTTPException

import routes.agent as agent_routes


EXPECTED_BUILTIN_IDS = [
    "build-evaluation-harness",
    "dataset-audit",
    "fine-tune-model",
    "implement-architecture",
    "literature-overview",
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
    assert payload["risky_operations"]
    assert {operation["id"] for operation in payload["risky_operations"]} == {
        approval["id"] for approval in payload["approval_points"]
    }


async def test_flow_preview_route_returns_clear_not_found_error() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await agent_routes.get_flow_preview("missing-flow", {"user_id": "dev"})

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {
        "error": "flow_template_not_found",
        "template_id": "missing-flow",
        "message": "Unknown built-in flow template: missing-flow",
    }
