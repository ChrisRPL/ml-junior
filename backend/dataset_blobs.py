from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Final


DATASET_BLOB_ALGORITHM: Final = "sha256"
DATASET_BLOB_CACHE_ROOT: Final = PurePosixPath("~/.mlj/blobs")
SHA256_HEX_LENGTH: Final = 64

_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-fA-F]{64}$")


class DatasetBlobDigestError(ValueError):
    """Raised when a dataset blob digest cannot identify a sha256 blob."""


def normalize_sha256_digest(digest: str) -> str:
    """Return the lowercase 64-character sha256 hex digest.

    Accepts bare hex or ``sha256:<hex>`` values. The helper is intentionally
    pure: it validates only the digest string and never probes local cache
    state.
    """

    if not isinstance(digest, str):
        raise TypeError("sha256 digest must be a string")

    value = digest.strip()
    if not value:
        raise DatasetBlobDigestError("sha256 digest must not be empty")

    algorithm, separator, payload = value.partition(":")
    if separator:
        if algorithm.lower() != DATASET_BLOB_ALGORITHM:
            raise DatasetBlobDigestError(
                f"unsupported dataset blob digest algorithm: {algorithm}"
            )
        value = payload

    if len(value) != SHA256_HEX_LENGTH:
        raise DatasetBlobDigestError(
            "sha256 digest must be exactly 64 hexadecimal characters"
        )

    if _SHA256_HEX_RE.fullmatch(value) is None:
        raise DatasetBlobDigestError(
            "sha256 digest must contain only hexadecimal characters"
        )

    return value.lower()


def qualified_sha256_digest(digest: str) -> str:
    """Return the canonical ``sha256:<hex>`` digest label."""

    return f"{DATASET_BLOB_ALGORITHM}:{normalize_sha256_digest(digest)}"


def dataset_blob_relative_path(digest: str) -> PurePosixPath:
    """Return the cache-relative content-addressed blob path.

    The convention fans out on the first four digest characters:
    ``sha256/ab/cd/<digest>``.
    """

    value = normalize_sha256_digest(digest)
    return PurePosixPath(DATASET_BLOB_ALGORITHM, value[:2], value[2:4], value)


def dataset_blob_cache_path(digest: str) -> PurePosixPath:
    """Return the conventional ``~/.mlj/blobs`` blob path without expanding it."""

    return DATASET_BLOB_CACHE_ROOT / dataset_blob_relative_path(digest)


__all__ = [
    "DATASET_BLOB_ALGORITHM",
    "DATASET_BLOB_CACHE_ROOT",
    "DatasetBlobDigestError",
    "SHA256_HEX_LENGTH",
    "dataset_blob_cache_path",
    "dataset_blob_relative_path",
    "normalize_sha256_digest",
    "qualified_sha256_digest",
]
