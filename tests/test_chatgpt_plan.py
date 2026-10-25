"""
Sign in with ChatGPT and plan inference, against a local fake of OpenAI's
identity server (RS256 ID tokens, JWKS, token, revocation) and Responses API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.brain as brain  # noqa: E402
from integrations.chatgpt import __main__ as chatgpt_cli  # noqa: E402
from integrations.chatgpt import auth, responses  # noqa: E402

ISSUED_CLIENT_ID = "oaiapp_test123"


class FakeOpenAI:
    """Just enough of auth.openai.com and api.openai.com/v1 to exercise the documented flow."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self.jwks = {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}
        self.authorize_requests: list[dict[str, str]] = []
        self.token_requests: list[dict[str, str]] = []
        self.revocations: list[dict[str, str]] = []
        self.responses_requests: list[dict] = []
        self.pending: dict[str, dict[str, str]] = {}
        self.valid_access: set[str] = set()
        self.refresh_tokens: set[str] = set()
        self.counter = 0
        # Knobs tests turn.
        self.authorize_error = ""
        self.wrong_state = False
        self.granted_scope = auth.SCOPES
        self.nonce_override = ""
        self.subject = "user-1"
        self.refresh_failure: tuple[int, str] | None = None
        self.responses_script: list = []  # each item: list of SSE events, or (status, error_body)
        self.models = [
            {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol", "visibility": "list"},
            {"slug": "internal-eval", "display_name": "Hidden", "visibility": "hide"},
            {"slug": "gpt-6.1-mini", "display_name": "GPT-6.1 Mini", "visibility": "list"},
        ]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _next(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter}"

    def _id_token(self, client_id: str, nonce: str) -> str:
        now = int(time.time())
        claims = {"iss": self.base, "aud": client_id, "sub": self.subject, "email": "sai@example.com",
                  "iat": now, "exp": now + 600, "nonce": self.nonce_override or nonce}
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "k1"})

    def _issue(self, client_id: str, nonce: str, expires_in: int = 3600) -> dict:
        access, refresh = self._next("access"), self._next("refresh")
        self.valid_access.add(access)
        self.refresh_tokens.add(refresh)
        return {"access_token": access, "refresh_token": refresh, "id_token": self._id_token(client_id, nonce),
                "token_type": "Bearer", "expires_in": expires_in, "scope": self.granted_scope}

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, status, payload, headers=None):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _form(self):
                length = int(self.headers.get("Content-Length") or 0)
                return {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}

            def _bearer_ok(self):
                token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
                if token not in fake.valid_access:
                    self._json(401, {"error": {"code": "invalid_token", "message": "expired"}})
                    return False
                return True

            def do_GET(self):
                url = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                if url.path == "/.well-known/openid-configuration":
                    return self._json(200, {
                        "issuer": fake.base,
                        "authorization_endpoint": f"{fake.base}/api/accounts/authorize",
                        "token_endpoint": f"{fake.base}/api/accounts/oauth/token",
                        "jwks_uri": f"{fake.base}/jwks",
                        "revocation_endpoint": f"{fake.base}/revoke",
                    })
                if url.path == "/jwks":
                    return self._json(200, fake.jwks)
                if url.path == "/api/accounts/authorize":
                    fake.authorize_requests.append(query)
                    target = {"state": "forged" if fake.wrong_state else query["state"]}
                    if fake.authorize_error:
                        target["error"] = fake.authorize_error
                    else:
                        code = fake._next("code")
                        fake.pending[code] = query
                        target.update(code=code, client_id=ISSUED_CLIENT_ID)
                    self.send_response(302)
                    self.send_header("Location", f"{query['redirect_uri']}?{urlencode(target)}")
                    self.end_headers()
                    return
                if url.path == "/v1/models":
                    if self._bearer_ok():
                        self._json(200, {"models": fake.models})
                    return
                self._json(404, {})

            def do_POST(self):
                url = urlparse(self.path)
                if url.path == "/api/accounts/oauth/token":
                    form = self._form()
                    fake.token_requests.append(form)
                    if form["grant_type"] == "authorization_code":
                        request = fake.pending.pop(form["code"], None)
                        challenge = base64.urlsafe_b64encode(
                            hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                        if (request is None or challenge != request["code_challenge"]
                                or form["redirect_uri"] != request["redirect_uri"]
                                or form["client_id"] != ISSUED_CLIENT_ID or "client_secret" in form):
                            return self._json(400, {"error": "invalid_grant"})
                        return self._json(200, fake._issue(form["client_id"], request["nonce"]))
                    if fake.refresh_failure:
                        status, error = fake.refresh_failure
                        return self._json(status, {"error": error})
                    if form["refresh_token"] not in fake.refresh_tokens:
                        return self._json(400, {"error": "invalid_grant"})
                    fake.refresh_tokens.discard(form["refresh_token"])  # rotation: old token is now dead
                    issued = fake._issue(form["client_id"], "")
                    issued.pop("id_token")
                    return self._json(200, issued)
                if url.path == "/revoke":
                    fake.revocations.append(self._form())
                    return self._json(200, {})
                if url.path == "/v1/responses":
                    if not self._bearer_ok():
                        return
                    length = int(self.headers.get("Content-Length") or 0)
                    fake.responses_requests.append(json.loads(self.rfile.read(length)))
                    step = fake.responses_script.pop(0)
                    if isinstance(step, tuple):
                        return self._json(step[0], step[1])
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for event in step:
                        self.wfile.write(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
                    return
                self._json(404, {})

        return Handler


@pytest.fixture
def fake(tmp_path, monkeypatch):
    server = FakeOpenAI()
    monkeypatch.setenv("JARVIS_CHATGPT_ISSUER", server.base)
    monkeypatch.setenv("JARVIS_CHATGPT_DIR", str(tmp_path / "chatgpt"))
    monkeypatch.delenv("JARVIS_CHATGPT_MODEL", raising=False)
    monkeypatch.setattr(responses, "API_BASE", f"{server.base}/v1")
    responses.PAUSE.clear()
    responses._models_cache.clear()
    yield server
    responses.PAUSE.clear()
    server.close()


def _browser(url: str) -> None:
    # Plays the user's browser: follows the authorize redirect back to Jarvis's callback.
    requests.get(url, timeout=10)


def _sign_in():
    return auth.sign_in(open_browser=_browser, preferred_port=0, timeout_seconds=10)


def _completed(*deltas: str) -> list[dict]:
    events = [{"type": "response.created", "response": {"id": "resp_1"}}]
    events += [{"type": "response.output_text.delta", "delta": d} for d in deltas]
    events.append({"type": "response.completed", "response": {"id": "resp_1", "status": "completed"}})
    return events


# Sign-in ------------------------------------------------------------------------------------


def test_first_sign_in_registers_with_the_dynamic_client(fake) -> None:
    record = _sign_in()

    first = fake.authorize_requests[0]
    assert first["client_id"] == auth.DYNAMIC_CLIENT_ID
    assert first["agent_name_hint"] == "Jarvis"
    assert first["ext_agent_host_id"].startswith("urn:uuid:")
    assert first["scope"] == "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
    assert first["resource"] == "https://api.openai.com/v1"
    assert first["code_challenge_method"] == "S256"
    assert urlparse(first["redirect_uri"]).hostname == "127.0.0.1"
    assert urlparse(first["redirect_uri"]).path == "/auth/callback"
    assert {"state", "nonce", "code_challenge"} <= first.keys()

    assert record["client_id"] == ISSUED_CLIENT_ID and record["email"] == "sai@example.com"
    assert auth.is_signed_in()
    assert auth.load_registration()["client_id"] == ISSUED_CLIENT_ID
    if os.name == "posix":
        assert stat.S_IMODE(auth.credentials_path().stat().st_mode) == 0o600


def test_second_sign_in_reauthorizes_the_issued_client(fake) -> None:
    _sign_in()
    _sign_in()

    again = fake.authorize_requests[1]
    assert again["client_id"] == ISSUED_CLIENT_ID
    assert "agent_name_hint" not in again
    assert again["login_hint"] == "sai@example.com" and again["id_token_hint"]
    assert again["ext_agent_host_id"] == fake.authorize_requests[0]["ext_agent_host_id"]


@pytest.mark.parametrize(
    ("knob", "value", "message"),
    [
        ("wrong_state", True, "state mismatch"),
        ("authorize_error", "access_denied", "declined"),
        ("granted_scope", "openid profile email offline_access", "plan usage was not granted"),
        ("nonce_override", "replayed", "nonce"),
    ],
)
def test_sign_in_rejects_bad_responses_and_saves_nothing(fake, knob, value, message) -> None:
    setattr(fake, knob, value)
    with pytest.raises(auth.ChatGPTAuthError, match=message):
        _sign_in()
    assert auth.load_credentials() is None and auth.load_registration() is None


def test_sign_in_rejects_a_different_account_for_the_same_registration(fake) -> None:
    _sign_in()
    fake.subject = "someone-else"
    with pytest.raises(auth.ChatGPTAuthError, match="different ChatGPT account"):
        _sign_in()


# Sessions -----------------------------------------------------------------------------------


def _expire_soon() -> None:
    credentials = auth.load_credentials()
    credentials["expires_at"] = int(time.time()) + 10
    auth._write_private(auth.credentials_path(), credentials)


def test_access_token_refreshes_once_under_concurrency_and_rotates(fake) -> None:
    first = _sign_in()
    _expire_soon()

    tokens: list[str] = []
    workers = [threading.Thread(target=lambda: tokens.append(auth.access_token())) for _ in range(5)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    refreshes = [r for r in fake.token_requests if r["grant_type"] == "refresh_token"]
    assert len(refreshes) == 1 and refreshes[0]["refresh_token"] == first["refresh_token"]
    assert len(set(tokens)) == 1 and tokens[0] != first["access_token"]
    assert auth.load_credentials()["refresh_token"] != first["refresh_token"]


def test_dead_and_temporary_refresh_failures_are_distinguished(fake) -> None:
    _sign_in()
    _expire_soon()

    fake.refresh_failure = (500, "server_error")
    with pytest.raises(auth.ChatGPTAuthError) as temporary:
        auth.access_token()
    assert not isinstance(temporary.value, auth.NotSignedInError)
    assert auth.load_credentials() is not None

    fake.refresh_failure = (400, "invalid_grant")
    with pytest.raises(auth.NotSignedInError, match="python -m integrations.chatgpt login"):
        auth.access_token()


def test_sign_out_revokes_and_keeps_the_registration(fake) -> None:
    record = _sign_in()

    assert auth.sign_out() is True

    assert fake.revocations == [{"token": record["refresh_token"], "token_type_hint": "refresh_token",
                                 "client_id": ISSUED_CLIENT_ID}]
    assert not auth.is_signed_in()
    assert auth.load_registration()["client_id"] == ISSUED_CLIENT_ID
    with pytest.raises(auth.NotSignedInError):
        auth.access_token()


# Models and inference -----------------------------------------------------------------------


def test_list_models_keeps_listed_models_in_server_order(fake) -> None:
    _sign_in()
    assert responses.list_models() == [
        {"slug": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol"},
        {"slug": "gpt-6.1-mini", "display_name": "GPT-6.1 Mini"},
    ]
    assert responses.default_model() == "gpt-6.1-sol"


def test_generate_streams_with_only_supported_fields(fake, monkeypatch) -> None:
    _sign_in()
    monkeypatch.setenv("JARVIS_CHATGPT_MODEL", "gpt-6.1-mini")
    fake.responses_script = [_completed("Hello", ", ", "world!")]

    assert responses.generate(instructions="Be brief.", user="Say hello") == "Hello, world!"
    assert fake.responses_requests == [{
        "model": "gpt-6.1-mini",
        "instructions": "Be brief.",
        "input": [{"role": "user", "content": "Say hello"}],
        "store": False,
        "stream": True,
    }]


def test_generate_refreshes_and_retries_once_on_401(fake) -> None:
    first = _sign_in()
    fake.valid_access.discard(first["access_token"])  # server-side expiry the client did not see
    fake.responses_script = [_completed("ok")]

    assert responses.generate(instructions="i", user="u", model="gpt-6.1-sol") == "ok"
    assert auth.load_credentials()["access_token"] != first["access_token"]


def test_success_requires_response_completed(fake) -> None:
    _sign_in()
    fake.responses_script = [
        [{"type": "response.output_text.delta", "delta": "partial"}],
        [{"type": "response.incomplete", "response": {"incomplete_details": {"reason": "max_output_tokens"}}}],
    ]
    with pytest.raises(responses.ChatGPTResponseError, match="ended before"):
        responses.generate(instructions="i", user="u", model="m")
    with pytest.raises(responses.ChatGPTResponseError, match="max_output_tokens"):
        responses.generate(instructions="i", user="u", model="m")


def test_usage_limit_mid_stream_pauses_until_a_new_sign_in(fake) -> None:
    _sign_in()
    limit = {"type": "response.failed", "response": {"error": {"code": responses.LIMIT_EXCEEDED, "message": "x"}}}
    fake.responses_script = [[{"type": "response.output_text.delta", "delta": "Hal"}, limit]]

    with pytest.raises(responses.ChatGPTPaused, match="chatgpt.com/settings/usage"):
        responses.generate(instructions="i", user="u", model="m")
    with pytest.raises(responses.ChatGPTPaused):
        responses.generate(instructions="i", user="u", model="m")
    assert len(fake.responses_requests) == 1  # the pause stopped the second request locally

    time.sleep(1.1)  # signed_in_at has one-second resolution
    _sign_in()
    fake.responses_script = [_completed("back")]
    assert responses.generate(instructions="i", user="u", model="m") == "back"


def test_ineligible_account_is_not_retried_and_outages_back_off(fake) -> None:
    _sign_in()
    fake.responses_script = [(403, {"error": {"code": responses.NOT_ELIGIBLE, "message": "region"}})]
    with pytest.raises(responses.ChatGPTPaused, match="not available for this account"):
        responses.generate(instructions="i", user="u", model="m")
    assert responses.PAUSE.until == float("inf")

    responses.PAUSE.clear()
    first = responses._handle_error(responses.USAGE_UNAVAILABLE, "", 503)
    responses.PAUSE.until = 0
    responses._handle_error(responses.USAGE_UNAVAILABLE, "", 503)
    assert isinstance(first, responses.ChatGPTPaused)
    assert responses.PAUSE.backoff == 2 * responses.BACKOFF_START_SECONDS


# Brain and CLI ------------------------------------------------------------------------------


async def test_brain_uses_chatgpt_only_when_signed_in(fake) -> None:
    assert not brain.provider_configured(None, "chatgpt")
    with pytest.raises(brain.BrainProviderUnavailable, match="not signed in"):
        await brain._chatgpt_reply(None, "sys", "q", 0.4, 100)

    _sign_in()
    fake.responses_script = [_completed("{\"ok\": true}")]
    assert brain.provider_configured(None, "chatgpt")
    assert await brain._chatgpt_reply(None, "sys", "q", 0.4, 100, json_mode=True) == '{"ok": true}'
    sent = fake.responses_requests[0]
    assert sent["instructions"].startswith("sys") and "JSON object" in sent["instructions"]
    assert "temperature" not in sent and "max_output_tokens" not in sent
    assert brain.provider_label(None, "chatgpt") == "ChatGPT plan"


async def test_brain_falls_through_when_the_plan_is_paused(fake) -> None:
    _sign_in()
    responses.PAUSE.pause(responses.LIMIT_EXCEEDED, "limit reached", 60)
    with pytest.raises(brain.BrainProviderUnavailable, match="limit reached"):
        await brain._chatgpt_reply(None, "sys", "q", 0.4, 100)


def test_cli_status_and_models(fake, capsys) -> None:
    assert chatgpt_cli.main(["status"]) == 1
    assert "Not signed in" in capsys.readouterr().out

    _sign_in()
    assert chatgpt_cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "sai@example.com" in out and "Plan usage granted: yes" in out

    assert chatgpt_cli.main(["models"]) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("gpt-6.1-sol")

    assert chatgpt_cli.main(["logout"]) == 0
    assert "Signed out." in capsys.readouterr().out
