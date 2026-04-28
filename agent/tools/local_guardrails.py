"""Guardrails for local filesystem and shell execution tools."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


LOCAL_ALLOWED_ROOTS_ENV = "MLJ_LOCAL_ALLOWED_ROOTS"
LOCAL_WORKSPACE_ROOT_ENV = "MLJ_LOCAL_WORKSPACE_ROOT"


@dataclass(frozen=True)
class LocalGuardrailResult:
    allowed: bool
    reason: str = ""
    code: str | None = None
    path: str | None = None
    allowed_roots: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShellCommandRisk:
    risk: str
    reason: str
    code: str = "local_destructive_command"
    pattern: str | None = None


@dataclass(frozen=True)
class LocalPolicyFailure:
    risk: str
    reason: str
    code: str
    side_effects: tuple[str, ...]
    credential_usage: tuple[str, ...]


def local_allowed_roots(config: Any | None = None) -> tuple[Path, ...]:
    """Return normalized roots that local tools may access."""

    candidates: list[str | os.PathLike[str]] = []
    _extend_env_paths(candidates, os.environ.get(LOCAL_ALLOWED_ROOTS_ENV))
    _append_path(candidates, os.environ.get(LOCAL_WORKSPACE_ROOT_ENV))

    for attr in (
        "local_allowed_roots",
        "allowed_roots",
        "workspace_roots",
        "workspace_root",
        "workspace",
        "project_root",
    ):
        _append_path(candidates, getattr(config, attr, None) if config is not None else None)

    candidates.append(Path.cwd())

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            root = _normalize_path(candidate)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        root_str = str(root)
        if root_str in seen:
            continue
        seen.add(root_str)
        roots.append(root)
    return tuple(roots)


def check_local_path(
    path: str | os.PathLike[str],
    *,
    operation: str,
    config: Any | None = None,
) -> LocalGuardrailResult:
    return _check_allowed_path(path, operation=operation, config=config)


def check_local_work_dir(
    work_dir: str | os.PathLike[str],
    *,
    config: Any | None = None,
) -> LocalGuardrailResult:
    return _check_allowed_path(work_dir, operation="execute from", config=config)


def classify_shell_command(command: str) -> ShellCommandRisk | None:
    """Return a risk classification for shell commands we never execute locally."""

    if not command.strip():
        return None

    try:
        segments = _command_segments(command)
    except ValueError:
        return _classify_shell_command_regex(command)

    for segment in segments:
        risk = _classify_segment(segment)
        if risk is not None:
            return risk
    return None


def evaluate_local_policy_failure(
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    config: Any | None = None,
    is_local_tool: bool,
) -> LocalPolicyFailure | None:
    if tool_name == "bash":
        if not is_local_tool:
            return None

        command_risk = classify_shell_command(str(tool_args.get("command", "")))
        if command_risk is not None:
            return LocalPolicyFailure(
                risk=command_risk.risk,
                reason=command_risk.reason,
                code=command_risk.code,
                side_effects=("local_exec", "local_destructive_command"),
                credential_usage=("local_system",),
            )

        work_dir = tool_args.get("work_dir", ".")
        work_dir_guard = check_local_work_dir(work_dir, config=config)
        if not work_dir_guard.allowed:
            return LocalPolicyFailure(
                risk="high",
                reason=work_dir_guard.reason,
                code="local_work_dir_outside_workspace",
                side_effects=("local_filesystem_guardrail",),
                credential_usage=("local_system",),
            )
        return None

    if is_local_tool and tool_name in {"read", "write", "edit"}:
        path = tool_args.get("path", "")
        if not path:
            return None
        path_guard = check_local_path(path, operation=tool_name, config=config)
        if not path_guard.allowed:
            return LocalPolicyFailure(
                risk="high",
                reason=path_guard.reason,
                code=path_guard.code or "local_path_outside_workspace",
                side_effects=("local_filesystem_guardrail",),
                credential_usage=("local_filesystem",),
            )

    return None


def _check_allowed_path(
    path: str | os.PathLike[str],
    *,
    operation: str,
    config: Any | None,
) -> LocalGuardrailResult:
    roots = local_allowed_roots(config)
    root_strings = tuple(str(root) for root in roots)
    try:
        resolved = _normalize_path(path)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return LocalGuardrailResult(
            allowed=False,
            reason=f"Local {operation} denied: invalid path {path!r}: {exc}",
            code="local_invalid_path",
            allowed_roots=root_strings,
        )

    if any(_path_is_relative_to(resolved, root) for root in roots):
        return LocalGuardrailResult(
            allowed=True,
            path=str(resolved),
            allowed_roots=root_strings,
        )

    return LocalGuardrailResult(
        allowed=False,
        reason=(
            f"Local {operation} denied: {resolved} is outside allowed roots "
            f"({_format_roots(root_strings)})."
        ),
        code="local_path_outside_workspace",
        path=str(resolved),
        allowed_roots=root_strings,
    )


def _append_path(target: list[str | os.PathLike[str]], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _append_path(target, item)
        return
    if isinstance(value, os.PathLike):
        target.append(value)
        return
    if isinstance(value, str) and value.strip():
        target.append(value)


def _extend_env_paths(target: list[str | os.PathLike[str]], value: str | None) -> None:
    if not value:
        return
    for item in value.split(os.pathsep):
        if item.strip():
            target.append(item)


def _normalize_path(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve(strict=False)


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _format_roots(roots: Iterable[str]) -> str:
    return ", ".join(roots) or "none"


def _command_segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in {";", "&&", "||", "|", "&", "(", ")"}:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _classify_segment(segment: list[str]) -> ShellCommandRisk | None:
    if not segment:
        return None

    command_index = _effective_command_index(segment)
    if command_index is None:
        return None

    command = _command_name(segment[command_index])
    args = segment[command_index + 1 :]

    if command in {"rm", "unlink", "shred", "srm"}:
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: remove/delete command.",
            pattern=command,
        )

    if command == "git":
        return _classify_git_command(args)

    if command == "find" and "-delete" in args:
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: find -delete.",
            pattern="find -delete",
        )

    if command == "xargs" and any(
        _command_name(token) in {"rm", "unlink", "shred", "srm"} for token in args
    ):
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: xargs delete command.",
            pattern="xargs rm",
        )

    if command == "truncate" and _truncate_zeroes_file(args):
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: truncate to zero bytes.",
            pattern="truncate -s 0",
        )

    if command == "dd" and any(token.startswith("of=") for token in args):
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: dd writes to an output file/device.",
            pattern="dd of=",
        )

    if command.startswith("mkfs") or command in {"fdisk", "parted"}:
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: disk formatting/partitioning.",
            pattern=command,
        )

    if command == "diskutil" and args and args[0] in {"eraseDisk", "eraseVolume"}:
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: disk erase operation.",
            pattern=f"diskutil {args[0]}",
        )

    return None


def _effective_command_index(segment: list[str]) -> int | None:
    index = 0
    while index < len(segment):
        token = segment[index]
        if _is_assignment(token) or token in {"time", "command", "builtin", "exec", "noglob"}:
            index += 1
            continue

        command = _command_name(token)
        if command in {"sudo", "doas", "nohup", "nice", "ionice"}:
            index += 1
            while index < len(segment) and segment[index].startswith("-"):
                if segment[index] in {"-u", "-g", "-h", "-p", "-C", "-T"}:
                    index += 2
                    continue
                index += 1
            continue

        if command == "env":
            index += 1
            while index < len(segment) and (
                segment[index].startswith("-") or _is_assignment(segment[index])
            ):
                index += 1
            continue

        return index
    return None


def _is_assignment(token: str) -> bool:
    if "=" not in token or token.startswith("="):
        return False
    name = token.split("=", 1)[0]
    return name.replace("_", "").isalnum() and not name[0].isdigit()


def _command_name(token: str) -> str:
    return Path(token).name.lower()


def _classify_git_command(args: list[str]) -> ShellCommandRisk | None:
    if not args:
        return None

    subcommand_index = 0
    while subcommand_index < len(args):
        arg = args[subcommand_index]
        if arg in {"-C", "-c", "--config-env"}:
            subcommand_index += 2
            continue
        if not arg.startswith("-"):
            break
        subcommand_index += 1
    if subcommand_index >= len(args):
        return None

    subcommand = args[subcommand_index]
    sub_args = args[subcommand_index + 1 :]
    if subcommand == "reset" and "--hard" in sub_args:
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: git reset --hard.",
            pattern="git reset --hard",
        )
    if subcommand == "clean":
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: git clean.",
            pattern="git clean",
        )
    if subcommand == "restore":
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: git restore.",
            pattern="git restore",
        )
    if subcommand == "checkout" and any(arg in {"--", ".", ":/"} for arg in sub_args):
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: git checkout path restore.",
            pattern="git checkout --",
        )
    if subcommand == "rm":
        return ShellCommandRisk(
            risk="critical",
            reason="Destructive local shell command blocked: git rm.",
            pattern="git rm",
        )
    return None


def _truncate_zeroes_file(args: list[str]) -> bool:
    for index, arg in enumerate(args):
        if arg == "-s" and index + 1 < len(args) and args[index + 1] == "0":
            return True
        if arg.startswith("--size=") and arg.split("=", 1)[1] == "0":
            return True
    return False


def _classify_shell_command_regex(command: str) -> ShellCommandRisk | None:
    lowered = command.lower()
    regex_patterns = (
        ("rm ", "remove/delete command"),
        ("git reset --hard", "git reset --hard"),
        ("git clean", "git clean"),
        ("git restore", "git restore"),
        ("find ", "find -delete"),
    )
    if "find " in lowered and " -delete" not in lowered:
        return None
    for pattern, label in regex_patterns:
        if pattern in lowered:
            return ShellCommandRisk(
                risk="critical",
                reason=f"Destructive local shell command blocked: {label}.",
                pattern=label,
            )
    return None
