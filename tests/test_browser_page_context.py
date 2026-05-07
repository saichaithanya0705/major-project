import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.browser.page_context import (
    MAIN_CONTENT_SCRIPT,
    PageContext,
    clean_page_text,
    extractive_summary,
    format_page_context_response,
    truncate_words,
)


def test_clean_page_text_collapses_spaces_and_blank_runs() -> None:
    raw = "  Heading  \r\n\r\n\r\n  First   paragraph.  \n\tSecond line.  "
    assert clean_page_text(raw) == "Heading\n\nFirst paragraph.\nSecond line."


def test_summary_selects_first_readable_sentences() -> None:
    text = (
        "First sentence explains the page. Second sentence adds detail. "
        "Third sentence adds another detail. Fourth sentence should still fit. "
        "Fifth sentence is enough. Sixth sentence should be clipped."
    )
    summary = extractive_summary(text, max_chars=160, max_sentences=5)
    assert "First sentence explains the page." in summary
    assert "Fifth sentence is enough." in summary
    assert "Sixth sentence should be clipped." not in summary


def test_format_page_context_response_for_headings() -> None:
    context = PageContext(
        title="Example Docs",
        url="https://example.com/docs",
        headings=["Install", "Usage", "Troubleshooting"],
        text="Install\n\nUsage\n\nTroubleshooting",
    )
    response = format_page_context_response(
        task="read the headings on this page",
        context=context,
    )
    assert response.startswith("Headings from Example Docs (https://example.com/docs):")
    assert "- Install" in response
    assert "- Usage" in response
    assert "- Troubleshooting" in response


def test_format_page_context_response_for_summary() -> None:
    context = PageContext(
        title="World War I - Wikipedia",
        url="https://en.wikipedia.org/wiki/World_War_I",
        headings=["History", "Course of the war"],
        text=(
            "World War I was a global conflict between two coalitions. "
            "The war lasted from 1914 to 1918 and reshaped Europe."
        ),
    )
    response = format_page_context_response(
        task="summarize this page",
        context=context,
    )
    assert response.startswith("Summary of World War I - Wikipedia")
    assert "global conflict between two coalitions" in response


def test_summary_request_takes_priority_over_sections_word() -> None:
    context = PageContext(
        title="Example Docs",
        url="https://example.com/docs",
        headings=["Install", "Usage"],
        text=(
            "The installation section explains setup requirements. "
            "The usage section describes common workflows."
        ),
    )
    response = format_page_context_response(
        task="summarize the sections on this page",
        context=context,
    )
    assert response.startswith("Summary of Example Docs (https://example.com/docs):")
    assert not response.startswith("Headings from")


def test_main_content_script_limits_browser_text_extraction() -> None:
    assert "maxTextChars" in MAIN_CONTENT_SCRIPT
    assert "maxBlocks" in MAIN_CONTENT_SCRIPT
    assert "truncated" in MAIN_CONTENT_SCRIPT
    assert ".slice(0, maxTextChars)" in MAIN_CONTENT_SCRIPT


def test_truncate_words_respects_max_chars_budget() -> None:
    text = "alpha beta gamma delta"
    assert truncate_words(text, 10) == "alpha..."
    assert truncate_words(text, 3) == "..."
    assert truncate_words(text, 2) == ".."
    assert truncate_words(text, 1) == "."
    assert truncate_words(text, 0) == ""
    for max_chars in range(0, 12):
        assert len(truncate_words(text, max_chars)) <= max_chars


if __name__ == "__main__":
    test_clean_page_text_collapses_spaces_and_blank_runs()
    test_summary_selects_first_readable_sentences()
    test_format_page_context_response_for_headings()
    test_format_page_context_response_for_summary()
    test_summary_request_takes_priority_over_sections_word()
    test_main_content_script_limits_browser_text_extraction()
    test_truncate_words_respects_max_chars_budget()
    print("PASS")
