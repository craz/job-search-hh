"""Unit tests for HttpApplyTransport POST boundary."""

from __future__ import annotations

import io
import json
from typing import Any
from urllib.error import HTTPError

import pytest

from job_search_hh.apply_transport import ApplyTransportError, HttpApplyTransport


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_http_apply_posts_negotiations(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:  # noqa: ARG001
        assert request.get_method() == "POST"
        assert request.full_url.endswith("/negotiations")
        body = request.data.decode("utf-8")
        assert "vacancy_id=1001" in body
        assert "resume_id=resume-1" in body
        return _FakeResponse(json.dumps({"id": "neg-99"}).encode("utf-8"))

    monkeypatch.setattr("job_search_hh.apply_transport.urllib.request.urlopen", fake_urlopen)
    transport = HttpApplyTransport("https://api.hh.ru", "ua", 5.0, "tok")
    result = transport.submit(
        {
            "live": True,
            "path": "/negotiations",
            "vacancy_external_id": "1001",
            "resume_id": "resume-1",
            "message": "hello",
            "body": {"vacancy_id": "1001", "resume_id": "resume-1", "message": "hello"},
        }
    )
    assert result["status"] == "submitted"
    assert result["negotiation_id"] == "neg-99"
    assert transport.write_attempted is True


def test_http_apply_maps_captcha_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float = 0) -> Any:  # noqa: ARG001
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=io.BytesIO(b'{"errors":[{"value":"captcha_required"}]}'),
        )

    monkeypatch.setattr("job_search_hh.apply_transport.urllib.request.urlopen", fake_urlopen)
    transport = HttpApplyTransport("https://api.hh.ru", "ua", 5.0, "tok")
    with pytest.raises(ApplyTransportError, match="captcha_or_auth_stop"):
        transport.submit(
            {
                "live": True,
                "path": "/negotiations",
                "vacancy_external_id": "1",
                "resume_id": "r",
                "message": "",
                "body": {"vacancy_id": "1", "resume_id": "r", "message": ""},
            }
        )
