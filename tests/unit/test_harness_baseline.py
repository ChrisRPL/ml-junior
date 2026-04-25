"""Smoke tests for the shared offline test harness."""

from agent.config import Config
from agent.core.session import Event
from backend import user_quotas


def test_project_and_backend_imports_are_configured():
    assert Config(model_name="test/model").model_name == "test/model"
    assert user_quotas.daily_cap_for("free") == user_quotas.CLAUDE_FREE_DAILY


async def test_shared_event_queue_fixture(event_queue, event_collector):
    await event_queue.put(Event(event_type="ready", data={"message": "ok"}))

    events = await event_collector(event_queue)

    assert [event.event_type for event in events] == ["ready"]
    assert event_queue.empty()


async def test_fake_tool_router_fixture(fake_tool_router):
    output, success = await fake_tool_router.call_tool(
        "echo",
        {"value": 1},
        tool_call_id="tc_1",
    )

    assert success is True
    assert output == "echo:{'value': 1}"
    assert fake_tool_router.calls == [("echo", {"value": 1}, "tc_1")]
