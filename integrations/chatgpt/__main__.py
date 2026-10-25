"""
python -m integrations.chatgpt login     # sign in with ChatGPT in your browser
python -m integrations.chatgpt status    # who is signed in, and whether requests are paused
python -m integrations.chatgpt models    # models your plan offers (set one with JARVIS_CHATGPT_MODEL)
python -m integrations.chatgpt logout    # revoke the session and delete local tokens
"""

from __future__ import annotations

import argparse
import sys
import time

from integrations.chatgpt import auth, responses


def _login() -> int:
    print("Opening your browser to sign in with ChatGPT...")
    record = auth.sign_in(open_browser=_open_and_print)
    print(f"Signed in as {record['email'] or record['subject']}. Jarvis can now use your ChatGPT plan.")
    return 0


def _open_and_print(url: str) -> None:
    import webbrowser

    if not webbrowser.open(url):
        print(f"Open this link to continue:\n{url}")


def _status() -> int:
    credentials = auth.load_credentials()
    if not credentials:
        print("Not signed in. Run: python -m integrations.chatgpt login")
        return 1
    minutes = (int(credentials.get("expires_at", 0)) - time.time()) / 60
    print(f"Signed in as {credentials.get('email') or credentials.get('subject')}")
    print(f"Plan usage granted: {'yes' if auth.PLAN_SCOPE in credentials.get('scopes', []) else 'no'}")
    print(f"Access token: {'valid for %d min' % minutes if minutes > 0 else 'expired (renews on next use)'}")
    print(f"Credentials: {auth.credentials_path()}")
    return 0


def _models() -> int:
    for model in responses.list_models(refresh=True):
        print(f"{model['slug']:<32} {model['display_name']}")
    return 0


def _logout() -> int:
    if not auth.load_credentials():
        print("Not signed in.")
        return 0
    revoked = auth.sign_out()
    print("Signed out." if revoked else "Deleted local tokens (could not reach OpenAI to revoke the session).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m integrations.chatgpt", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["login", "status", "models", "logout"])
    command = parser.parse_args(argv).command
    try:
        return {"login": _login, "status": _status, "models": _models, "logout": _logout}[command]()
    except (auth.ChatGPTAuthError, responses.ChatGPTResponseError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
