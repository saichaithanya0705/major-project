import json
import shutil
import subprocess
from pathlib import Path
from html.parser import HTMLParser

import pytest


ROOT_DIR = Path(__file__).resolve().parent.parent


class _ParentMapParser(HTMLParser):
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, str | None]] = []
        self.parents: dict[str, str | None] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        element_id = attrs_dict.get("id")
        parent_id = self.stack[-1][1] if self.stack else None
        if element_id:
            self.parents[element_id] = parent_id
        if tag.lower() not in self._VOID_TAGS:
            self.stack.append((tag.lower(), element_id))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def _input_window_parent_map() -> dict[str, str | None]:
    parser = _ParentMapParser()
    parser.feed((ROOT_DIR / "ui" / "input.html").read_text(encoding="utf-8"))
    return parser.parents


def _run_node_module(script: str) -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for UI module contract tests")

    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def test_input_window_header_uses_compact_jarvis_actions_contract() -> None:
    input_html = (ROOT_DIR / "ui" / "input.html").read_text(encoding="utf-8")

    assert '<span id="chat-title">JARVIS</span>' in input_html
    assert "JARVIS Assistant" not in input_html
    assert 'id="chat-new"' in input_html
    assert 'id="chat-settings-toggle"' in input_html
    assert 'id="chat-settings-popover"' in input_html
    assert 'id="chat-settings-help"' in input_html
    assert 'id="chat-settings-history"' in input_html
    assert 'id="chat-shortcuts-toggle"' not in input_html
    assert 'id="chat-history-toggle"' not in input_html
    assert 'id="chat-stop"' not in input_html
    assert 'id="chat-hide"' not in input_html
    assert "Hide window" not in input_html
    assert "chat-guidance-hide-shortcut" not in input_html


def test_composer_action_swaps_between_send_and_stop_contract() -> None:
    input_html = (ROOT_DIR / "ui" / "input.html").read_text(encoding="utf-8")
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    input_window_css = (ROOT_DIR / "ui" / "input_window.css").read_text(encoding="utf-8")

    assert 'class="send-icon"' in input_html
    assert 'class="stop-icon"' in input_html
    assert "function updateComposerActionState()" in input_window_js
    assert "commandSend.dataset.mode = hasWork ? 'stop' : 'send';" in input_window_js
    assert "'Stop running actions'" in input_window_js
    assert "requestStopAll" in input_window_js
    assert "#command-send[data-mode=\"stop\"]" in input_window_css


def test_submit_command_routes_without_unconditional_screenshot_capture() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    start = input_window_js.index("function submitCommand()")
    end = input_window_js.index("commandInput?.addEventListener", start)
    submit_body = input_window_js[start:end]

    assert "event: 'overlay_input'" in submit_body
    assert "EXECUTION_PHASES.ROUTING" in submit_body
    assert "capture_screenshot" not in submit_body


def test_chat_response_command_finalizes_pending_assistant() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")

    assert "payload.command === 'chat_response'" in input_window_js
    assert "payload.responseText || payload.text || ''" in input_window_js
    assert "finalizePendingAssistant(responseText)" in input_window_js


def test_web_qa_status_is_trace_only_until_router_chat_response() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")

    assert "from './chat_reply_policy.mjs'" in input_window_js
    policy = _run_node_module(
        """
        const policy = await import('./ui/chat_reply_policy.mjs');
        process.stdout.write(JSON.stringify({
          rapid: policy.shouldDisplayReplyInChat({ source: 'rapid_response' }),
          rapidCase: policy.shouldDisplayReplyInChat({ source: ' RAPID_RESPONSE ' }),
          webQa: policy.shouldDisplayReplyInChat({ source: 'web_qa' }),
          trace: policy.shouldDisplayReplyInChat({ source: 'agent_work_trace' }),
          missingSource: policy.shouldDisplayReplyInChat({}),
        }));
        """
    )
    assert policy == {
        "rapid": True,
        "rapidCase": True,
        "webQa": False,
        "trace": False,
        "missingSource": True,
    }

    complete_block = input_window_js.split("payload.command === 'complete_status_bubble'", 1)[1].split(
        "if (payload.command === 'hide_status_bubble'",
        1,
    )[0]
    assert "applyAgentWorkTraceEvent(payload)" in complete_block
    assert "if (shouldDisplayReplyInChat(payload))" in complete_block
    assert "finalizePendingAssistant(responseText)" in complete_block
    assert "Checking result" in complete_block

    chat_response_block = input_window_js.split("payload.command === 'chat_response'", 1)[1].split(
        "if (payload.command === 'draw_text'",
        1,
    )[0]
    assert "finalizePendingAssistant(responseText)" in chat_response_block
    assert "applyFinalAssistantLifecycle(responseText, agentTrace)" in chat_response_block


def test_assistant_replies_render_structured_markdown_safely() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    input_window_css = (ROOT_DIR / "ui" / "input_window.css").read_text(encoding="utf-8")
    renderer_start = input_window_js.index("function normalizeRichMessageMarkdown")
    renderer_end = input_window_js.index("function ensurePendingAssistantTicker", renderer_start)
    renderer_block = input_window_js[renderer_start:renderer_end]

    assert "function renderRichMessageContent(content, text)" in input_window_js
    assert "content.classList.add('chat-msg-content--rich')" in input_window_js
    assert "appendInlineMarkdown(paragraph, paragraphText)" in renderer_block
    assert "document.createElement(level <= 2 ? 'h3' : 'h4')" in renderer_block
    assert "document.createElement(ordered ? 'ol' : 'ul')" in renderer_block
    assert "document.createElement('pre')" in renderer_block
    assert "document.createElement('blockquote')" in renderer_block
    assert "document.createElement('table')" in renderer_block
    assert "new URL(value, window.location.href)" in renderer_block
    assert "link.rel = 'noopener noreferrer'" in renderer_block
    assert "innerHTML" not in renderer_block

    assert ".chat-msg-content--rich" in input_window_css
    assert ".chat-rich-heading" in input_window_css
    assert ".chat-rich-table" in input_window_css
    assert ".chat-rich-code-block" in input_window_css
    assert ".chat-rich-link" in input_window_css


def test_input_window_shell_keeps_header_status_and_body_as_siblings() -> None:
    parents = _input_window_parent_map()

    assert parents["chat-header"] == "chat-shell"
    assert parents["chat-status"] == "chat-shell"
    assert parents["chat-body"] == "chat-shell"
    assert parents["chat-brand"] == "chat-header"
    assert parents["chat-actions"] == "chat-header"
    assert parents["chat-settings-menu"] == "chat-actions"
    assert parents["chat-settings-popover"] == "chat-settings-menu"
    assert parents["chat-help-panel"] == "chat-settings-popover"
