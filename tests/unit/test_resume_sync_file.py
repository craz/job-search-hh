"""Unit tests for resume sync file attachment behavior."""

from __future__ import annotations

from job_search_hh.resume_sync import sync_resume_content


def test_sync_reports_file_failure_without_failing_json_ingest() -> None:
    def fake_reader(_external_id: str, *_args, **_kwargs):
        return {
            "status": "available",
            "code": "ready",
            "transport": "browser_readonly",
            "extractor_version": "test",
            "captured_at": "2026-08-28T00:40:00Z",
            "content": {"title": "Engineer", "about": "About"},
        }

    class FakeCore:
        def create_resume_version(self, payload: dict) -> dict:
            return {
                "created": False,
                "resume_version": {
                    "id": "c39fa10d-1ba2-4bd7-978d-4256987163d4",
                    "content_hash": "abc",
                },
                "candidate_context": {"resume_content": {"content_state": "synced"}},
            }

        def create_resume_artifact(self, *_args, **_kwargs) -> dict:
            raise AssertionError("artifact should not be uploaded when download fails")

    def fake_downloader(_external_id: str) -> dict:
        return {"ok": False, "status": "unavailable", "code": "download_menu_missing"}

    result = sync_resume_content(
        external_resume_id="resume-1",
        content_reader=fake_reader,
        file_downloader=fake_downloader,
        core=FakeCore(),
    )
    assert result["ok"] is True
    assert result["ingest"]["ok"] is True
    assert result["file"]["ok"] is False


def test_sync_stores_file_when_download_succeeds() -> None:
    def fake_reader(_external_id: str, *_args, **_kwargs):
        return {
            "status": "available",
            "code": "ready",
            "transport": "browser_readonly",
            "extractor_version": "test",
            "captured_at": "2026-08-28T00:40:00Z",
            "content": {"title": "Engineer", "about": "About"},
        }

    class FakeCore:
        def create_resume_version(self, payload: dict) -> dict:
            return {
                "created": False,
                "resume_version": {
                    "id": "c39fa10d-1ba2-4bd7-978d-4256987163d4",
                    "content_hash": "abc",
                },
                "candidate_context": {"resume_content": {"content_state": "synced"}},
            }

        def create_resume_artifact(self, version_id: str, **kwargs) -> dict:
            assert version_id == "c39fa10d-1ba2-4bd7-978d-4256987163d4"
            assert kwargs["data"] == b"%PDF-1.4"
            assert kwargs["mime_type"] == "application/pdf"
            return {
                "created": True,
                "artifact": {"id": "artifact-1"},
                "candidate_context": {
                    "resume_file": {
                        "artifact_id": "artifact-1",
                        "format_label": "PDF",
                    }
                },
            }

    def fake_downloader(_external_id: str) -> dict:
        return {
            "ok": True,
            "data": b"%PDF-1.4",
            "mime_type": "application/pdf",
            "original_filename": "resume.pdf",
            "size_bytes": 8,
            "captured_at": "2026-08-28T00:40:00Z",
        }

    result = sync_resume_content(
        external_resume_id="resume-1",
        content_reader=fake_reader,
        file_downloader=fake_downloader,
        core=FakeCore(),
    )
    assert result["ok"] is True
    assert result["file"]["ok"] is True
    assert result["file"]["artifact_id"] == "artifact-1"
    assert result["candidate_context"]["resume_file"]["format_label"] == "PDF"
