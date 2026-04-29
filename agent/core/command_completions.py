"""Inline slash-command completions for the interactive CLI."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from agent.core.commands import COMMAND_REGISTRY, CommandSpec


@dataclass(frozen=True, slots=True)
class CommandCompletionRow:
    """Pure completion row, independent from prompt_toolkit."""

    text: str
    display: str
    display_meta: str
    start_position: int
    spec: CommandSpec
    matched_candidate: str
    match_kind: str

    @property
    def group(self) -> str:
        return self.spec.group


@dataclass(frozen=True, slots=True)
class CommandCompletionGroup:
    """Completion rows grouped by command catalog group."""

    group: str
    rows: tuple[CommandCompletionRow, ...]


def slash_command_completion_rows(
    text_before_cursor: str,
    registry: Iterable[CommandSpec] | None = None,
    limit: int = 8,
) -> tuple[CommandCompletionRow, ...]:
    """Return ranked slash-command completion rows for text before the cursor."""

    entries = tuple(registry or COMMAND_REGISTRY)
    query = _completion_query(text_before_cursor, entries)
    if query is None:
        return ()

    normalized = _normalize_query(query)
    if not normalized:
        return ()

    matches: list[tuple[int, int, CommandCompletionRow]] = []
    for index, spec in enumerate(entries):
        scored = _best_candidate_score(normalized, spec)
        if scored is None:
            continue

        score, matched_candidate, match_kind = scored
        matches.append(
            (
                score,
                index,
                CommandCompletionRow(
                    text=_completion_text(spec),
                    display=spec.usage,
                    display_meta=_display_meta(spec),
                    start_position=-len(query),
                    spec=spec,
                    matched_candidate=matched_candidate,
                    match_kind=match_kind,
                ),
            )
        )

    matches.sort(key=lambda item: (-item[0], item[1]))
    return tuple(row for _, _, row in matches[:limit])


def grouped_slash_command_completion_rows(
    text_before_cursor: str,
    registry: Iterable[CommandSpec] | None = None,
    limit: int = 8,
) -> tuple[CommandCompletionGroup, ...]:
    """Return slash-command completion rows grouped by registry group."""

    rows = slash_command_completion_rows(text_before_cursor, registry, limit)
    groups: dict[str, list[CommandCompletionRow]] = {}
    for row in rows:
        groups.setdefault(row.group, []).append(row)
    return tuple(
        CommandCompletionGroup(group=group, rows=tuple(group_rows))
        for group, group_rows in groups.items()
    )


def build_slash_command_completer(
    registry: Iterable[CommandSpec] | None = None,
    limit: int = 8,
):
    """Build a prompt_toolkit completer backed by the pure completion helper."""

    from prompt_toolkit.completion import Completer, Completion

    class SlashCommandCompleter(Completer):
        def get_completions(self, document, complete_event):
            del complete_event
            for row in slash_command_completion_rows(
                document.text_before_cursor,
                registry=registry,
                limit=limit,
            ):
                yield Completion(
                    row.text,
                    start_position=row.start_position,
                    display=row.display,
                    display_meta=row.display_meta,
                )

    return SlashCommandCompleter()


def _completion_query(
    text_before_cursor: str,
    registry: tuple[CommandSpec, ...],
) -> str | None:
    query = text_before_cursor.lstrip()
    if not query.startswith("/"):
        return None
    normalized = _normalize_query(query)
    for spec in registry:
        for candidate in _candidate_names(spec):
            candidate_name = _normalize_query(candidate)
            if candidate_name != normalized and candidate_name.startswith(normalized):
                return query
    if _has_arguments_after_complete_command(query, registry):
        return None
    return query


def _has_arguments_after_complete_command(
    query: str,
    registry: tuple[CommandSpec, ...],
) -> bool:
    stripped = query.strip()
    if not stripped:
        return False

    input_tokens = tuple(stripped.lower().split())
    if len(input_tokens) < 2:
        return False

    has_trailing_space = query[-1:].isspace()
    for spec in registry:
        for candidate in _candidate_names(spec):
            candidate_tokens = tuple(_normalize_query(candidate).split())
            if input_tokens[: len(candidate_tokens)] != candidate_tokens:
                continue
            if len(input_tokens) > len(candidate_tokens):
                return True
            if has_trailing_space and len(input_tokens) == len(candidate_tokens):
                return True
    return False


def _best_candidate_score(
    normalized: str,
    spec: CommandSpec,
) -> tuple[int, str, str] | None:
    best: tuple[int, str, str] | None = None
    for candidate in _candidate_names(spec):
        candidate_name = _normalize_query(candidate)
        scored = _score_candidate(normalized, candidate_name)
        if scored is None:
            continue

        score, match_kind = scored
        if best is None or score > best[0]:
            best = (score, candidate_name, match_kind)
    return best


def _score_candidate(normalized: str, candidate_name: str) -> tuple[int, str] | None:
    if candidate_name == normalized:
        return 300, "exact"
    if candidate_name.startswith(normalized):
        return 200, "prefix"
    if normalized in candidate_name:
        return 150, "contains"

    ratio = SequenceMatcher(None, normalized, candidate_name).ratio()
    if ratio >= 0.72:
        return int(ratio * 100), "fuzzy"
    return None


def _completion_text(spec: CommandSpec) -> str:
    return f"{spec.name} " if spec.arguments else spec.name


def _display_meta(spec: CommandSpec) -> str:
    state = "mutates state" if spec.mutates_state else "read-only"
    return (
        f"{spec.group} | {spec.status} | {spec.risk_level} risk | {state} | "
        f"requires: {spec.required_backend_capability}"
    )


def _candidate_names(spec: CommandSpec) -> tuple[str, ...]:
    return (spec.name, *spec.aliases)


def _normalize_query(query: str) -> str:
    normalized = " ".join(query.strip().lower().split())
    if normalized and not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized
