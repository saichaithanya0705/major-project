"""
Checks for shared async subprocess lifecycle helpers.
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from core.async_process_lifecycle import await_subprocess_operation


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.kill_calls = 0
        self.wait_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    async def wait(self) -> int:
        self.wait_calls += 1
        return -9


def test_await_subprocess_operation_terminates_running_process_on_error() -> None:
    async def _run() -> None:
        process = _FakeProcess()

        async def _explode() -> str:
            raise RuntimeError("boom")

        try:
            await await_subprocess_operation(
                process=process,
                timeout=1.0,
                operation=_explode(),
                terminate=process.kill,
                terminate_on_error=True,
            )
        except RuntimeError as exc:
            assert str(exc) == "boom"
        else:
            raise AssertionError("Expected RuntimeError to be re-raised.")

        assert process.kill_calls == 1
        assert process.wait_calls == 1

    asyncio.run(_run())
