from pathlib import Path
from html.parser import HTMLParser


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
