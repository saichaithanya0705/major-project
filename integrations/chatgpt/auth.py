"""
Sign in with ChatGPT (ChatGPT plan usage for open-source apps).

Implements OpenAI's documented flow for locally hosted open-source apps
(https://developers.openai.com/siwc/token-sharing-open-source):

1. Persist a stable, opaque host ID (``urn:uuid:...``) before the first sign-in.
2. Open the system browser at the authorize endpoint with PKCE, ``state``,
   ``nonce``, and either ``client_id=dynamic_agent_client`` (first sign-in,
   with ``agent_name_hint``) or the client ID issued at registration.
3. Receive the code on a ``http://127.0.0.1:<port>/auth/callback`` listener,
   exchange it (no client secret), validate the ID token against OpenAI's
   JWKS, and require the ``chatgpt.tokens.use.direct`` scope.
4. Store credentials in an owner-only file, refresh near expiry (rotating
   refresh tokens, serialized), and revoke on sign-out.

Jarvis never reads another app's credentials (for example Codex CLI's).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

import requests

APP_NAME = "Jarvis"
DEFAULT_ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
DYNAMIC_CLIENT_ID = "dynamic_agent_client"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
CALLBACK_PATH = "/auth/callback"
DEFAULT_CALLBACK_PORT = 1455
REFRESH_MARGIN_SECONDS = 300
SIGN_IN_TIMEOUT_SECONDS = 300

_refresh_lock = threading.Lock()


class ChatGPTAuthError(RuntimeError):
    pass


class NotSignedInError(ChatGPTAuthError):
    pass


class TokenRequestError(ChatGPTAuthError):
    def __init__(self, status: int, error: str) -> None:
        super().__init__(f"Token request failed: HTTP {status}{f' {error}' if error else ''}")
        self.status = status
        self.error = error

    @property
    def session_is_dead(self) -> bool:
        """invalid_grant and 4xx (except 429) mean the refresh token is no longer usable; 5xx is temporary."""
        return self.error == "invalid_grant" or (400 <= self.status < 500 and self.status != 429)


def issuer() -> str:
    # Overridable only so tests can run against a local identity server.
    return (os.getenv("JARVIS_CHATGPT_ISSUER") or DEFAULT_ISSUER).rstrip("/")


def config_dir() -> Path:
    configured = os.getenv("JARVIS_CHATGPT_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".jarvis" / "chatgpt"


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


def registration_path() -> Path:
    """The issued client ID and account identity, kept across sign-outs for reauthorization."""
    return config_dir() / "registration.json"


def _write_private(path: Path, payload: dict[str, Any]) -> None:
    """Atomic write readable only by the current user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def host_id() -> str:
    """This machine's stable, opaque agent host ID, created once before the first sign-in."""
    path = config_dir() / "host_id"
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = f"urn:uuid:{uuid.uuid4()}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return value


def load_credentials() -> dict[str, Any] | None:
    path = credentials_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("access_token") else None


def load_registration() -> dict[str, Any] | None:
    path = registration_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("client_id") else None


def is_signed_in() -> bool:
    credentials = load_credentials()
    return bool(credentials and PLAN_SCOPE in credentials.get("scopes", []))


def _discovery() -> dict[str, Any]:
    response = requests.get(f"{issuer()}/.well-known/openid-configuration", timeout=20)
    response.raise_for_status()
    return response.json()


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
    host: str,
    id_token_hint: str | None = None,
    login_hint: str | None = None,
) -> str:
    params = {
        "client_id": client_id,
        "ext_agent_host_id": host,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }
    if client_id == DYNAMIC_CLIENT_ID:
        params["agent_name_hint"] = APP_NAME
    else:
        if id_token_hint:
            params["id_token_hint"] = id_token_hint
        if login_hint:
            params["login_hint"] = login_hint
    return f"{issuer()}/api/accounts/authorize?{urlencode(params)}"


class _CallbackServer(HTTPServer):
    result: dict[str, str] | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        self.server.result = {key: values[0] for key, values in parse_qs(parsed.query).items()}  # type: ignore[attr-defined]
        body = b"<html><body><h2>Jarvis is connected.</h2><p>You can close this tab.</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_callback_server(preferred_port: int) -> _CallbackServer:
    for port in (preferred_port, 0):
        try:
            return _CallbackServer(("127.0.0.1", port), _CallbackHandler)
        except OSError:
            continue
    raise ChatGPTAuthError("Could not open a local port for the sign-in callback.")


def _validate_id_token(id_token: str, *, client_id: str, nonce: str, jwks_uri: str) -> dict[str, Any]:
    import jwt  # Only needed at sign-in, so Jarvis still starts if PyJWT is not installed yet.

    signing_key = jwt.PyJWKClient(jwks_uri).get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=client_id,
        issuer=issuer(),
        options={"require": ["exp", "iat", "sub"]},
    )
    if claims.get("nonce") != nonce:
        raise ChatGPTAuthError("ID token nonce does not match this sign-in attempt.")
    return claims


def _token_request(form: dict[str, str]) -> dict[str, Any]:
    response = requests.post(f"{issuer()}/api/accounts/oauth/token", data=form, timeout=30)
    if response.status_code >= 400:
        try:
            error = str(response.json().get("error", ""))
        except ValueError:
            error = ""
        raise TokenRequestError(response.status_code, error)
    return response.json()


def _credential_record(tokens: dict[str, Any], claims: dict[str, Any], *, client_id: str, host: str) -> dict[str, Any]:
    now = int(time.time())
    return {
        "email": claims.get("email", ""),
        "issuer": issuer(),
        "subject": claims["sub"],
        "client_id": client_id,
        "ext_agent_host_id": host,
        "id_token": tokens["id_token"],
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "token_type": tokens.get("token_type", "Bearer"),
        "expires_in": int(tokens.get("expires_in", 3600)),
        "expires_at": now + int(tokens.get("expires_in", 3600)),
        "scopes": sorted(str(tokens.get("scope", "")).split()),
        "signed_in_at": now,
        "saved_at": now,
    }


def sign_in(
    *,
    open_browser: Callable[[str], Any] = webbrowser.open,
    preferred_port: int = DEFAULT_CALLBACK_PORT,
    timeout_seconds: float = SIGN_IN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the browser sign-in and return the saved credential record."""
    previous = load_credentials()
    registration = load_registration()
    client_id = registration["client_id"] if registration else DYNAMIC_CLIENT_ID
    host = host_id()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    discovery = _discovery()

    server = _start_callback_server(preferred_port)
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}{CALLBACK_PATH}"
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        open_browser(
            authorize_url(
                client_id=client_id,
                redirect_uri=redirect_uri,
                state=state,
                nonce=nonce,
                code_challenge=challenge,
                host=host,
                id_token_hint=previous.get("id_token") if previous else None,
                login_hint=registration.get("email") if registration else None,
            )
        )
        deadline = time.monotonic() + timeout_seconds
        while server.result is None and time.monotonic() < deadline:
            time.sleep(0.1)
        result = server.result
    finally:
        server.shutdown()
        server.server_close()

    if result is None:
        raise ChatGPTAuthError("Sign-in timed out before the browser returned to Jarvis.")
    if result.get("state") != state:
        raise ChatGPTAuthError("Sign-in response did not match this attempt (state mismatch).")
    if result.get("error"):
        if result["error"] == "access_denied":
            raise ChatGPTAuthError("Sign-in was declined, so Jarvis cannot use your ChatGPT plan.")
        raise ChatGPTAuthError(f"Sign-in failed: {result['error']}")
    issued = result.get("client_id")
    if client_id == DYNAMIC_CLIENT_ID:
        if not issued:
            raise ChatGPTAuthError("Registration did not return a client ID; please sign in again.")
        client_id = issued
    elif issued and issued != client_id:
        raise ChatGPTAuthError("Sign-in returned a different client ID than this account's registration.")

    tokens = _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": result.get("code", ""),
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "resource": RESOURCE,
        }
    )
    claims = _validate_id_token(tokens["id_token"], client_id=client_id, nonce=nonce, jwks_uri=discovery["jwks_uri"])
    if registration and registration.get("subject") not in (None, claims["sub"]):
        raise ChatGPTAuthError("Signed in as a different ChatGPT account than the one this Jarvis registered.")
    if PLAN_SCOPE not in str(tokens.get("scope", "")).split():
        raise ChatGPTAuthError("ChatGPT plan usage was not granted. Sign in again and allow plan usage.")
    record = _credential_record(tokens, claims, client_id=client_id, host=host)
    _write_private(
        registration_path(),
        {key: record[key] for key in ("issuer", "client_id", "subject", "email", "ext_agent_host_id")},
    )
    _write_private(credentials_path(), record)
    return record


def access_token(*, force_refresh: bool = False) -> str:
    """A valid access token, refreshing it first when it is about to expire (or when forced after a 401)."""
    with _refresh_lock:
        credentials = load_credentials()
        if credentials is None or PLAN_SCOPE not in credentials.get("scopes", []):
            raise NotSignedInError("Not signed in with ChatGPT. Run: python -m integrations.chatgpt login")
        if not force_refresh and int(credentials.get("expires_at", 0)) - REFRESH_MARGIN_SECONDS > time.time():
            return str(credentials["access_token"])
        if not credentials.get("refresh_token"):
            raise NotSignedInError("ChatGPT session expired. Run: python -m integrations.chatgpt login")
        try:
            tokens = _token_request(
                {
                    "grant_type": "refresh_token",
                    "client_id": credentials["client_id"],
                    "refresh_token": credentials["refresh_token"],
                    "resource": RESOURCE,
                }
            )
        except TokenRequestError as exc:
            if exc.session_is_dead:
                raise NotSignedInError(
                    f"ChatGPT session ended ({exc}). Run: python -m integrations.chatgpt login"
                ) from exc
            raise ChatGPTAuthError(f"Could not renew the ChatGPT session right now ({exc}); try again shortly.") from exc
        now = int(time.time())
        credentials.update(
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token") or credentials["refresh_token"],
            expires_in=int(tokens.get("expires_in", 3600)),
            expires_at=now + int(tokens.get("expires_in", 3600)),
            scopes=sorted(str(tokens.get("scope", "")).split()) or credentials["scopes"],
            saved_at=now,
        )
        if tokens.get("id_token"):
            credentials["id_token"] = tokens["id_token"]
        _write_private(credentials_path(), credentials)
        return str(credentials["access_token"])


def sign_out() -> bool:
    """
    Revoke the session remotely when possible and delete local tokens. Returns True if revoked.

    The registration (issued client ID) is kept so the next sign-in reauthorizes the same client.
    """
    credentials = load_credentials()
    revoked = False
    if credentials and credentials.get("refresh_token"):
        try:
            endpoint = _discovery()["revocation_endpoint"]
            response = requests.post(
                endpoint,
                data={
                    "token": credentials["refresh_token"],
                    "token_type_hint": "refresh_token",
                    "client_id": credentials["client_id"],
                },
                timeout=20,
            )
            revoked = response.status_code == 200
        except (requests.RequestException, KeyError, ValueError):
            revoked = False
    credentials_path().unlink(missing_ok=True)
    return revoked
