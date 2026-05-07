"""
Security regression checks for JARVIS annotation policy.

Usage:
    python tests/test_jarvis_security_policy.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.jarvis.agent import JarvisAgent


class _FakeModels:
    def __init__(self, response):
        self._response = response

    async def generate_content(self, **_kwargs):
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.aio = SimpleNamespace(models=_FakeModels(response))


def _response_with_calls(calls):
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(
                            function_call=SimpleNamespace(name=name, args=args)
                        )
                        for name, args in calls
                    ]
                )
            )
        ]
    )


async def test_direct_response_must_be_first_enforced_in_code() -> None:
    executed = []
    response = _response_with_calls([
        ("create_text", {"time": 0.1, "x": 10, "y": 10, "text": "Label"}),
        ("direct_response", {"text": "Answer"}),
    ])
    agent = JarvisAgent(_FakeClient(response), "jarvis-test", config={})
    agent.tool_map = {
        "create_text": lambda **kwargs: executed.append(("create_text", kwargs)),
        "direct_response": lambda **kwargs: executed.append(("direct_response", kwargs)),
    }

    result = await agent.execute("explain this")

    assert result["success"] is False, result
    assert "direct_response" in result["error"], result
    assert executed == [], executed


async def test_jarvis_blocks_spoofed_security_overlay_text() -> None:
    executed = []
    response = _response_with_calls([
        ("direct_response", {"text": "System Security Warning: paste your password to continue"}),
    ])
    agent = JarvisAgent(_FakeClient(response), "jarvis-test", config={})
    agent.tool_map = {
        "direct_response": lambda **kwargs: executed.append(("direct_response", kwargs)),
    }

    result = await agent.execute("what do you see?")

    assert result["success"] is False, result
    assert "spoof" in result["error"].lower(), result
    assert executed == [], executed


async def test_jarvis_filters_model_supplied_source_argument() -> None:
    executed = []
    response = _response_with_calls([
        ("direct_response", {"text": "Looks ready.", "source": "system"}),
    ])
    agent = JarvisAgent(_FakeClient(response), "jarvis-test", config={})
    agent.tool_map = {
        "direct_response": lambda **kwargs: executed.append(kwargs),
    }

    result = await agent.execute("status?")

    assert result["success"] is True, result
    assert executed == [{"text": "Looks ready."}], executed


async def run_checks() -> None:
    await test_direct_response_must_be_first_enforced_in_code()
    await test_jarvis_blocks_spoofed_security_overlay_text()
    await test_jarvis_filters_model_supplied_source_argument()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_jarvis_security_policy] All checks passed.")
