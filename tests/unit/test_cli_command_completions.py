from __future__ import annotations

from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import to_plain_text

from agent.core.command_completions import (
    build_slash_command_completer,
    grouped_slash_command_completion_rows,
    slash_command_completion_rows,
)


def _names(rows):
    return [row.spec.name for row in rows]


def test_slash_completion_rows_group_flow_subcommands() -> None:
    groups = grouped_slash_command_completion_rows("/flow", limit=6)

    assert [group.group for group in groups] == ["flow"]
    assert _names(groups[0].rows) == [
        "/flows",
        "/flow preview",
        "/flow start",
        "/flow pause",
        "/flow resume",
        "/flow fork",
    ]
    assert all("flow |" in row.display_meta for row in groups[0].rows)


def test_slash_completion_matches_alias_to_canonical_command() -> None:
    rows = slash_command_completion_rows("/exit")

    assert rows[0].spec.name == "/quit"
    assert rows[0].matched_candidate == "/exit"
    assert rows[0].match_kind == "exact"
    assert rows[0].text == "/quit"


def test_slash_completion_ranking_is_stable_for_exact_prefix_and_fuzzy() -> None:
    exact = slash_command_completion_rows("/model")
    assert exact[0].spec.name == "/model"
    assert exact[0].match_kind == "exact"

    prefix = slash_command_completion_rows("/run", limit=4)
    assert _names(prefix) == ["/runs", "/run show", "/run compare", "/run fork"]
    assert {row.match_kind for row in prefix} == {"prefix"}

    fuzzy = slash_command_completion_rows("/compct")
    assert fuzzy[0].spec.name == "/compact"
    assert fuzzy[0].match_kind == "fuzzy"


def test_slash_completion_preserves_command_metadata_for_planned_commands() -> None:
    rows = slash_command_completion_rows("/ledger v")

    assert rows[0].spec.name == "/ledger verify"
    assert rows[0].spec.implemented is False
    assert rows[0].spec.status == "planned"
    assert rows[0].spec.group == "evidence"
    assert rows[0].spec.risk_level == "low"
    assert rows[0].spec.mutates_state is False
    assert rows[0].display == "/ledger verify [bundle]"
    assert rows[0].display_meta == "evidence | planned | low risk | read-only"
    assert rows[0].text == "/ledger verify "


def test_slash_completion_skips_non_slash_text_and_command_arguments() -> None:
    assert slash_command_completion_rows("hello /model") == ()
    assert slash_command_completion_rows("/flow preview fine-tune-model") == ()
    assert slash_command_completion_rows("/flow preview ") == ()
    assert _names(slash_command_completion_rows("/flow ")) == [
        "/flows",
        "/flow preview",
        "/flow start",
        "/flow pause",
        "/flow resume",
        "/flow fork",
    ]


def test_prompt_toolkit_adapter_uses_pure_completion_rows() -> None:
    completer = build_slash_command_completer()
    completions = list(completer.get_completions(Document("/flow p"), None))

    assert [completion.text for completion in completions[:2]] == [
        "/flow preview ",
        "/flow pause ",
    ]
    assert completions[0].start_position == len("/flow p") * -1
    assert to_plain_text(completions[0].display_meta) == (
        "flow | implemented | low risk | read-only"
    )
