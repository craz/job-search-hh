"""Unit tests for HH resume file download via visible «Скачать» action."""

from __future__ import annotations

import tempfile
from pathlib import Path

from job_search_hh.resume_file_download import (
    _sanitize_filename,
    _trigger_download_on_page,
)


class _FakeDownload:
    def __init__(self, *, filename: str, data: bytes) -> None:
        self.suggested_filename = filename
        self._data = data
        self.saved_path = None

    def save_as(self, path: str) -> None:
        self.saved_path = path
        with open(path, "wb") as handle:
            handle.write(self._data)


class _FakeLocator:
    def __init__(self, count: int = 1, *, download: _FakeDownload | None = None) -> None:
        self._count = count
        self._download = download

    def count(self) -> int:
        return self._count

    @property
    def first(self) -> _FakeLocator:
        return self

    def click(self, *, timeout: int) -> None:
        return None

    def filter(self, **_kwargs: object) -> _FakeLocator:
        return self

    def locator(self, _selector: str) -> _FakeLocator:
        if "resume-list-action-more" in _selector:
            return _FakeLocator(1)
        if "operations-list-download-resume-pdf" in _selector:
            return _FakeLocator(1, download=self._download)
        return _FakeLocator(0)

    def expect_download(self, *, timeout: int):
        download = self._download

        class _Manager:
            def __enter__(self):
                return self

            def __exit__(self, *args: object) -> None:
                return None

            @property
            def value(self) -> _FakeDownload:
                assert download is not None
                return download

        return _Manager()


class _FakePage:
    def __init__(self, download: _FakeDownload) -> None:
        self._download = download
        self._timeouts = 0

    def locator(self, selector: str) -> _FakeLocator:
        if selector.startswith('[data-qa^="resume "]'):
            return _FakeLocator(1, download=self._download)
        if "operations-list-download-resume-pdf" in selector:
            return _FakeLocator(1, download=self._download)
        if "operations-list-download-resume" in selector:
            return _FakeLocator(1, download=self._download)
        return _FakeLocator(0, download=self._download)

    def get_by_role(self, role: str, name: object) -> _FakeLocator:
        return _FakeLocator(0)

    def get_by_text(self, text: str, exact: bool = False) -> _FakeLocator:
        return _FakeLocator(0)

    def wait_for_timeout(self, _ms: int) -> None:
        return None

    def expect_download(self, *, timeout: int):
        return _FakeLocator(1, download=self._download).expect_download(timeout=timeout)


def test_trigger_download_captures_filename_mime_and_bytes(monkeypatch) -> None:
    fake = _FakeDownload(
        filename="Иванов Иван.pdf",
        data=b"%PDF-1.4",
    )
    page = _FakePage(fake)
    temp_root = Path(tempfile.mkdtemp(prefix="hh-resume-download-test-"))
    monkeypatch.setattr(
        "job_search_hh.resume_file_download.tempfile.mkdtemp",
        lambda **_kwargs: str(temp_root),
    )
    result = _trigger_download_on_page(page, external_resume_id="resume-1", timeout_ms=5_000)
    assert result["kind"] == "ok"
    assert result["original_filename"] == "Иванов Иван.pdf"
    assert result["mime_type"] == "application/pdf"
    assert result["size_bytes"] == len(b"%PDF-1.4")
    assert fake.saved_path is not None
    assert not temp_root.exists()


def test_sanitize_filename_strips_directory_segments() -> None:
    assert _sanitize_filename("subdir/evil.pdf") == "evil.pdf"
    assert _sanitize_filename("") == "resume"
