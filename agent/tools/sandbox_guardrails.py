"""Guardrails for remote sandbox filesystem and log surfaces."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

from agent.core.redaction import REDACTED, redact_string


SANDBOX_ALLOWED_ROOTS = (PurePosixPath("/app"), PurePosixPath("/tmp"))
SANDBOX_DEFAULT_ROOT = PurePosixPath("/app")


@dataclass(frozen=True)
class SandboxGuardrailResult:
    allowed: bool
    reason: str = ""
    code: str | None = None
    path: str | None = None
    allowed_roots: tuple[str, ...] = ()


def check_sandbox_path(
    path: str | PurePosixPath,
    *,
    operation: str,
    default_root: str | PurePosixPath = SANDBOX_DEFAULT_ROOT,
) -> SandboxGuardrailResult:
    return _check_allowed_path(path, operation=operation, default_root=default_root)


def check_sandbox_work_dir(
    work_dir: str | PurePosixPath,
    *,
    default_root: str | PurePosixPath = SANDBOX_DEFAULT_ROOT,
) -> SandboxGuardrailResult:
    result = _check_allowed_path(
        work_dir,
        operation="execute from",
        default_root=default_root,
    )
    if not result.allowed and result.code == "sandbox_path_outside_allowed_roots":
        return SandboxGuardrailResult(
            allowed=False,
            reason=result.reason,
            code="sandbox_work_dir_outside_allowed_roots",
            path=result.path,
            allowed_roots=result.allowed_roots,
        )
    return result


def prepare_sandbox_tool_args(
    tool_name: str,
    args: dict[str, Any],
    *,
    default_root: str | PurePosixPath = SANDBOX_DEFAULT_ROOT,
) -> tuple[dict[str, Any] | None, SandboxGuardrailResult | None]:
    prepared = dict(args)
    if tool_name == "bash":
        guard = check_sandbox_work_dir(
            prepared.get("work_dir") or str(default_root),
            default_root=default_root,
        )
        if not guard.allowed:
            return None, guard
        prepared["work_dir"] = guard.path
        return prepared, None

    if tool_name in {"read", "write", "edit"}:
        guard = check_sandbox_path(
            prepared.get("path", ""),
            operation=tool_name,
            default_root=default_root,
        )
        if not guard.allowed:
            return None, guard
        prepared["path"] = guard.path
        return prepared, None

    return prepared, None


def redact_sandbox_text(
    value: Any,
    secret_values: Iterable[str | None] = (),
) -> str:
    text = "" if value is None else str(value)
    for secret in sorted({s for s in secret_values if s}, key=len, reverse=True):
        if secret == REDACTED:
            continue
        text = text.replace(secret, REDACTED)
    return redact_string(text).value


def _check_allowed_path(
    path: str | PurePosixPath,
    *,
    operation: str,
    default_root: str | PurePosixPath,
) -> SandboxGuardrailResult:
    root_strings = tuple(str(root) for root in SANDBOX_ALLOWED_ROOTS)
    try:
        normalized = _normalize_sandbox_path(path, default_root=default_root)
    except (TypeError, ValueError) as exc:
        return SandboxGuardrailResult(
            allowed=False,
            reason=f"Sandbox {operation} denied: invalid path {path!r}: {exc}",
            code="sandbox_invalid_path",
            allowed_roots=root_strings,
        )

    if any(_path_is_relative_to(normalized, root) for root in SANDBOX_ALLOWED_ROOTS):
        return SandboxGuardrailResult(
            allowed=True,
            path=str(normalized),
            allowed_roots=root_strings,
        )

    return SandboxGuardrailResult(
        allowed=False,
        reason=(
            f"Sandbox {operation} denied: {normalized} is outside allowed roots "
            f"({', '.join(root_strings)})."
        ),
        code="sandbox_path_outside_allowed_roots",
        path=str(normalized),
        allowed_roots=root_strings,
    )


def _normalize_sandbox_path(
    path: str | PurePosixPath,
    *,
    default_root: str | PurePosixPath,
) -> PurePosixPath:
    raw = str(path)
    if not raw.strip():
        raise ValueError("path is empty")
    if "\x00" in raw:
        raise ValueError("path contains NUL byte")

    root = PurePosixPath(str(default_root))
    candidate = PurePosixPath(raw)
    if not candidate.is_absolute():
        candidate = root / candidate

    normalized = posixpath.normpath(str(candidate))
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return PurePosixPath(normalized)


def _path_is_relative_to(path: PurePosixPath, root: PurePosixPath) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
