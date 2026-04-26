from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

REDACTED = "[REDACTED]"
REDACTED_DATASET_ROWS = "[REDACTED_DATASET_ROWS]"

REDACTION_NONE = "none"
REDACTION_PARTIAL = "partial"
REDACTION_REDACTED = "redacted"


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    status: str = REDACTION_NONE


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
_ENV_ASSIGN_RE = re.compile(
    r"(?i)\b(HF_TOKEN|GITHUB_TOKEN)\s*([=:])\s*"
    r"(['\"]?)([^'\"\s,;)}\]]+)(\3)"
)
_KEY_VALUE_RE = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]*(?:api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|auth[_-]?token|client[_-]?secret|secret|"
    r"password|passwd|private[_-]?key|github[_-]?token|hf[_-]?token)"
    r"[A-Za-z0-9_.-]*)\s*([:=])\s*(['\"]?)([^'\"\s,;)}\]]+)(\3)"
)
_URL_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&](?:token|access_token|auth_token|api_key|key|signature|sig)=)"
    r"([^&#\s]+)"
)
_HF_TOKEN_RE = re.compile(r"\bhf_[A-Za-z0-9_\-]{8,}\b")
_GITHUB_TOKEN_RE = re.compile(
    r"\b(github_pat_[A-Za-z0-9_]{20,}|gh[opsru]_[A-Za-z0-9_]{20,})\b"
)
_MAC_USER_PATH_RE = re.compile(r"(?<![\w.-])(/Users/)([^/\s:]+)")
_LINUX_USER_PATH_RE = re.compile(r"(?<![\w.-])(/home/)([^/\s:]+)")
_WINDOWS_USER_PATH_RE = re.compile(r"(?i)\b([A-Z]:\\Users\\)([^\\/\s]+)")
_PRIVATE_DATASET_SAMPLE_RE = re.compile(
    r"(?is)(private\s*[:=]\s*true.*?)(##\s*Sample Rows\b.*)"
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


def redact_value(value: Any) -> RedactionResult:
    """Return a redacted copy of value without mutating the input."""

    return _redact_value(value, private_context=False)


def redact_string(value: str) -> RedactionResult:
    """Redact sensitive substrings from a standalone string."""

    if _SENSITIVE_STRING_RE.fullmatch(value.strip()):
        return RedactionResult(REDACTED, REDACTION_REDACTED)

    redacted = value
    redacted = _BEARER_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
    redacted = _ENV_ASSIGN_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{match.group(3)}"
        f"{REDACTED}{match.group(5)}",
        redacted,
    )
    redacted = _KEY_VALUE_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{match.group(3)}"
        f"{REDACTED}{match.group(5)}",
        redacted,
    )
    redacted = _URL_SECRET_QUERY_RE.sub(
        lambda match: f"{match.group(1)}{REDACTED}", redacted
    )
    redacted = _HF_TOKEN_RE.sub(REDACTED, redacted)
    redacted = _GITHUB_TOKEN_RE.sub(REDACTED, redacted)
    redacted = _MAC_USER_PATH_RE.sub(r"\1[USER]", redacted)
    redacted = _LINUX_USER_PATH_RE.sub(r"\1[USER]", redacted)
    redacted = _WINDOWS_USER_PATH_RE.sub(r"\1[USER]", redacted)
    redacted = _PRIVATE_DATASET_SAMPLE_RE.sub(
        lambda match: f"{match.group(1)}{REDACTED_DATASET_ROWS}", redacted
    )

    if redacted == value:
        return RedactionResult(value, REDACTION_NONE)
    return RedactionResult(redacted, REDACTION_PARTIAL)


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
            if _SECRET_KEY_RE.search(key_text):
                redacted[key] = REDACTED
                status = _combine_status(status, REDACTION_REDACTED)
                continue
            if current_private and key_lower in _PRIVATE_ROW_KEYS:
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
        if str(key).lower() in _PRIVATE_FLAGS and child is True:
            return True
    return False


def _combine_status(left: str, right: str) -> str:
    if REDACTION_REDACTED in (left, right):
        return REDACTION_REDACTED
    if REDACTION_PARTIAL in (left, right):
        return REDACTION_PARTIAL
    return REDACTION_NONE
