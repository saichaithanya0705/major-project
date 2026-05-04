"""
Browser task heuristics extracted from BrowserAgent.
"""

from __future__ import annotations

import os
import re

DEFAULT_STICKY_SITE_MARKERS = ("scopegrade",)
FAST_PATH_BLOCKING_MARKERS = (
    "ask",
    "ask it",
    "prompt",
    "message",
    "send",
    "submit",
    "fill",
    "form",
    "login",
    "log in",
    "sign in",
    "upload",
    "download",
    "click",
    "type",
    "select",
    "choose",
    "checkout",
    "add to cart",
)
PAGE_SUMMARY_MARKERS = (
    "summary",
    "summarize",
    "summarise",
    "tl;dr",
    "tldr",
    "overview",
    "key points",
)


def should_close_after_task(task: str) -> bool:
    lowered = task.lower()

    keep_open_markers = [
        "stay open",
        "keep open",
        "leave open",
        "do not close",
        "don't close",
    ]
    if any(marker in lowered for marker in keep_open_markers):
        return False

    close_markers = [
        "close the browser",
        "close browser",
        "close the window",
        "close window",
        "close the tab",
        "close tab",
        "quit browser",
        "exit browser",
    ]
    return any(marker in lowered for marker in close_markers)


def should_fallback_to_playwright(exc: Exception) -> bool:
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return True
    lowered = str(exc).lower()
    markers = [
        "failed to import",
        "no module named",
        "cannot import name",
        "unsupported operand type(s) for |",
    ]
    return any(marker in lowered for marker in markers)


def has_browser_interaction_intent(task: str) -> bool:
    lowered = (task or "").lower()
    for marker in FAST_PATH_BLOCKING_MARKERS:
        if " " in marker:
            if marker in lowered:
                return True
        elif re.search(rf"\b{re.escape(marker)}\b", lowered):
            return True
    return False


def should_summarize_page_content(task: str) -> bool:
    lowered = (task or "").lower()
    for marker in PAGE_SUMMARY_MARKERS:
        if " " in marker:
            if marker in lowered:
                return True
        elif re.search(rf"\b{re.escape(marker)}\b", lowered):
            return True
    return False


def should_extract_page_content(task: str) -> bool:
    lowered = " ".join((task or "").lower().split())
    if not lowered:
        return False
    if should_summarize_page_content(lowered):
        return True

    content_patterns = (
        r"\b(?:read|extract|scrape)\b.*\b(?:page|article|website|site|contents?|text)\b",
        r"\b(?:fetch|get|show|give)\b.*\b(?:page\s+contents?|contents?|page\s+text|article\s+text|text)\b",
        r"\bwhat\s+(?:does|is\s+on)\b.*\b(?:page|article|website|site)\b",
        r"\b(?:page|article|website|site)\b.*\b(?:says|contains)\b",
    )
    return any(re.search(pattern, lowered) for pattern in content_patterns)


def should_search_before_direct_navigation(task: str) -> bool:
    lowered = (task or "").lower()
    if "search" not in lowered:
        return False
    result_markers = (
        "open the starting point",
        "open starting point",
        "open the first",
        "open first",
        "open the top",
        "open top",
        "open best",
    )
    return any(marker in lowered for marker in result_markers)


def should_use_playwright_fast_path(task: str) -> bool:
    if has_browser_interaction_intent(task):
        return False
    if should_extract_page_content(task):
        return False
    if is_current_tab_context_task(task):
        return False
    if should_search_before_direct_navigation(task):
        return True
    if "search" in (task or "").lower():
        return False
    return extract_direct_url(task) is not None


def extract_direct_url(task: str) -> str | None:
    task = task.strip()
    if not task:
        return None

    url_match = re.search(r"https?://[^\s]+", task)
    if url_match:
        return url_match.group(0).rstrip(".,);")

    domain_match = re.search(r"\b([a-zA-Z0-9-]+\.(?:com|org|edu|gov|net|io|ai|co))\b", task)
    if domain_match:
        return f"https://{domain_match.group(1)}"

    localhost_match = re.search(
        r"\b(localhost|127\.0\.0\.1)(?:\s*:\s*|\s+)?(\d{2,5})?([/\w\-.?=&%+]*)",
        task,
        flags=re.IGNORECASE,
    )
    if localhost_match:
        host = localhost_match.group(1)
        port = localhost_match.group(2)
        path = (localhost_match.group(3) or "").strip()
        path = path.rstrip(".,);")
        normalized = f"http://{host}"
        if port:
            normalized += f":{port}"
        if path:
            if not path.startswith("/"):
                path = f"/{path}"
            normalized += path
        return normalized

    return None


def extract_available_file_paths_from_task(task: str) -> list[str]:
    """Extract likely local file paths from task text for upload whitelisting."""
    if not task:
        return []

    def is_url_like(value: str) -> bool:
        return bool(re.match(r"^(?:https?:)?//", value.strip(), flags=re.IGNORECASE))

    candidates: list[str] = []

    # Quoted chunks commonly contain explicit file paths.
    for quoted in re.findall(r"""['"]([^'"]+)['"]""", task):
        q = quoted.strip()
        if q and not is_url_like(q):
            candidates.append(q)

    path_scan_text = re.sub(r"https?://[^\s,;]+", " ", task, flags=re.IGNORECASE)

    # Also capture unquoted absolute/home-relative paths.
    for match in re.findall(
        r"""(?<!\w)(~\/[^\s,;]+|\/[^\s,;]+|[A-Za-z]:\\[^\s,;]+|\\\\[^\s,;]+)""",
        path_scan_text,
    ):
        m = str(match).strip()
        if m and not is_url_like(m):
            candidates.append(m)

    resolved: list[str] = []
    seen: set[str] = set()

    def add(path_value: str) -> None:
        p = str(path_value).strip()
        if not p:
            return
        # Trim surrounding punctuation that can appear in prose.
        p = p.strip(".,;:()[]{}'\"`")
        if not p or is_url_like(p) or p in seen:
            return
        seen.add(p)
        resolved.append(p)

    for candidate in candidates:
        # Skip obvious non-path tokens.
        if "/" not in candidate and "\\" not in candidate and "~" not in candidate:
            continue

        expanded = os.path.expandvars(os.path.expanduser(candidate))
        absolute = os.path.abspath(expanded)

        add(expanded)
        add(absolute)
        add(candidate)

        base = os.path.basename(expanded)
        if base:
            add(base)

    return resolved


def is_open_new_tab_task(task: str) -> bool:
    lowered = task.lower()
    markers = [
        "open a new browser tab",
        "open new browser tab",
        "open a new tab",
        "open new tab",
        "new tab",
    ]
    return any(marker in lowered for marker in markers)


def is_current_tab_context_task(task: str) -> bool:
    lowered = task.lower()
    markers = [
        "currently open",
        "current page",
        "current tab",
        "already open",
        "this page",
        "on the page",
        "on this page",
        "open page",
        "that is open",
        "page that is open",
    ]
    return any(marker in lowered for marker in markers)


def should_reuse_existing_page(
    task: str,
    sticky_site_markers: tuple[str, ...] = DEFAULT_STICKY_SITE_MARKERS,
) -> bool:
    lowered = task.lower()
    if is_current_tab_context_task(task):
        return True
    return any(marker in lowered for marker in sticky_site_markers)


def steer_task_for_existing_page(
    task: str,
    sticky_site_markers: tuple[str, ...] = DEFAULT_STICKY_SITE_MARKERS,
) -> str:
    """
    If the user indicates the target page is already open, prepend strict
    instructions to avoid search/navigation drift.
    """
    lowered = task.lower()
    wants_localhost = (
        ("localhost" in lowered)
        or ("127.0.0.1" in lowered)
        or any(marker in lowered for marker in sticky_site_markers)
    )

    if not should_reuse_existing_page(task, sticky_site_markers) and not wants_localhost:
        return task

    if wants_localhost:
        steering = (
            "HARD CONSTRAINT (LOCAL-SITE MODE):\n"
            "- You MUST use the currently open local-server page/tab in this browser session.\n"
            "- Do NOT perform web search.\n"
            "- Do NOT type the full task sentence into the browser address/search bar.\n"
            "- Do NOT navigate to unrelated public websites.\n"
            "- If a navigation is required, only use local-server URLs (e.g. http://127.0.0.1:PORT).\n"
            "- Prioritize interacting with the existing on-page UI to complete the task.\n\n"
            "Task:\n"
        )
        return f"{steering}{task}"

    steering = (
        "IMPORTANT EXECUTION CONSTRAINTS:\n"
        "- The target page is already open in the current browser session.\n"
        "- Stay on the currently open relevant tab/page.\n"
        "- Do NOT perform web search and do NOT navigate to unrelated sites.\n"
        "- Do NOT type the full task sentence into the browser address/search bar.\n"
        "- Only navigate if the task explicitly gives a direct URL.\n"
        "- Prioritize interacting with existing on-page UI to complete the task.\n\n"
        "Task:\n"
    )
    return f"{steering}{task}"


def must_avoid_search(
    task: str,
    sticky_site_markers: tuple[str, ...] = DEFAULT_STICKY_SITE_MARKERS,
) -> bool:
    lowered = task.lower()
    if should_reuse_existing_page(task, sticky_site_markers):
        return True
    if ("localhost" in lowered) or ("127.0.0.1" in lowered):
        return True
    return any(marker in lowered for marker in sticky_site_markers)


def task_to_search_query(task: str) -> str:
    cleaned = " ".join(task.split())
    if not cleaned:
        return "official website"
    content_match = re.search(
        r"\b(?:fetch|get|give|show|tell)\s+(?:me\s+)?(?:the\s+)?"
        r"(?:summary|overview|contents?|text)\s+(?:of|from|for)\s+(.+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if content_match:
        query = content_match.group(1).strip(" .,:;")
        if query:
            return query
    summarize_match = re.search(
        r"\b(?:summarize|summarise|read|extract|scrape)\s+(?:the\s+)?(.+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if summarize_match:
        query = summarize_match.group(1).strip(" .,:;")
        if query and query.lower() not in {"page", "this page", "current page"}:
            return query
    search_match = re.search(
        r"\bsearch\s+(?:for\s+)?(.+?)(?:\s+and\s+open\b|\s+then\s+open\b|$)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if search_match:
        query = search_match.group(1).strip(" .,:;")
        if query:
            return query
    if re.search(r"\b(go to|open|visit)\b", cleaned, flags=re.IGNORECASE):
        return cleaned
    return f"{cleaned} official website"


def build_fallback_summary(
    *,
    task: str,
    final_url: str,
    page_title: str,
    used_search: bool,
    used_headless: bool,
    action_mode: str = "direct_navigation",
) -> str:
    del task
    if action_mode == "new_tab":
        mode_text = "new-tab action"
    elif action_mode == "current_tab_context":
        mode_text = "current-tab context fallback"
    else:
        mode_text = "search fallback" if used_search else "direct navigation fallback"
    title_text = page_title.strip() if isinstance(page_title, str) else ""
    if used_headless:
        mode_text = f"{mode_text} (headless)"
    if title_text:
        return f"Browser task completed via {mode_text}: {title_text} ({final_url})"
    return f"Browser task completed via {mode_text}: {final_url}"
