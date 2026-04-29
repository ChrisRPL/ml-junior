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
        "/export",
        "/doctor",
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


def test_parse_exact_command_with_arguments():
    parsed = parse_slash_command("/flow preview configs/demo.yaml")

    assert parsed.spec is not None
    assert parsed.spec.name == "/flow preview"
    assert parsed.command_text == "/flow preview"
    assert parsed.arguments == "configs/demo.yaml"
    assert parsed.suggestions == ()


def test_parse_planned_subcommands_with_longest_match():
    parsed = parse_slash_command("/run compare baseline candidate --metric loss")

    assert parsed.spec is not None
    assert parsed.spec.name == "/run compare"
    assert parsed.command_text == "/run compare"
    assert parsed.arguments == "baseline candidate --metric loss"

    data_parsed = parse_slash_command("/data diff train-v1 train-v2")
    assert data_parsed.spec is not None
    assert data_parsed.spec.name == "/data diff"
    assert data_parsed.arguments == "train-v1 train-v2"


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
    assert f"{parsed.spec.name} is not implemented yet." == (
        "/ledger verify is not implemented yet."
    )


def test_help_text_is_generated_from_registry_metadata():
    help_text = format_command_help()

    assert "[cyan]/help[/cyan]" in help_text
    assert "[cyan]/flow preview <id>[/cyan]" in help_text
    assert "[cyan]/ledger verify [bundle][/cyan]" in help_text
    assert "Run environment diagnostics" in help_text
    assert "[dim](planned)[/dim]" in help_text
