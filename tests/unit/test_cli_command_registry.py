from agent.core.commands import (
    COMMAND_REGISTRY,
    filter_commands,
    format_command_help,
    parse_slash_command,
)


def _registry_by_name():
    return {command.name: command for command in COMMAND_REGISTRY}


def test_registry_contains_required_metadata():
    registry = _registry_by_name()

    for name in (
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
        "/budget",
        "/experiments",
        "/artifacts",
        "/approve",
        "/doctor",
    ):
        command = registry[name]
        assert command.description
        assert isinstance(command.arguments, str)
        assert command.risk_level
        assert isinstance(command.mutates_state, bool)


def test_parse_exact_command_with_arguments():
    parsed = parse_slash_command("/flow preview configs/demo.yaml")

    assert parsed.spec is not None
    assert parsed.spec.name == "/flow preview"
    assert parsed.command_text == "/flow preview"
    assert parsed.arguments == "configs/demo.yaml"
    assert parsed.suggestions == ()


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

    fuzzy_names = [command.name for command in filter_commands("/compct")]
    assert fuzzy_names[0] == "/compact"


def test_help_text_is_generated_from_registry_metadata():
    help_text = format_command_help()

    assert "[cyan]/help[/cyan]" in help_text
    assert "[cyan]/flow preview <flow>[/cyan]" in help_text
    assert "Run environment diagnostics" in help_text
