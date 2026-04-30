from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from backend.dataset_blobs import (
    DATASET_BLOB_CACHE_ROOT,
    DatasetBlobDigestError,
    dataset_blob_cache_path,
    dataset_blob_relative_path,
    normalize_sha256_digest,
    qualified_sha256_digest,
)


SHA256_HEX = "0123456789abcdef" * 4


def test_sha256_digest_normalization_accepts_bare_or_qualified_hex():
    assert normalize_sha256_digest(SHA256_HEX) == SHA256_HEX
    assert normalize_sha256_digest(f"sha256:{SHA256_HEX}") == SHA256_HEX
    assert normalize_sha256_digest(f"SHA256:{SHA256_HEX.upper()}") == SHA256_HEX
    assert normalize_sha256_digest(f"  sha256:{SHA256_HEX}  ") == SHA256_HEX
    assert qualified_sha256_digest(SHA256_HEX.upper()) == f"sha256:{SHA256_HEX}"


def test_blob_paths_use_stable_sha256_fanout_convention():
    assert dataset_blob_relative_path(SHA256_HEX) == PurePosixPath(
        "sha256",
        "01",
        "23",
        SHA256_HEX,
    )
    assert dataset_blob_cache_path(f"sha256:{SHA256_HEX}") == PurePosixPath(
        "~/.mlj/blobs",
        "sha256",
        "01",
        "23",
        SHA256_HEX,
    )
    assert dataset_blob_cache_path(SHA256_HEX) == dataset_blob_cache_path(
        f"sha256:{SHA256_HEX}"
    )


def test_blob_paths_are_pure_conventional_paths_without_home_expansion():
    cache_path = dataset_blob_cache_path(SHA256_HEX)

    assert DATASET_BLOB_CACHE_ROOT == PurePosixPath("~/.mlj/blobs")
    assert type(cache_path) is PurePosixPath
    assert str(cache_path).startswith("~/.mlj/blobs/sha256/")
    assert not cache_path.is_absolute()


@pytest.mark.parametrize(
    "digest",
    [
        "",
        "   ",
        "abc123",
        "sha256:abc123",
        "sha256:" + ("a" * 63),
        "sha256:" + ("a" * 65),
        "sha256:" + ("g" * 64),
        "sha1:" + ("a" * 40),
        "md5:" + ("a" * 32),
        "blake3:" + ("a" * 64),
        "a" * 40,
    ],
)
def test_rejects_weak_or_malformed_digests(digest):
    with pytest.raises(DatasetBlobDigestError):
        normalize_sha256_digest(digest)


def test_rejects_non_string_digest_values():
    with pytest.raises(TypeError, match="must be a string"):
        normalize_sha256_digest(None)  # type: ignore[arg-type]
