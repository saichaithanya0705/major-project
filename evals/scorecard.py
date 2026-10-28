"""
Task scorecard: how often Jarvis handles your real tasks correctly.

    python -m evals.scorecard                       # routing check, 3 trials per task
    python -m evals.scorecard --mode run --only pptx-deck,chat-fact
    python -m evals.scorecard --tasks my_tasks.yaml --trials 5

``route`` mode asks the router (your local model) which agent each prompt
should go to and compares it with the expected agent. It is fast and changes
nothing on your machine.

``run`` mode also executes each task with the agent it expects and checks the
result (success, created file type, reply text, time). It creates real files
and opens a real browser; tasks marked ``run: false`` are skipped. Risky
browser actions still ask for confirmation, so unattended runs decline them.

Each run is saved to ``evals/results/<timestamp>.json`` and compared with the
previous run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_TASKS = Path(__file__).resolve().parent / "tasks.yaml"
KNOWN_AGENTS = {"direct", "web_qa", "browser", "cua_cli", "cua_vision", "jarvis", "screen_context", "memory"}

RouteFn = Callable[[str], Awaitable[str]]
Executor = Callable[[str], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    agents: tuple[str, ...]
    run: bool = True
    expect: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trial:
    passed: bool
    seconds: float
    detail: str
    routed_to: str = ""


@dataclass
class TaskScore:
    task_id: str
    trials: list[Trial]

    @property
    def passes(self) -> int:
        return sum(trial.passed for trial in self.trials)


def load_tasks(path: Path) -> list[Task]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tasks: list[Task] = []
    seen: set[str] = set()
    for raw in data.get("tasks") or []:
        task_id = str(raw.get("id") or "").strip()
        prompt = str(raw.get("prompt") or "").strip()
        agents = raw.get("agent")
        agents = tuple(agents) if isinstance(agents, list) else (agents,)
        if not task_id or not prompt:
            raise ValueError(f"Every task needs an id and a prompt: {raw!r}")
        if task_id in seen:
            raise ValueError(f"Duplicate task id: {task_id}")
        unknown = [agent for agent in agents if agent not in KNOWN_AGENTS]
        if unknown:
            raise ValueError(f"Task {task_id} names unknown agent(s) {unknown}; use one of {sorted(KNOWN_AGENTS)}")
        seen.add(task_id)
        tasks.append(Task(task_id, prompt, agents, bool(raw.get("run", True)), dict(raw.get("expect") or {})))
    return tasks


def check_result(task: Task, result: dict[str, Any], seconds: float) -> tuple[bool, str]:
    expect = task.expect
    problems: list[str] = []
    reply = str(result.get("result") or result.get("reply") or "")
    if "success" in expect and bool(result.get("success")) != bool(expect["success"]):
        problems.append(f"success={result.get('success')} ({str(result.get('error') or '')[:120]})")
    extension = expect.get("output_extension")
    if extension:
        path = str(result.get("output_file_path") or "")
        if not path.lower().endswith(str(extension).lower()) or not Path(path).exists():
            problems.append(f"no {extension} file created")
    for needle in expect.get("reply_contains") or []:
        if str(needle).lower() not in reply.lower():
            problems.append(f"reply lacks {needle!r}")
    if expect.get("max_seconds") and seconds > float(expect["max_seconds"]):
        problems.append(f"took {seconds:.0f}s > {expect['max_seconds']}s")
    return (not problems, "; ".join(problems) or "ok")


async def score_tasks(
    tasks: list[Task],
    *,
    mode: str,
    trials: int,
    route: RouteFn,
    executors: dict[str, Executor] | None = None,
) -> list[TaskScore]:
    scores: list[TaskScore] = []
    for task in tasks:
        task_trials: list[Trial] = []
        for _ in range(trials):
            started = time.monotonic()
            try:
                routed_to = await route(task.prompt)
            except Exception as exc:  # noqa: BLE001 - a crashing router is a failed trial, not a crashed run.
                task_trials.append(Trial(False, time.monotonic() - started, f"router error: {exc}"))
                continue
            if routed_to not in task.agents:
                task_trials.append(Trial(False, time.monotonic() - started, f"routed to {routed_to}", routed_to))
                continue
            if mode == "route" or not task.run:
                task_trials.append(Trial(True, time.monotonic() - started, "routed correctly", routed_to))
                continue
            executor = (executors or {}).get(routed_to)
            if executor is None:
                task_trials.append(Trial(False, time.monotonic() - started, f"no executor for {routed_to}", routed_to))
                continue
            try:
                result = await executor(task.prompt)
            except Exception as exc:  # noqa: BLE001
                result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
            seconds = time.monotonic() - started
            passed, detail = check_result(task, result, seconds)
            task_trials.append(Trial(passed, seconds, detail, routed_to))
        scores.append(TaskScore(task.id, task_trials))
    return scores


def render_report(scores: list[TaskScore], previous: dict[str, Any] | None = None) -> str:
    before = {row["task_id"]: row for row in (previous or {}).get("tasks", [])}
    lines = ["| Task | Pass | Avg s | Change | Last failure |", "| --- | --- | --- | --- | --- |"]
    total_pass = total = 0
    for score in scores:
        count = len(score.trials)
        total_pass += score.passes
        total += count
        average = sum(trial.seconds for trial in score.trials) / count if count else 0.0
        change = ""
        if score.task_id in before:
            old = before[score.task_id]
            delta = score.passes / count - old["passes"] / max(old["trials"], 1) if count else 0
            change = f"{delta:+.0%}" if delta else "="
        failure = next((trial.detail for trial in reversed(score.trials) if not trial.passed), "")
        lines.append(f"| {score.task_id} | {score.passes}/{count} | {average:.1f} | {change} | {failure[:80]} |")
    rate = total_pass / total if total else 0.0
    lines.append(f"\n**Overall: {total_pass}/{total} ({rate:.0%})**")
    return "\n".join(lines)


def save_results(scores: list[TaskScore], *, mode: str, results_dir: Path = RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{mode}.json"
    payload = {
        "mode": mode,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "tasks": [
            {"task_id": s.task_id, "passes": s.passes, "trials": len(s.trials), "details": [asdict(t) for t in s.trials]}
            for s in scores
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def latest_results(mode: str, results_dir: Path = RESULTS_DIR) -> dict[str, Any] | None:
    runs = sorted(results_dir.glob(f"*-{mode}.json")) if results_dir.exists() else []
    return json.loads(runs[-1].read_text(encoding="utf-8")) if runs else None


# Live wiring -----------------------------------------------------------------------------------


def build_live_route() -> RouteFn:
    """Route exactly as a real request would: memory commands, rule-based Q&A, then the router model."""
    from core.memory import MemoryStore, handle_memory_command
    from core.settings import get_model_configs
    from models.models import GeminiModel
    from models.prompts import RAPID_RESPONSE_SYSTEM_PROMPT
    from models.routing_guardrails import apply_routing_guardrails_route
    from models.routing_question_policy import is_direct_qa_request
    import tempfile

    rapid_model, jarvis_model = get_model_configs()
    model = GeminiModel(jarvis_model=jarvis_model, rapid_response_model=rapid_model)
    scratch_memory = MemoryStore(Path(tempfile.mkdtemp(prefix="jarvis-eval-")) / "memory.sqlite3")

    async def route(prompt: str) -> str:
        if handle_memory_command(prompt, scratch_memory) is not None:
            return "memory"
        if is_direct_qa_request(prompt):
            return "direct"
        result = await model.route_request(RAPID_RESPONSE_SYSTEM_PROMPT + f"\n# User's Latest Request:\n{prompt}")
        if "tasks" in result:
            return str(result["tasks"][0].get("agent") or "") if result["tasks"] else ""
        return str(apply_routing_guardrails_route(prompt, result, None).get("agent") or "")

    return route


def build_live_executors() -> dict[str, Executor]:
    from agents.browser.agent import BrowserAgent
    from agents.cua_cli.agent import CLIAgent
    from core.memory import MemoryStore, handle_memory_command
    from core.settings import get_model_configs
    from models.direct_answer_runtime import answer_direct_request
    from models.models import GeminiModel
    import tempfile

    rapid_model, jarvis_model = get_model_configs()
    model = GeminiModel(jarvis_model=jarvis_model, rapid_response_model=rapid_model)
    scratch_memory = MemoryStore(Path(tempfile.mkdtemp(prefix="jarvis-eval-")) / "memory.sqlite3")

    async def direct(prompt: str) -> dict[str, Any]:
        return {"success": True, "result": await answer_direct_request(model, user_prompt=prompt)}

    async def cli(prompt: str) -> dict[str, Any]:
        return await CLIAgent().execute(prompt)

    async def browser(prompt: str) -> dict[str, Any]:
        result = await BrowserAgent(model_name=jarvis_model).execute(prompt)
        summary = result.get("result")
        if not isinstance(summary, str):
            summary = json.dumps(summary, default=str)
        return {**result, "result": summary}

    async def memory(prompt: str) -> dict[str, Any]:
        return {"success": True, "result": handle_memory_command(prompt, scratch_memory) or ""}

    return {"direct": direct, "cua_cli": cli, "browser": browser, "memory": memory}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.scorecard", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["route", "run"], default="route")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--only", help="Comma-separated task ids")
    args = parser.parse_args(argv)

    tasks = load_tasks(args.tasks)
    if args.only:
        wanted = {name.strip() for name in args.only.split(",") if name.strip()}
        tasks = [task for task in tasks if task.id in wanted]
    if not tasks:
        print("No tasks selected.", file=sys.stderr)
        return 1

    previous = latest_results(args.mode)
    scores = asyncio.run(
        score_tasks(
            tasks,
            mode=args.mode,
            trials=max(1, args.trials),
            route=build_live_route(),
            executors=build_live_executors() if args.mode == "run" else None,
        )
    )
    print(render_report(scores, previous))
    print(f"\nSaved {save_results(scores, mode=args.mode)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
