from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_delete_chat_uses_in_app_confirmation_dialog() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    input_window_css = (ROOT_DIR / "ui" / "input_window.css").read_text(encoding="utf-8")

    assert "window.confirm" not in input_window_js
    assert "delete-confirm-dialog" in input_window_js
    assert "role', 'dialog'" in input_window_js
    assert "aria-modal', 'true'" in input_window_js
    assert "confirmDeleteSession" in input_window_js
    assert "cancelDeleteConfirmation" in input_window_js
    assert "window.api.deleteChatSession" in input_window_js
    assert ".delete-confirm-dialog" in input_window_css
    assert ".delete-confirm-overlay" in input_window_css


def test_archived_history_has_delete_all_icon_button_contract() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    input_window_css = (ROOT_DIR / "ui" / "input_window.css").read_text(encoding="utf-8")
    preload_js = (ROOT_DIR / "ui" / "preload.js").read_text(encoding="utf-8")

    assert "historyDeleteAllArchived" in input_window_js
    assert "history-delete-all-archived" in input_window_js
    assert "historyPanelHeader.insertBefore" in input_window_js
    assert "title = 'Delete all'" in input_window_js
    assert "aria-label', 'Delete all archived chats'" in input_window_js
    assert "window.api.deleteArchivedChatSessions" in input_window_js
    assert "deleteArchivedChatSessions" in preload_js
    assert ".history-delete-all-archived" in input_window_css
