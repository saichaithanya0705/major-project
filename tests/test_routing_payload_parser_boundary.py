"""
Checks the shared route-payload normalization and copy boundary.
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from models.routing_payload_parser import (
    copy_plan_task_payload,
    copy_route_payload,
    route_payload_work_text,
)


def test_copy_route_payload_promotes_direct_text_and_preserves_context() -> None:
    route = {
        "agent": "direct",
        "direct_response_args": {"text": "Done.", "variant": "compact"},
        "orchestrator_context": {
            "request": "finish",
            "dependency_outcomes": (),
            "artifacts": (),
            "metadata": {},
        },
    }

    copied = copy_route_payload(route, error_source="test route")

    assert copied == {
        "agent": "direct",
        "response_text": "Done.",
        "direct_response_args": {"variant": "compact"},
        "orchestrator_context": {
            "request": "finish",
            "dependency_outcomes": (),
            "artifacts": (),
            "metadata": {},
        },
    }


def test_route_payload_work_text_uses_response_then_task_then_query() -> None:
    assert route_payload_work_text({"agent": "direct", "response_text": "Done."}) == "Done."
    assert route_payload_work_text({"agent": "browser", "task": "Open docs"}) == "Open docs"
    assert route_payload_work_text({"agent": "jarvis", "query": "Explain this"}) == "Explain this"


def test_copy_plan_task_payload_normalizes_direct_args_and_sequences() -> None:
    task = {
        "id": " patch ",
        "agent": "direct",
        "direct_response_args": {"text": "Done.", "variant": "compact"},
        "depends_on": " research ",
        "resources": ["cli", " ", "web_qa"],
        "max_attempts": "2",
    }

    copied = copy_plan_task_payload(task, error_source="test plan task")

    assert copied == {
        "id": "patch",
        "agent": "direct",
        "response_text": "Done.",
        "direct_response_args": {"variant": "compact"},
        "depends_on": ["research"],
        "resources": ["cli", "web_qa"],
        "max_attempts": 2,
    }
