# Web QA Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `web_qa` routed agent that answers source-grounded factual questions through Tavily MCP without changing browser automation behavior.

**Architecture:** The router gets a seventh route, `web_qa`, for current/source-needed factual Q&A. `WebQAAgent` owns Tavily MCP search and answer synthesis, returning Markdown plus a `Sources` section. Existing direct Q&A remains the fast path for timeless questions.

**Tech Stack:** Python 3.11, existing `mcp` SDK, Tavily MCP launched over stdio with `npx -y tavily-mcp@latest`, existing Gemini/OpenRouter model wrapper for synthesis.

---

### Task 1: Router Policy and Contracts

**Files:**
- Modify: `models/contracts.py`
- Modify: `models/function_calls.py`
- Modify: `models/prompts.py`
- Modify: `models/routing_policy.py`
- Modify: `models/router_backends.py`
- Test: `tests/test_routing_policy.py`
- Test: `tests/test_router_backends_boundary.py`
- Test: `tests/test_router_chaining.py`

- [x] Ensure `RouteDecision` accepts `web_qa` with required `task`.
- [x] Ensure router tool declarations expose `invoke_web_qa`.
- [x] Teach prompts that `web_qa` is for Tavily source-grounded Q&A, not browser automation.
- [x] Add `_is_web_qa_request()` so direct Q&A fast path does not intercept latest/source-grounded questions.
- [x] Normalize model and legacy text-tool outputs for `web_qa`.
- [x] Run `python -m pytest tests/test_routing_policy.py tests/test_router_backends_boundary.py tests/test_router_chaining.py -q`.

### Task 2: Tavily MCP Client

**Files:**
- Create: `agents/web_qa/mcp_client.py`
- Create: `agents/web_qa/__init__.py`
- Test: `tests/test_web_qa_agent.py`

- [x] Implement text extraction from MCP responses.
- [x] Implement a small stdio client for `npx -y tavily-mcp@latest`.
- [x] Require `TAVILY_API_KEY`; return a clear setup error if missing.
- [x] Support `tavily_search` with `query`, `max_results`, and `search_depth`.
- [x] Always close any MCP process/session opened by the agent.

### Task 3: WebQAAgent

**Files:**
- Create: `agents/web_qa/agent.py`
- Modify: `models/agent_step_runner.py`
- Modify: `ui/agent_work_trace.mjs`
- Test: `tests/test_web_qa_agent.py`
- Test: `tests/test_agent_step_runner_latency.py`
- Test: `tests/test_ui_agent_work_trace.py`

- [x] Convert Tavily search results into normalized source dictionaries.
- [x] Synthesize answers via the existing model when available.
- [x] Fall back to a concise source-summary answer if model synthesis is unavailable.
- [x] Return `{"success": true, "result": markdown, "error": "", "complete": true}`.
- [x] Wire `run_routed_agent_step()` to call `WebQAAgent` for `agent == "web_qa"`.
- [x] Surface `web_qa` as `Web QA` in the agent work trace UI.

### Task 4: Verification

**Files:**
- No new files.

- [x] Run focused Web QA tests.
- [x] Run router regression tests.
- [x] Run status/step-runner tests.
- [x] Check no `npx`, `node`, or `python` child process created by the task remains.
