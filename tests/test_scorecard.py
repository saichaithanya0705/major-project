"""Task scorecard: task loading, routing and run checks, reports, and saved results."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from evals.scorecard import (  # noqa: E402
    DEFAULT_TASKS,
    Task,
    check_result,
    latest_results,
    load_tasks,
    render_report,
    save_results,
    score_tasks,
)


def test_bundled_task_file_is_valid() -> None:
    tasks = load_tasks(DEFAULT_TASKS)
    assert len(tasks) >= 10
    assert {"pptx-deck", "docx-report", "pdf-notes", "xlsx-budget", "browser-read", "memory-remember"} <= {t.id for t in tasks}
    assert all(task.expect or not task.run for task in tasks)


def test_load_tasks_rejects_bad_files(tmp_path) -> None:
    bad_agent = tmp_path / "bad.yaml"
    bad_agent.write_text("tasks:\n  - {id: a, prompt: hi, agent: wizard}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown agent"):
        load_tasks(bad_agent)
    duplicate = tmp_path / "dup.yaml"
    duplicate.write_text("tasks:\n  - {id: a, prompt: hi, agent: direct}\n  - {id: a, prompt: yo, agent: direct}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_tasks(duplicate)
    multi = tmp_path / "multi.yaml"
    multi.write_text("tasks:\n  - {id: a, prompt: hi, agent: [cua_cli, browser]}\n", encoding="utf-8")
    assert load_tasks(multi)[0].agents == ("cua_cli", "browser")


def test_check_result_reports_each_problem(tmp_path) -> None:
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"x")
    task = Task("t", "p", ("cua_cli",), expect={"success": True, "output_extension": ".pptx", "reply_contains": ["Created"], "max_seconds": 10})

    assert check_result(task, {"success": True, "result": "Created it", "output_file_path": str(deck)}, 3) == (True, "ok")
    passed, detail = check_result(task, {"success": False, "error": "boom", "result": "nope"}, 30)
    assert not passed
    assert detail == "success=False (boom); no .pptx file created; reply lacks 'Created'; took 30s > 10s"


async def test_route_mode_scores_routing_only() -> None:
    tasks = [
        Task("deck", "make slides", ("cua_cli",)),
        Task("fact", "boiling point", ("direct",)),
        Task("either", "do it", ("cua_cli", "browser")),
    ]
    answers = {"make slides": ["cua_cli", "direct"], "boiling point": ["direct", "direct"], "do it": ["browser", "jarvis"]}

    async def route(prompt):
        return answers[prompt].pop(0)

    scores = await score_tasks(tasks, mode="route", trials=2, route=route)

    assert [(s.task_id, s.passes) for s in scores] == [("deck", 1), ("fact", 2), ("either", 1)]
    assert scores[0].trials[1].detail == "routed to direct"


async def test_run_mode_executes_runnable_tasks_and_survives_errors() -> None:
    tasks = [
        Task("fact", "q1", ("direct",), expect={"reply_contains": ["100"]}),
        Task("unsafe", "q2", ("browser",), run=False),
        Task("crash", "q3", ("cua_cli",), expect={"success": True}),
        Task("router-down", "q4", ("direct",)),
    ]
    executed = []

    async def route(prompt):
        if prompt == "q4":
            raise RuntimeError("ollama down")
        return {"q1": "direct", "q2": "browser", "q3": "cua_cli"}[prompt]

    async def direct(prompt):
        executed.append(prompt)
        return {"success": True, "result": "It boils at 100 °C."}

    async def cli(prompt):
        executed.append(prompt)
        raise OSError("disk full")

    scores = await score_tasks(tasks, mode="run", trials=1, route=route, executors={"direct": direct, "cua_cli": cli})

    assert executed == ["q1", "q3"]
    assert [(s.task_id, s.passes) for s in scores] == [("fact", 1), ("unsafe", 1), ("crash", 0), ("router-down", 0)]
    assert scores[2].trials[0].detail == "success=False (OSError: disk full)"
    assert scores[3].trials[0].detail == "router error: ollama down"


async def test_report_and_saved_results_compare_runs(tmp_path) -> None:
    async def route_ok(prompt):
        return "direct"

    async def route_bad(prompt):
        return "jarvis"

    tasks = [Task("fact", "q", ("direct",))]
    first = await score_tasks(tasks, mode="route", trials=2, route=route_bad)
    save_results(first, mode="route", results_dir=tmp_path)
    previous = latest_results("route", results_dir=tmp_path)
    second = await score_tasks(tasks, mode="route", trials=2, route=route_ok)

    report = render_report(second, previous)

    assert "| fact | 2/2 |" in report and "+100%" in report
    assert report.endswith("**Overall: 2/2 (100%)**")
    assert latest_results("run", results_dir=tmp_path) is None
    assert Path(next(tmp_path.glob("*-route.json"))).read_text().count('"passes": 0') == 1
