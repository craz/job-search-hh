"""OAuth authorize URL, code exchange and safe token persistence for HH API reads."""

from __future__ import annotations

import json
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from job_search_hh.session import SessionPaths

AUTH_HOST = "https://hh.ru"


class OAuthError(Exception):
    """Stable OAuth/token storage failures without embedding secrets."""


@dataclass(frozen=True)
class OAuthSettings:
    """HH application credentials used only for token exchange."""

    client_id: str
    client_secret: str
    redirect_uri: str
    auth_host: str
    user_agent: str
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> OAuthSettings:
        return cls(
            client_id=os.getenv("JOB_SEARCH_HH_CLIENT_ID", os.getenv("HH_CLIENT_ID", "")).strip(),
            client_secret=os.getenv(
                "JOB_SEARCH_HH_CLIENT_SECRET", os.getenv("HH_CLIENT_SECRET", "")
            ).strip(),
            redirect_uri=os.getenv(
                "JOB_SEARCH_HH_REDIRECT_URI",
                os.getenv("HH_REDIRECT_URI", "http://127.0.0.1:8767/oauth/callback"),
            ).strip(),
            auth_host=os.getenv("JOB_SEARCH_HH_AUTH_HOST", AUTH_HOST).rstrip("/"),
            user_agent=os.getenv(
                "JOB_SEARCH_HH_USER_AGENT",
                "job-search-hh/0.1 (+https://github.com/local/job-search-hh; read-only)",
            ),
            timeout_seconds=float(os.getenv("JOB_SEARCH_HH_TIMEOUT_SECONDS", "20")),
        )

    def require_client(self) -> None:
        if not self.client_id:
            raise OAuthError("client_id_missing")
        if not self.client_secret:
            raise OAuthError("client_secret_missing")
        if not self.redirect_uri:
            raise OAuthError("redirect_uri_missing")


@dataclass(frozen=True)
class TokenRecord:
    """Persisted OAuth tokens; never serialize into public CLI envelopes."""

    access_token: str
    refresh_token: str | None
    expires_at: float | None
    token_type: str = "bearer"


def token_json_path(paths: SessionPaths | None = None) -> Path:
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    override = os.getenv("JOB_SEARCH_HH_TOKEN_FILE", "").strip()
    if override:
        return Path(override)
    return resolved.state_dir / "hh_token.json"


def plain_access_token_path(paths: SessionPaths | None = None) -> Path:
    resolved = paths or SessionPaths.from_env()
    resolved.ensure()
    override = os.getenv("JOB_SEARCH_HH_ACCESS_TOKEN_FILE", "").strip()
    if override:
        return Path(override)
    return resolved.state_dir / "access_token"


def _chmod_private(path: Path) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        return


def save_token_record(record: TokenRecord, paths: SessionPaths | None = None) -> Path:
    """Write token JSON with restrictive permissions; never log contents."""
    path = token_json_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": record.access_token,
        "refresh_token": record.refresh_token,
        "expires_at": record.expires_at,
        "token_type": record.token_type,
        "saved_at": time.time(),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    _chmod_private(path)
    # Keep legacy plain file in sync for older loaders; still mode 0600.
    plain = plain_access_token_path(paths)
    plain.write_text(record.access_token + "\n", encoding="utf-8")
    _chmod_private(plain)
    return path


def load_token_record(paths: SessionPaths | None = None) -> TokenRecord | None:
    path = token_json_path(paths)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    access = str(raw.get("access_token") or "").strip()
    if not access:
        return None
    expires_at = raw.get("expires_at")
    expires_value = float(expires_at) if isinstance(expires_at, (int, float)) else None
    refresh = raw.get("refresh_token")
    return TokenRecord(
        access_token=access,
        refresh_token=str(refresh).strip() if refresh else None,
        expires_at=expires_value,
        token_type=str(raw.get("token_type") or "bearer"),
    )


def clear_token_record(paths: SessionPaths | None = None) -> dict[str, Any]:
    removed = False
    for path in (token_json_path(paths), plain_access_token_path(paths)):
        if path.is_file():
            path.unlink()
            removed = True
    return {"access_token_present": False, "cleared": removed}


def token_status(paths: SessionPaths | None = None) -> dict[str, Any]:
    """Describe token presence without exposing secret material."""
    env_token = os.getenv("JOB_SEARCH_HH_ACCESS_TOKEN", "").strip()
    record = load_token_record(paths)
    plain = plain_access_token_path(paths)
    source = "missing"
    present = False
    expires_at: str | None = None
    expired = False
    refresh_present = False
    if env_token:
        source = "env"
        present = True
    elif record is not None:
        source = "token_file"
        present = True
        refresh_present = bool(record.refresh_token)
        if record.expires_at is not None:
            expires_at = (
                datetime.fromtimestamp(record.expires_at, tz=UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
            expired = time.time() >= record.expires_at
    elif plain.is_file() and plain.read_text(encoding="utf-8").strip():
        source = "plain_file"
        present = True
    return {
        "access_token_present": present,
        "refresh_token_present": refresh_present,
        "source": source,
        "expires_at": expires_at,
        "expired": expired,
        "token_file": str(token_json_path(paths)),
    }


def build_authorize_url(
    settings: OAuthSettings | None = None,
    *,
    state: str = "job-search-hh",
) -> dict[str, Any]:
    """Build the HH OAuth authorize URL; never includes client_secret."""
    cfg = settings or OAuthSettings.from_env()
    if not cfg.client_id:
        raise OAuthError("client_id_missing")
    if not cfg.redirect_uri:
        raise OAuthError("redirect_uri_missing")
    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": cfg.client_id,
            "redirect_uri": cfg.redirect_uri,
            "state": state,
        }
    )
    return {
        "authorize_url": f"{cfg.auth_host}/oauth/authorize?{params}",
        "redirect_uri": cfg.redirect_uri,
        "state": state,
        "client_id_present": True,
        "client_secret_present": bool(cfg.client_secret),
    }


def _post_token_form(settings: OAuthSettings, form: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(
        f"{settings.auth_host}/oauth/token",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise OAuthError(f"http_{error.code}") from error
    except (OSError, urllib.error.URLError, ValueError) as error:
        raise OAuthError("token_exchange_failed") from error
    if not isinstance(payload, dict) or not str(payload.get("access_token") or "").strip():
        raise OAuthError("invalid_token_response")
    return payload


def token_record_from_oauth_payload(payload: dict[str, Any]) -> TokenRecord:
    expires_in = payload.get("expires_in")
    expires_at = time.time() + int(expires_in) if expires_in is not None else None
    refresh = payload.get("refresh_token")
    return TokenRecord(
        access_token=str(payload["access_token"]).strip(),
        refresh_token=str(refresh).strip() if refresh else None,
        expires_at=float(expires_at) if expires_at is not None else None,
        token_type=str(payload.get("token_type") or "bearer"),
    )


def exchange_authorization_code(
    code: str,
    *,
    paths: SessionPaths | None = None,
    settings: OAuthSettings | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code and persist tokens without returning secrets."""
    cleaned = code.strip()
    if not cleaned:
        raise OAuthError("authorization_code_missing")
    cfg = settings or OAuthSettings.from_env()
    cfg.require_client()
    payload = _post_token_form(
        cfg,
        {
            "grant_type": "authorization_code",
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "code": cleaned,
            "redirect_uri": cfg.redirect_uri,
        },
    )
    record = token_record_from_oauth_payload(payload)
    save_token_record(record, paths)
    status = token_status(paths)
    status["stored"] = True
    status["grant"] = "authorization_code"
    return status


def set_access_token(
    access_token: str,
    *,
    paths: SessionPaths | None = None,
    refresh_token: str | None = None,
    expires_in: int | None = None,
) -> dict[str, Any]:
    """Persist an operator-supplied access token from a file/stdin (not CLI JSON)."""
    cleaned = access_token.strip()
    if not cleaned:
        raise OAuthError("access_token_missing")
    expires_at = time.time() + expires_in if expires_in is not None else None
    save_token_record(
        TokenRecord(
            access_token=cleaned,
            refresh_token=refresh_token.strip() if refresh_token else None,
            expires_at=expires_at,
        ),
        paths,
    )
    status = token_status(paths)
    status["stored"] = True
    status["grant"] = "manual"
    return status


def refresh_token_record(
    paths: SessionPaths | None = None,
    settings: OAuthSettings | None = None,
) -> TokenRecord:
    """Refresh an expired/near-expiry token using the stored refresh_token."""
    current = load_token_record(paths)
    if current is None or not current.refresh_token:
        raise OAuthError("refresh_token_missing")
    cfg = settings or OAuthSettings.from_env()
    cfg.require_client()
    payload = _post_token_form(
        cfg,
        {
            "grant_type": "refresh_token",
            "refresh_token": current.refresh_token,
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
        },
    )
    record = token_record_from_oauth_payload(payload)
    save_token_record(record, paths)
    return record
