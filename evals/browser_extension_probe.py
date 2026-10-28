"""Real MCP browser/fixture rehearsal; all submissions stay on a local test server.

Run with --mode fixture for deterministic network-side-effect checks, optionally
--llm for real-provider research. --mode extension verifies the selected live tab
and requires the user-installed official extension and browser pairing.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.browser.connected_gateway import ConnectedGateway, public_url
from agents.browser.connected_runner import ConnectedBrowserRunner
from agents.browser.mcp_client import PlaywrightMcpClient


def fixture_server():
    submissions = []
    fixture = (ROOT / "tests" / "fixtures" / "browser_operator.html").read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(fixture)
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            submissions.append({"path": self.path, "fields": parse_qs(body.decode()) if self.path == "/submit" else {"draft": body.decode()}})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<title>Application received</title><h1>Application received successfully</h1><p>Receipt DEMO-001</p>")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, submissions


def ref(gateway, role, label):
    match = re.search(r"(?m)^\s*- " + re.escape(role) + r' "' + re.escape(label) + r'"[^\n]*?\[ref=([^\]]+)\]', gateway.observation())
    if not match:
        raise RuntimeError(f"Fixture control not found: {role} {label}")
    return match.group(1)


async def research(client, base, results, check, runner=None):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    runner = runner or ConnectedBrowserRunner(client)
    results["research_decisions"] = []
    results["research_observations"] = []  # Synthetic fixture only, never used in extension mode.
    async def record_decision(system, user):
        results["research_observations"].append(json.loads(user)["observation"][:12000])
        raw = await runner._brain_decide(system, user)
        try:
            results["research_decisions"].append(json.loads(raw))
        except ValueError:
            results["research_decisions"].append({"invalid_output":True})
        return raw
    runner.decide = record_decision
    reply = await runner.execute(f"Use the browser to open {base}/research, inspect both device reports, then compare Quartz and Lumen by price, memory, and measured battery life. Return the actual figures with source links. Do not submit any forms.")
    results["research_result"] = reply
    summary = str((reply.get("result") or {}).get("summary", ""))
    check("live-provider multipage research", reply.get("complete") and all(word in summary.lower() for word in ("quartz","lumen","15","22","9","14")))


async def run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    results = {"mode": args.mode, "checks": [], "complete": False}
    executable = args.executable
    if not executable and args.mode != "extension":
        chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
        executable = str(chrome) if chrome.is_file() else None
    connected = args.mode == "extension" or args.connected_fixture
    client = PlaywrightMcpClient(ROOT, extension=connected, headless=not connected,
        executable_path=executable, browser=args.browser, timeout=120 if args.mode == "extension" else 45)
    server = thread = None
    started = time.monotonic()
    def check(name, condition):
        results["checks"].append({"name": name, "passed": bool(condition)})
        if not condition: raise RuntimeError("Check failed: " + name)
    try:
        if args.mode == "extension":
            if args.open_test_tab:
                (await client.call_result("browser_tabs", {"action":"new", "url":"https://example.com/"})).require_success()
                args.tab_url = "https://example.com/"
            runner = ConnectedBrowserRunner(client)
            await runner.connect()
            if runner.state == "awaiting_tab_selection":
                index = args.tab_index
                if args.tab_url:
                    matches = [i for i,(_,url) in runner.gateway._tab_entries.items() if url == args.tab_url]
                    if len(matches) != 1:
                        raise RuntimeError("The explicit test-tab URL is absent or ambiguous; select its index deliberately.")
                    index = matches[0]
                if index is None:
                    raise RuntimeError("Browser authenticated; use --tab-index or --tab-url to choose the test tab explicitly.")
                await runner.select_tab(index)
            results["selected_tab"] = {"title": runner.gateway.title, "url": public_url(runner.gateway.url)}
            check("extension selected tab snapshot", bool(runner.gateway._refs or runner.gateway.title))
            if args.open_test_tab:
                check("extension public page contents", "Example Domain" in runner.gateway.observation())
        elif args.mode == "research":
            server, thread, _ = fixture_server()
            await research(client, f"http://127.0.0.1:{server.server_address[1]}", results, check)
        else:
            server, thread, submissions = fixture_server()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            approvals = []
            allow = False
            async def review(message):
                approvals.append(message.split("\n")[0])
                return allow
            gateway = ConnectedGateway(client, review)
            runner = None
            if args.connected_fixture:
                (await client.call_result("browser_tabs", {"action":"new", "url":base + "/"})).require_success()
                runner = ConnectedBrowserRunner(client, confirm=review)
                await runner.connect()
                index = next(i for i,(_,url) in runner.gateway._tab_entries.items() if url == base + "/")
                await runner.select_tab(index)
                gateway = runner.gateway
            await gateway.observe()
            await gateway.act("browser_navigate", {"url": base + "/form"})
            await gateway.act("browser_fill_form", {"fields": [
                {"target": ref(gateway,"textbox","Full name"), "name":"Full name", "type":"textbox", "value":"Demo Presenter"},
                {"target": ref(gateway,"textbox","Email"), "name":"Email", "type":"textbox", "value":"presenter@example.test"},
                {"target": ref(gateway,"combobox","Track"), "name":"Track", "type":"combobox", "value":"Engineering"},
                {"target": ref(gateway,"checkbox","Receive project updates"), "name":"Updates", "type":"checkbox", "value":"true"},
                {"target": ref(gateway,"radio","Online attendance"), "name":"Attendance", "type":"radio", "value":"true"},
            ]})
            check("form read-back without confirmation", len(gateway.verified_steps) == 2 and not approvals and not submissions)
            try:
                await gateway.act("browser_click", {"target": ref(gateway,"button","Send application")})
            except RuntimeError as exc:
                if "declined" not in str(exc): raise
            check("declined submission has no network effect", len(approvals) == 1 and not submissions)
            allow = True
            await gateway.act("browser_click", {"target": ref(gateway,"button","Send application")})
            check("approved submission occurs exactly once", len(submissions) == 1 and submissions[0]["fields"].get("full_name") == ["Demo Presenter"])
            check("submission receipt observed", "Receipt DEMO-001" in gateway.observation())
            await gateway.act("browser_navigate", {"url": base + "/app"})
            await gateway.act("browser_click", {"target": ref(gateway,"button","Show details")})
            check("ordinary app control needs no confirmation", "Milestone Polaris" in gateway.observation() and len(approvals) == 2)
            await gateway.act("browser_type", {"target": ref(gateway,"textbox","Draft title"), "text":"Browser presentation draft"})
            await gateway.act("browser_click", {"target": ref(gateway,"button","Submit draft")})
            check("SPA submission reviewed exactly once", len(approvals) == 3 and len(submissions) == 2 and submissions[-1]["path"] == "/submit-draft")
            check("SPA result observed", "Draft received successfully" in gateway.observation())
            if args.llm:
                await research(client, base, results, check, runner)
            if args.connected_fixture:
                await gateway.list_tabs()
                for index, (_,url) in gateway._tab_entries.items():
                    if url.startswith(base + "/"):
                        (await client.call_result("browser_tabs", {"action":"close", "index":index})).require_success()
        results["complete"] = True
    except Exception as exc:
        results["error"] = {"type": type(exc).__name__, "message": str(exc)[:400]}
    finally:
        await client.close()
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        results["duration_seconds"] = round(time.monotonic() - started, 3)
    output = Path(args.output) if args.output else ROOT / "evals/results/browser-extension/" / f"{args.mode}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"complete":results["complete"], "checks":results["checks"], "error":results.get("error"), "output":str(output)},indent=2))
    return 0 if results["complete"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fixture","research","extension"], default="fixture")
    parser.add_argument("--open-test-tab", action="store_true", help="Open and explicitly select a dedicated Example Domain tab")
    parser.add_argument("--connected-fixture", action="store_true", help="Run synthetic fixture checks in a dedicated installed Chrome extension tab")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--executable")
    parser.add_argument("--browser", choices=["chrome","msedge"], default="chrome")
    parser.add_argument("--output")
    parser.add_argument("--tab-index", type=int)
    parser.add_argument("--tab-url")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
