"""
Checks for extracted browser task-policy helpers.

Usage:
    python tests/test_browser_task_policy_boundary.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.browser.task_policy import (
    build_fallback_summary,
    extract_available_file_paths_from_task,
    extract_direct_url,
    has_browser_interaction_intent,
    is_current_tab_context_task,
    is_open_new_tab_task,
    must_avoid_search,
    should_close_after_task,
    should_extract_page_content,
    should_fallback_to_playwright,
    should_reuse_existing_page,
    should_summarize_page_content,
    should_use_playwright_fast_path,
    steer_task_for_existing_page,
    task_to_search_query,
)


def run_checks() -> None:
    assert should_close_after_task("open page then close browser")
    assert not should_close_after_task("open page and keep open")

    assert should_fallback_to_playwright(ModuleNotFoundError("No module named x"))
    assert not should_fallback_to_playwright(RuntimeError("task execution failed"))

    assert extract_direct_url("Go to https://example.com/docs") == "https://example.com/docs"
    assert extract_direct_url("open stanford.edu") == "https://stanford.edu"
    assert extract_direct_url("open localhost 3000/dashboard") == "http://localhost:3000/dashboard"
    assert extract_direct_url("search for docs") is None

    paths = extract_available_file_paths_from_task(
        r'Upload "C:\Users\SAI\Desktop\homework.zip" to this page'
    )
    assert any("homework.zip" in p for p in paths), paths

    assert is_open_new_tab_task("Please open a new browser tab")
    assert is_current_tab_context_task("On the currently open page, click submit")
    assert should_reuse_existing_page("On the currently open page, click submit")
    assert should_reuse_existing_page("Open ScopeGrade and upload file")

    assert must_avoid_search("Open localhost:3000")
    assert not must_avoid_search("Open youtube.com")

    steered = steer_task_for_existing_page("On localhost:3000, submit the current form")
    assert "hard constraint (local-site mode)" in steered.lower(), steered
    assert "do not perform web search" in steered.lower(), steered

    plain = steer_task_for_existing_page("Open youtube.com")
    assert plain == "Open youtube.com", plain

    assert task_to_search_query("Go to OpenAI") == "Go to OpenAI"
    assert task_to_search_query("OpenAI docs").endswith("official website")
    assert task_to_search_query("fetch me the summary of world war 1 wikipedia page") == (
        "world war 1 wikipedia page"
    )
    chatgpt_task = "goto chat.openai.com website and ask it for top 3 ml learning resources"
    assert has_browser_interaction_intent(chatgpt_task), chatgpt_task
    assert not should_use_playwright_fast_path(chatgpt_task), chatgpt_task
    assert not has_browser_interaction_intent("open the task tracker homepage")
    assert should_extract_page_content("fetch me the summary of world war 1 wikipedia page")
    assert should_summarize_page_content("open https://example.com and summarize the page")
    assert should_extract_page_content("read the contents of the currently open page")
    assert not should_extract_page_content("open youtube.com")
    assert not should_use_playwright_fast_path("open https://example.com and summarize the page")

    summary = build_fallback_summary(
        task="open docs",
        final_url="https://example.com",
        page_title="Example",
        used_search=False,
        used_headless=True,
    )
    assert "direct navigation fallback (headless)" in summary.lower(), summary
    assert "Example" in summary, summary


if __name__ == "__main__":
    run_checks()
    print("[test_browser_task_policy_boundary] All checks passed.")
