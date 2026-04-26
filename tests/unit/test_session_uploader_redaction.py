from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

from agent.core import session_uploader
from agent.core.redaction import REDACTED_DATASET_ROWS


HF_TOKEN = "hf_rawsessiontoken123456789"
GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz123456"
BEARER_TOKEN = "hf_bearerrawtoken123456789"
PRIVATE_URL_TOKEN = "hf_privateurltoken123456789"
LOCAL_USER_PATH = "/Users/alice/private/project"
PRIVATE_ROW_TEXT = "patient secret private row"


def test_upload_session_redacts_legacy_json_before_jsonl_payload(
    monkeypatch, tmp_path
):
    uploads: list[dict[str, Any]] = []
    _stub_huggingface_api(monkeypatch, uploads)
    monkeypatch.setattr(
        session_uploader, "_SESSION_TOKEN", "hf_uploadcredential123456789"
    )
    session_file = _write_raw_session(tmp_path / "session_legacy.json", "pending")

    assert session_uploader.upload_session_as_file(str(session_file), "owner/sessions")

    assert len(uploads) == 1
    uploaded_row = uploads[0]["row"]
    _assert_no_raw_sensitive_payload(uploaded_row)

    messages = json.loads(uploaded_row["messages"])
    events = json.loads(uploaded_row["events"])
    assert "HF_TOKEN=[REDACTED]" in messages[0]["content"]
    assert "GITHUB_TOKEN=[REDACTED]" in messages[0]["content"]
    assert "Authorization: Bearer [REDACTED]" in messages[0]["content"]
    assert "token=[REDACTED]" in messages[0]["content"]
    assert "/Users/[USER]/private/project" in messages[0]["content"]
    assert events[0]["data"]["rows"] == REDACTED_DATASET_ROWS

    rewritten = json.loads(session_file.read_text())
    assert rewritten["upload_status"] == "success"
    _assert_no_raw_sensitive_payload(rewritten)


def test_retry_failed_uploads_redacts_pending_and_failed_legacy_logs(
    monkeypatch, tmp_path
):
    uploads: list[dict[str, Any]] = []
    _stub_huggingface_api(monkeypatch, uploads)
    monkeypatch.setattr(
        session_uploader, "_SESSION_TOKEN", "hf_uploadcredential123456789"
    )
    _write_raw_session(tmp_path / "session_pending.json", "pending")
    _write_raw_session(tmp_path / "session_failed.json", "failed")
    _write_raw_session(tmp_path / "session_success.json", "success")

    session_uploader.retry_failed_uploads(str(tmp_path), "owner/sessions")

    assert sorted(upload["repo_path"] for upload in uploads) == [
        "sessions/2026-04-26/session-failed.jsonl",
        "sessions/2026-04-26/session-pending.jsonl",
    ]
    for upload in uploads:
        _assert_no_raw_sensitive_payload(upload["row"])


def _stub_huggingface_api(monkeypatch, uploads: list[dict[str, Any]]) -> None:
    class FakeHfApi:
        def create_repo(self, **_kwargs):
            return None

        def upload_file(
            self,
            *,
            path_or_fileobj,
            path_in_repo,
            repo_id,
            repo_type,
            token,
            commit_message,
        ):
            uploads.append(
                {
                    "row": json.loads(Path(path_or_fileobj).read_text()),
                    "repo_path": path_in_repo,
                    "repo_id": repo_id,
                    "repo_type": repo_type,
                    "token": token,
                    "commit_message": commit_message,
                }
            )

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        types.SimpleNamespace(HfApi=FakeHfApi),
    )


def _write_raw_session(path: Path, upload_status: str) -> Path:
    session_id = f"session-{path.stem.removeprefix('session_')}"
    path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "session_start_time": "2026-04-26T10:00:00",
                "session_end_time": "2026-04-26T10:02:00",
                "model_name": "test/model",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"HF_TOKEN={HF_TOKEN} "
                            f"GITHUB_TOKEN={GITHUB_TOKEN} "
                            f"Authorization: Bearer {BEARER_TOKEN} "
                            "https://huggingface.co/datasets/me/private"
                            f"?token={PRIVATE_URL_TOKEN} "
                            f"{LOCAL_USER_PATH}"
                        ),
                    }
                ],
                "events": [
                    {
                        "event_type": "tool_output",
                        "data": {
                            "private": True,
                            "rows": [{"text": PRIVATE_ROW_TEXT}],
                            "output": (
                                "private: true\n"
                                f"## Sample Rows\n{PRIVATE_ROW_TEXT}"
                            ),
                        },
                    }
                ],
                "upload_status": upload_status,
                "upload_url": None,
            }
        )
    )
    return path


def _assert_no_raw_sensitive_payload(payload: Any) -> None:
    serialized = json.dumps(payload)
    for raw_value in (
        HF_TOKEN,
        GITHUB_TOKEN,
        BEARER_TOKEN,
        PRIVATE_URL_TOKEN,
        LOCAL_USER_PATH,
        PRIVATE_ROW_TEXT,
    ):
        assert raw_value not in serialized
