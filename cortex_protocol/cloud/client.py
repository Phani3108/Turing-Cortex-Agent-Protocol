"""Cortex Cloud HTTP client.

Small, deliberately boring: urllib only, JSON in/out, OAuth device-flow
for interactive login, PAT/OIDC token for CI. The SaaS control plane
defined in Section F of the 0.5 plan will sit behind this interface; we
ship the wire protocol now so the OSS side is ready the day the backend
goes live.

Token storage:
  ~/.cortex-protocol/credentials.json  mode 0600 on POSIX
  Schema:
    {
      "email": "user@example.com",
      "workspace": "ws_abc",
      "access_token": "...",
      "token_type": "Bearer",
      "expires_at": "2026-...-...",
      "cloud_url": "https://cloud.cortexprotocol.dev"
    }

If `CORTEX_CLOUD_TOKEN` is set in the env, it wins over the stored
credentials — CI runs never touch disk.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ..platform import credentials_path, ensure_dir


DEFAULT_CLOUD_URL = "https://cloud.cortexprotocol.dev"
DEVICE_CODE_PATH = "/oauth/device/code"
DEVICE_TOKEN_PATH = "/oauth/device/token"
WHOAMI_PATH = "/v1/me"


class CloudAuthError(Exception):
    """Authentication / credential-related failures."""


class CloudHTTPError(Exception):
    """Non-2xx response from the Cloud API."""

    def __init__(self, message: str, *, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def default_cloud_url() -> str:
    return os.environ.get("CORTEX_CLOUD_URL", DEFAULT_CLOUD_URL).rstrip("/")


@dataclass
class Credentials:
    email: str
    workspace: str
    access_token: str
    token_type: str = "Bearer"
    expires_at: str = ""
    cloud_url: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "Credentials":
        return cls(
            email=data.get("email", ""),
            workspace=data.get("workspace", ""),
            access_token=data.get("access_token", ""),
            token_type=data.get("token_type", "Bearer"),
            expires_at=data.get("expires_at", ""),
            cloud_url=data.get("cloud_url", ""),
        )


def load_credentials(path: Optional[Path] = None) -> Optional[Credentials]:
    p = path or credentials_path()
    if not p.exists():
        return None
    try:
        return Credentials.from_dict(json.loads(p.read_text()))
    except (json.JSONDecodeError, OSError):
        return None


def save_credentials(creds: Credentials, path: Optional[Path] = None) -> Path:
    p = path or credentials_path()
    ensure_dir(p.parent)
    p.write_text(creds.to_json())
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p


def remove_credentials(path: Optional[Path] = None) -> bool:
    p = path or credentials_path()
    if not p.exists():
        return False
    p.unlink()
    return True


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------

def _request(method: str, url: str, *,
             headers: Optional[dict[str, str]] = None,
             body: Any = None,
             timeout: float = 30.0) -> tuple[int, dict, Any]:
    """Low-level HTTP roundtrip. Never raises for 4xx/5xx — returns the tuple.

    Higher layers (CloudClient.request) decide when to raise on status.
    Keeping this transport non-raising lets OAuth flows branch on expected
    4xx responses like 428 authorization_pending without try/except noise.
    """
    headers = dict(headers or {})
    data: Optional[bytes] = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json")
    headers.setdefault("User-Agent", _user_agent())

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
            return resp.status, dict(resp.headers), _parse_json_or_text(raw)
    except urllib.error.HTTPError as e:
        raw = e.read() or b""
        return e.code, dict(e.headers or {}), _parse_json_or_text(raw)
    except urllib.error.URLError as e:  # pragma: no cover — network
        raise CloudHTTPError(f"{method} {url} -> {e.reason}", status=0) from None


def _parse_json_or_text(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw.decode("utf-8", errors="replace")


def _user_agent() -> str:
    from .. import __version__
    return f"cortex-protocol/{__version__} (+https://cortexprotocol.dev)"


# ---------------------------------------------------------------------------
# CloudClient
# ---------------------------------------------------------------------------

class CloudClient:
    """Authenticated (or anonymous) client for Cortex Cloud HTTP APIs.

    Primary entry points:
      - `login_device_flow()`  interactive OAuth device flow
      - `whoami()`             current user/org/workspace
      - `request(method, path, body)` generic JSON request with auth header

    Callers that need specialized adapters (audit exporter, registry)
    build on top of `request` so transport concerns stay here.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        token: Optional[str] = None,
        credentials: Optional[Credentials] = None,
        http: Optional[Callable] = None,
    ):
        self._base = (base_url or default_cloud_url()).rstrip("/")
        self._token = token or os.environ.get("CORTEX_CLOUD_TOKEN") or (
            credentials.access_token if credentials else None
        )
        self._credentials = credentials
        # Injected transport for tests; defaults to the real urllib wrapper.
        self._http = http or _request

    @classmethod
    def from_environment(cls) -> "CloudClient":
        """Construct from env vars + disk-stored credentials."""
        creds = load_credentials()
        token = os.environ.get("CORTEX_CLOUD_TOKEN")
        return cls(
            base_url=default_cloud_url(),
            token=token,
            credentials=creds,
        )

    @property
    def base_url(self) -> str:
        return self._base

    @property
    def is_authenticated(self) -> bool:
        return bool(self._token)

    def _headers(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        h = dict(extra or {})
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def request(self, method: str, path: str, *,
                body: Any = None,
                headers: Optional[dict[str, str]] = None) -> Any:
        url = f"{self._base}{path if path.startswith('/') else '/' + path}"
        status, _resp_headers, payload = self._http(
            method, url, headers=self._headers(headers), body=body,
        )
        if status >= 400:
            raise CloudHTTPError(
                f"{method} {path} -> {status}", status=status,
                body=str(payload),
            )
        return payload

    def whoami(self) -> dict:
        if not self.is_authenticated:
            raise CloudAuthError("Not logged in. Run `cortex-protocol login`.")
        return self.request("GET", WHOAMI_PATH)

    # -----------------------------------------------------------------
    # OAuth device-flow
    # -----------------------------------------------------------------

    def login_device_flow(
        self,
        *,
        client_id: str = "cortex-cli",
        scope: str = "workspace:read workspace:write audit:write",
        prompt: Callable[[str, str], None] = None,
        poll_interval: float = 5.0,
        max_wait_seconds: int = 600,
        workspace: Optional[str] = None,
    ) -> Credentials:
        """Run the OAuth 2.0 device-authorization flow.

        1. POST to /oauth/device/code → get user_code, verification_uri, device_code
        2. Show the user the verification URL + code.
        3. Poll /oauth/device/token until the user approves or we time out.
        4. Persist credentials and return them.

        The `prompt` callback receives (verification_url, user_code). The
        default behavior prints the URL and tries to open it in a browser.
        """
        if prompt is None:
            prompt = _default_prompt

        body = {"client_id": client_id, "scope": scope}
        if workspace:
            body["workspace"] = workspace

        start = self._http("POST", f"{self._base}{DEVICE_CODE_PATH}", body=body)
        status, _h, payload = start
        if status >= 400 or not isinstance(payload, dict):
            raise CloudAuthError(
                f"Device authorization start failed ({status}): {payload}"
            )

        device_code = payload["device_code"]
        user_code = payload["user_code"]
        verification_uri = payload.get("verification_uri_complete") \
            or payload["verification_uri"]
        prompt(verification_uri, user_code)

        deadline = time.monotonic() + max_wait_seconds
        interval = float(payload.get("interval") or poll_interval)

        while time.monotonic() < deadline:
            time.sleep(interval)
            status, _h, token_payload = self._http(
                "POST", f"{self._base}{DEVICE_TOKEN_PATH}",
                body={"device_code": device_code, "client_id": client_id},
            )
            if status == 200 and isinstance(token_payload, dict) \
                    and "access_token" in token_payload:
                creds = Credentials(
                    email=token_payload.get("email", ""),
                    workspace=token_payload.get("workspace", workspace or ""),
                    access_token=token_payload["access_token"],
                    token_type=token_payload.get("token_type", "Bearer"),
                    expires_at=token_payload.get("expires_at", ""),
                    cloud_url=self._base,
                )
                save_credentials(creds)
                self._credentials = creds
                self._token = creds.access_token
                return creds

            # 428 "authorization_pending" is the normal pre-approval state.
            if isinstance(token_payload, dict) and token_payload.get("error") == "slow_down":
                interval = min(interval * 2, 30.0)
                continue
            if isinstance(token_payload, dict) and token_payload.get("error") not in (None, "authorization_pending"):
                raise CloudAuthError(
                    f"Device token exchange failed: {token_payload.get('error')}"
                )

        raise CloudAuthError(
            f"Timed out after {max_wait_seconds}s waiting for device approval."
        )


def _default_prompt(url: str, user_code: str) -> None:
    print("\n  To finish login, open this URL and enter the code:")
    print(f"    {url}")
    print(f"    code: {user_code}\n")
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass
