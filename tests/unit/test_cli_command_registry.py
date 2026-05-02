from agent.core.commands import (
    COMMAND_REGISTRY,
    filter_commands,
    format_command_help,
    parse_slash_command,
)


REQUIRED_COMMANDS_BY_GROUP = {
    "project": {
        "/new",
        "/open",
        "/status",
        "/handoff",
        "/handoff preview",
        "/export",
        "/doctor",
        "/doctor local-inference",
    },
    "flow": {
        "/flows",
        "/flow preview",
        "/flow start",
        "/flow pause",
        "/flow resume",
        "/flow fork",
        "/phase",
        "/plan",
    },
    "experiment": {
        "/experiments",
        "/runs",
        "/run show",
        "/run compare",
        "/run fork",
        "/metrics",
        "/artifacts",
    },
    "tools": {
        "/tools",
        "/jobs",
        "/approve",
        "/deny",
        "/permissions",
        "/budget",
    },
    "evidence": {
        "/evidence",
        "/decisions",
        "/assumptions",
        "/compact",
        "/memory",
        "/ledger",
        "/ledger verify",
        "/proof bundle",
        "/share-traces",
    },
    "code": {
        "/diff",
        "/test",
        "/rollback",
        "/commit",
        "/pr",
        "/data snapshot",
        "/data diff",
        "/eval",
        "/package",
    },
}

IMPLEMENTED_COMMANDS = {
    "/help",
    "/undo",
    "/compact",
    "/model",
    "/effort",
    "/yolo",
    "/status",
    "/quit",
    "/flows",
    "/flow preview",
    "/handoff preview",
    "/doctor local-inference",
    "/runs",
    "/run show",
    "/metrics",
    "/artifacts",
    "/evidence",
    "/decisions",
    "/assumptions",
    "/ledger",
}

PRIORITY_BACKEND_CAPABILITIES = {
    "/status": "project.snapshot_read",
    "/phase": "workflow.phase_state",
    "/runs": "experiment.run_index",
    "/artifacts": "artifact.index_read",
    "/evidence": "evidence.search",
    "/decisions": "decision.log_read",
    "/ledger": "ledger.read",
    "/handoff": "project.handoff_summary",
    "/handoff preview": "project.handoff_preview",
}


def _registry_by_name():
    return {command.name: command for command in COMMAND_REGISTRY}


def test_registry_contains_required_metadata():
    registry = _registry_by_name()
    required_names = set().union(*REQUIRED_COMMANDS_BY_GROUP.values())

    assert required_names <= set(registry)
    for name, command in registry.items():
        assert command.description
        assert isinstance(command.arguments, str)
        assert command.risk_level
        assert isinstance(command.mutates_state, bool)
        assert command.group
        assert command.status in {"implemented", "planned"}
        assert command.required_backend_capability
        assert "." in command.required_backend_capability


def test_registry_groups_required_catalog_entries():
    grouped = {}
    for command in COMMAND_REGISTRY:
        grouped.setdefault(command.group, set()).add(command.name)

    for group, names in REQUIRED_COMMANDS_BY_GROUP.items():
        assert names <= grouped[group]


def test_backlog_commands_are_planned_except_existing_runtime_commands():
    registry = _registry_by_name()
    required_names = set().union(*REQUIRED_COMMANDS_BY_GROUP.values())
    planned_names = required_names - IMPLEMENTED_COMMANDS

    for name in planned_names:
        assert registry[name].implemented is False
        assert registry[name].status == "planned"

    for name in IMPLEMENTED_COMMANDS:
        assert registry[name].implemented is True
        assert registry[name].status == "implemented"


def test_handoff_remains_planned_and_mutating_while_preview_is_read_only():
    registry = _registry_by_name()

    assert registry["/handoff"].implemented is False
    assert registry["/handoff"].mutates_state is True
    assert registry["/handoff"].required_backend_capability == (
        "project.handoff_summary"
    )
    assert registry["/handoff preview"].implemented is True
    assert registry["/handoff preview"].mutates_state is False
    assert registry["/handoff preview"].required_backend_capability == (
        "project.handoff_preview"
    )


def test_priority_commands_have_backend_capability_metadata():
    registry = _registry_by_name()

    for name, capability in PRIORITY_BACKEND_CAPABILITIES.items():
        assert registry[name].required_backend_capability == capability


def test_parse_exact_command_with_arguments():
    parsed = parse_slash_command("/flow preview tests/fixtures/flow-template.json")

    assert parsed.spec is not None
    assert parsed.spec.name == "/flow preview"
    assert parsed.command_text == "/flow preview"
    assert parsed.arguments == "tests/fixtures/flow-template.json"
    assert parsed.suggestions == ()


def test_parse_planned_subcommands_with_longest_match():
    parsed = parse_slash_command(
        "/run compare tests/fixtures/runs/left tests/fixtures/runs/right --metric loss"
    )

    assert parsed.spec is not None
    assert parsed.spec.name == "/run compare"
    assert parsed.command_text == "/run compare"
    assert parsed.arguments == (
        "tests/fixtures/runs/left tests/fixtures/runs/right --metric loss"
    )

    data_parsed = parse_slash_command(
        "/data diff tests/fixtures/snapshots/train-v1 tests/fixtures/snapshots/train-v2"
    )
    assert data_parsed.spec is not None
    assert data_parsed.spec.name == "/data diff"
    assert data_parsed.arguments == (
        "tests/fixtures/snapshots/train-v1 tests/fixtures/snapshots/train-v2"
    )


def test_parse_unknown_command_preserves_unknown_token_and_suggests():
    parsed = parse_slash_command("/modle huggingface/test-model")

    assert parsed.spec is None
    assert parsed.command_text == "/modle"
    assert parsed.arguments == "huggingface/test-model"
    assert [command.name for command in parsed.suggestions] == ["/model"]


def test_parse_alias_resolves_to_canonical_command():
    parsed = parse_slash_command("/exit")

    assert parsed.spec is not None
    assert parsed.spec.name == "/quit"
    assert parsed.command_text == "/exit"


def test_filter_commands_prefix_and_fuzzy_matches():
    assert [command.name for command in filter_commands("/mo")] == ["/model"]

    run_names = [command.name for command in filter_commands("run", limit=4)]
    assert run_names == ["/runs", "/run show", "/run compare", "/run fork"]

    fuzzy_names = [command.name for command in filter_commands("/compct")]
    assert fuzzy_names[0] == "/compact"


def test_planned_command_parse_supports_existing_cli_response():
    parsed = parse_slash_command("/ledger verify latest")

    assert parsed.spec is not None
    assert parsed.spec.name == "/ledger verify"
    assert parsed.spec.implemented is False
    assert parsed.spec.planned_message == (
        "/ledger verify is not available yet; requires backend capability "
        "`ledger.verify`."
    )
    assert "not implemented" not in parsed.spec.planned_message


def test_help_text_is_generated_from_registry_metadata():
    help_text = format_command_help()

    assert "[cyan]/help[/cyan]" in help_text
    assert "[cyan]/flow preview <id>[/cyan]" in help_text
    assert "[cyan]/doctor local-inference [runtime] [model][/cyan]" in help_text
    assert "[cyan]/ledger verify [bundle][/cyan]" in help_text
    assert "Run environment diagnostics" in help_text
    assert "requires: project.snapshot_read" in help_text
    assert "[dim](planned)[/dim]" in help_text
