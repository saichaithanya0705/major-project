"""
Checks for extracted CLI response-parser helpers.

Usage:
    python tests/test_cli_response_parser_boundary.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_cli.response_parser import parse_json_response, parse_stream_json_response


def run_checks() -> None:
    stdout = "\n".join(
        [
            '{"type":"message","role":"assistant","content":"Hello"}',
            '{"type":"tool_use","tool_name":"run_shell_command","tool_id":"t1","parameters":{"command":"echo hi"}}',
            '{"type":"tool_result","tool_id":"t1","status":"success","output":"hi"}',
            '{"type":"result","status":"success"}',
        ]
    )
    parsed = parse_stream_json_response(stdout=stdout, stderr="", returncode=0)
    assert parsed["success"] is True, parsed
    assert parsed["output"] == "Hello", parsed
    assert parsed["tool_calls"], parsed
    assert parsed["tool_calls"][0]["status"] == "success", parsed

    failed = parse_stream_json_response(
        stdout='{"type":"error","message":"boom"}',
        stderr="",
        returncode=1,
    )
    assert failed["success"] is False, failed
    assert failed["error"] == "boom", failed

    json_parsed = parse_json_response(
        stdout='{"response":"done","error":null}',
        stderr="",
        returncode=0,
    )
    assert json_parsed["success"] is True, json_parsed
    assert json_parsed["output"] == "done", json_parsed

    raw_parsed = parse_json_response(
        stdout="not-json",
        stderr="bad",
        returncode=1,
    )
    assert raw_parsed["success"] is False, raw_parsed
    assert raw_parsed["output"] == "not-json", raw_parsed
    assert raw_parsed["error"] == "bad", raw_parsed


if __name__ == "__main__":
    run_checks()
    print("[test_cli_response_parser_boundary] All checks passed.")
