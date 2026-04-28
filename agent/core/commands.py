"""Slash command registry and parser for the interactive CLI."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from agent.core.command_catalog import build_command_registry


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Metadata for a CLI slash command."""

    name: str
    description: str
    arguments: str = ""
    risk_level: str = "safe"
    mutates_state: bool = False
    aliases: tuple[str, ...] = ()
    implemented: bool = True
    group: str = "core"

    @property
    def usage(self) -> str:
        return f"{self.name} {self.arguments}".strip()

    @property
    def status(self) -> str:
        return "implemented" if self.implemented else "planned"


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    """Result of parsing one user-entered slash command."""

    source: str
    spec: CommandSpec | None
    command_text: str
    arguments: str = ""
    suggestions: tuple[CommandSpec, ...] = ()


COMMAND_REGISTRY: tuple[CommandSpec, ...] = build_command_registry(CommandSpec)


def _normalize_query(query: str) -> str:
    normalized = " ".join(query.strip().lower().split())
    if normalized and not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _command_tokens(command: str) -> tuple[str, ...]:
    return tuple(_normalize_query(command).split())


def _candidate_names(spec: CommandSpec) -> tuple[str, ...]:
    return (spec.name, *spec.aliases)


def _iter_registry(
    registry: Iterable[CommandSpec] | None = None,
) -> tuple[CommandSpec, ...]:
    return tuple(registry or COMMAND_REGISTRY)


def _arguments_after_token_count(source: str, token_count: int) -> str:
    remainder = source.strip()
    for _ in range(token_count):
        parts = remainder.split(None, 1)
        if len(parts) == 1:
            return ""
        remainder = parts[1].lstrip()
    return remainder


def parse_slash_command(
    source: str,
    registry: Iterable[CommandSpec] | None = None,
) -> ParsedCommand:
    """Parse a slash command, using longest exact registry match."""

    stripped = source.strip()
    if not stripped:
        return ParsedCommand(source=source, spec=None, command_text="")

    input_tokens = tuple(stripped.lower().split())
    command_matches: list[tuple[int, str, CommandSpec]] = []
    for spec in _iter_registry(registry):
        for candidate in _candidate_names(spec):
            candidate_tokens = _command_tokens(candidate)
            if input_tokens[: len(candidate_tokens)] == candidate_tokens:
                command_matches.append((len(candidate_tokens), candidate, spec))

    if command_matches:
        token_count, candidate, spec = max(command_matches, key=lambda item: item[0])
        return ParsedCommand(
            source=source,
            spec=spec,
            command_text=_normalize_query(candidate),
            arguments=_arguments_after_token_count(stripped, token_count),
        )

    unknown = input_tokens[0] if input_tokens else ""
    return ParsedCommand(
        source=source,
        spec=None,
        command_text=unknown,
        arguments=_arguments_after_token_count(stripped, 1),
        suggestions=filter_commands(unknown, registry=registry),
    )


def filter_commands(
    query: str,
    registry: Iterable[CommandSpec] | None = None,
    limit: int = 8,
) -> tuple[CommandSpec, ...]:
    """Return registry entries that match a query by exact, prefix, or fuzzy match."""

    normalized = _normalize_query(query)
    entries = _iter_registry(registry)
    if not normalized:
        return entries[:limit]

    matches: list[tuple[int, int, CommandSpec]] = []
    for index, spec in enumerate(entries):
        best_score = 0
        for candidate in _candidate_names(spec):
            candidate_name = _normalize_query(candidate)
            if candidate_name == normalized:
                best_score = max(best_score, 100)
            elif candidate_name.startswith(normalized):
                best_score = max(best_score, 90)
            elif normalized in candidate_name:
                best_score = max(best_score, 80)
            else:
                ratio = SequenceMatcher(None, normalized, candidate_name).ratio()
                if ratio >= 0.72:
                    best_score = max(best_score, int(ratio * 70))
        if best_score:
            matches.append((best_score, index, spec))

    matches.sort(key=lambda item: (-item[0], item[1]))
    return tuple(spec for _, _, spec in matches[:limit])


def format_command_help(
    registry: Iterable[CommandSpec] | None = None,
    indent: str = "  ",
) -> str:
    """Build rich-markup help text from registry metadata."""

    entries = _iter_registry(registry)
    usage_width = max(len(entry.usage) for entry in entries)
    lines = [f"{indent}[bold]Commands[/bold]"]
    for entry in entries:
        padding = " " * (usage_width - len(entry.usage) + 2)
        planned = " [dim](planned)[/dim]" if not entry.implemented else ""
        lines.append(
            f"{indent}  [cyan]{entry.usage}[/cyan]{padding}"
            f"{entry.description}{planned}"
        )
    return "\n".join(lines)
