from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

REDACTED = "[REDACTED]"
REDACTED_DATASET_ROWS = "[REDACTED_DATASET_ROWS]"

REDACTION_NONE = "none"
REDACTION_PARTIAL = "partial"
REDACTION_REDACTED = "redacted"


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    status: str = REDACTION_NONE


_Replacement: TypeAlias = str | Callable[[re.Match[str]], str]


@dataclass(frozen=True)
class StringRedactionRule:
    name: str
    pattern: re.Pattern[str]
    replacement: _Replacement

    def apply(self, value: str) -> str:
        return self.pattern.sub(self.replacement, value)


@dataclass(frozen=True)
class RedactionPolicy:
    secret_key_pattern: re.Pattern[str]
    sensitive_string_patterns: tuple[re.Pattern[str], ...]
    string_rules: tuple[StringRedactionRule, ...]
    private_flags: frozenset[str]
    private_row_keys: frozenset[str]

    def redact_string(self, value: str) -> RedactionResult:
        if any(
            pattern.fullmatch(value.strip())
            for pattern in self.sensitive_string_patterns
        ):
            return RedactionResult(REDACTED, REDACTION_REDACTED)

        redacted = value
        for rule in self.string_rules:
            redacted = rule.apply(redacted)

        if redacted == value:
            return RedactionResult(value, REDACTION_NONE)
        return RedactionResult(redacted, REDACTION_PARTIAL)

    def is_secret_key(self, key: str) -> bool:
        return self.secret_key_pattern.search(key) is not None

    def is_private_marker(self, key: str, value: Any) -> bool:
        return key.lower() in self.private_flags and value is True

    def is_private_row_key(self, key: str) -> bool:
        return key.lower() in self.private_row_keys


_SECRET_KEY_RE = re.compile(
    r"(^|[_\-.])("
    r"hf[_-]?token|github[_-]?token|authorization|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"client[_-]?secret|secret|password|passwd|private[_-]?key"
    r")([_\-.]|$)",
    re.IGNORECASE,
)
_SENSITIVE_STRING_RE = re.compile(
    r"^(hf_[A-Za-z0-9_\-]{8,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"gh[opsru]_[A-Za-z0-9_]{20,})$"
)
_BEARER_RE = re.compile(
    r"(?i)\b(authorization\s*:\s*bearer\s+|bearer\s+)"
    r"([A-Za-z0-9._\-:~+/=]{8,})"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(authorization\s*:\s*(?:bearer|basic|token|apikey)\s+)"
    r"([A-Za-z0-9._\-:~+/=]{8,})"
)
_ENV_ASSIGN_RE = re.compile(
    r"(?i)\b(HF_TOKEN|GITHUB_TOKEN)\s*([=:])\s*"
    r"(['\"]?)([^'\"\s,;)}\]\[]+)(\3)"
)
_KEY_VALUE_RE = re.compile(
    r"(?i)(\b['\"]?)([A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|auth[_-]?token|client[_-]?secret|secret|"
    r"password|passwd|private[_-]?key|github[_-]?token|hf[_-]?token)"
    r"[A-Za-z0-9_.-]*)(['\"]?\s*[:=]\s*['\"]?)([^'\"\s,;)}\]\[&]+)(['\"]?)"
)
_SECRET_FLAG_RE = re.compile(
    r"(?i)(--(?:token|api-key|access-token|auth-token|secret|password)\s+)"
    r"([^'\"\s,;)}\]\[]+)"
)
_URL_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&](?:token|access_token|auth_token|refresh_token|api_key|key|"
    r"signature|sig|secret|client_secret|password|passwd|jwt)=)"
    r"([^&#\s]+)"
)
_HF_TOKEN_RE = re.compile(r"\bhf_[A-Za-z0-9_\-]{8,}\b")
_GITHUB_TOKEN_RE = re.compile(
    r"\b(github_pat_[A-Za-z0-9_]{20,}|gh[opsru]_[A-Za-z0-9_]{20,})\b"
)
_OPAQUE_AUTH_TOKEN_RE = re.compile(
    r"\b(?:sk-(?:proj-)?[A-Za-z0-9_\-]{12,}|xox[baprs]-[A-Za-z0-9_\-]{12,}|"
    r"glpat-[A-Za-z0-9_\-]{12,})\b"
)
_MAC_USER_PATH_RE = re.compile(r"(?<![\w.-])(/Users/)([^/\s:]+)")
_LINUX_USER_PATH_RE = re.compile(r"(?<![\w.-])(/home/)([^/\s:]+)")
_WINDOWS_USER_PATH_RE = re.compile(r"(?i)\b([A-Z]:[\\/]+Users[\\/]+)([^\\/\s:]+)")
_PRIVATE_DATASET_SAMPLE_RE = re.compile(
    r"(?is)(private\s*[:=]\s*true.*?)(##\s*Sample Rows\b.*)"
)
_PRIVATE_DATASET_ROWS_RE = re.compile(
    r"(?is)((?:private|is_private|gated)\s*[:=]\s*true.*?"
    r"\b(?:sample rows|rows|first rows|examples|preview)\s*[:=]\s*)"
    r"(?:\[[\s\S]*|\{[\s\S]*|\n[\s\S]*)"
)

_PRIVATE_FLAGS = {"private", "is_private", "gated"}
_PRIVATE_ROW_KEYS = {
    "row",
    "rows",
    "sample_row",
    "sample_rows",
    "first_rows",
    "examples",
    "preview",
}


DEFAULT_REDACTION_POLICY = RedactionPolicy(
    secret_key_pattern=_SECRET_KEY_RE,
    sensitive_string_patterns=(_SENSITIVE_STRING_RE, _OPAQUE_AUTH_TOKEN_RE),
    string_rules=(
        StringRedactionRule(
            "auth-header",
            _AUTH_HEADER_RE,
            lambda match: f"{match.group(1)}{REDACTED}",
        ),
        StringRedactionRule(
            "bearer-token",
            _BEARER_RE,
            lambda match: f"{match.group(1)}{REDACTED}",
        ),
        StringRedactionRule(
            "env-assignment",
            _ENV_ASSIGN_RE,
            lambda match: f"{match.group(1)}{match.group(2)}{match.group(3)}"
            f"{REDACTED}{match.group(5)}",
        ),
        StringRedactionRule(
            "key-value-secret",
            _KEY_VALUE_RE,
            lambda match: f"{match.group(1)}{match.group(2)}{match.group(3)}"
            f"{REDACTED}{match.group(5)}",
        ),
        StringRedactionRule(
            "secret-cli-flag",
            _SECRET_FLAG_RE,
            lambda match: f"{match.group(1)}{REDACTED}",
        ),
        StringRedactionRule(
            "url-secret-query",
            _URL_SECRET_QUERY_RE,
            lambda match: f"{match.group(1)}{REDACTED}",
        ),
        StringRedactionRule("hf-token", _HF_TOKEN_RE, REDACTED),
        StringRedactionRule("github-token", _GITHUB_TOKEN_RE, REDACTED),
        StringRedactionRule("opaque-auth-token", _OPAQUE_AUTH_TOKEN_RE, REDACTED),
        StringRedactionRule("mac-user-path", _MAC_USER_PATH_RE, r"\1[USER]"),
        StringRedactionRule("linux-user-path", _LINUX_USER_PATH_RE, r"\1[USER]"),
        StringRedactionRule(
            "windows-user-path",
            _WINDOWS_USER_PATH_RE,
            lambda match: f"{match.group(1)}[USER]",
        ),
        StringRedactionRule(
            "private-dataset-sample",
            _PRIVATE_DATASET_SAMPLE_RE,
            lambda match: f"{match.group(1)}{REDACTED_DATASET_ROWS}",
        ),
        StringRedactionRule(
            "private-dataset-rows",
            _PRIVATE_DATASET_ROWS_RE,
            lambda match: f"{match.group(1)}{REDACTED_DATASET_ROWS}",
        ),
    ),
    private_flags=frozenset(_PRIVATE_FLAGS),
    private_row_keys=frozenset(_PRIVATE_ROW_KEYS),
)


def redact_value(value: Any) -> RedactionResult:
    """Return a redacted copy of value without mutating the input."""

    return _redact_value(value, private_context=False)


def redact_string(value: str) -> RedactionResult:
    """Redact sensitive substrings from a standalone string."""

    return DEFAULT_REDACTION_POLICY.redact_string(value)


def _redact_value(value: Any, *, private_context: bool) -> RedactionResult:
    if isinstance(value, str):
        return redact_string(value)

    if isinstance(value, dict):
        current_private = private_context or _has_private_marker(value)
        redacted: dict[Any, Any] = {}
        status = REDACTION_NONE

        for key, child in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if DEFAULT_REDACTION_POLICY.is_secret_key(key_text):
                redacted[key] = REDACTED
                status = _combine_status(status, REDACTION_REDACTED)
                continue
            if current_private and DEFAULT_REDACTION_POLICY.is_private_row_key(
                key_lower
            ):
                redacted[key] = REDACTED_DATASET_ROWS
                status = _combine_status(status, REDACTION_REDACTED)
                continue

            child_result = _redact_value(child, private_context=current_private)
            redacted[key] = child_result.value
            status = _combine_status(status, child_result.status)

        return RedactionResult(redacted, status)

    if isinstance(value, list):
        redacted_items = []
        status = REDACTION_NONE
        for item in value:
            item_result = _redact_value(item, private_context=private_context)
            redacted_items.append(item_result.value)
            status = _combine_status(status, item_result.status)
        return RedactionResult(redacted_items, status)

    if isinstance(value, tuple):
        item_results = [
            _redact_value(item, private_context=private_context) for item in value
        ]
        status = REDACTION_NONE
        for item_result in item_results:
            status = _combine_status(status, item_result.status)
        return RedactionResult(tuple(item.value for item in item_results), status)

    return RedactionResult(value, REDACTION_NONE)


def _has_private_marker(value: dict[Any, Any]) -> bool:
    for key, child in value.items():
        if DEFAULT_REDACTION_POLICY.is_private_marker(str(key), child):
            return True
    return False


def _combine_status(left: str, right: str) -> str:
    if REDACTION_REDACTED in (left, right):
        return REDACTION_REDACTED
    if REDACTION_PARTIAL in (left, right):
        return REDACTION_PARTIAL
    return REDACTION_NONE
