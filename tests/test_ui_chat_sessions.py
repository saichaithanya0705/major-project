import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parent.parent


def _run_chat_sessions_eval(user_data_dir: Path, body: str):
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to validate ui/chat_sessions.js")

    script = (
        "const path = require('path');\n"
        "const { createChatSessionManager } = require(path.join(process.cwd(), 'ui', 'chat_sessions.js'));\n"
        "const userDataDir = process.env.USER_DATA_DIR;\n"
        "const app = { getPath: (name) => (name === 'userData' ? userDataDir : userDataDir) };\n"
        "const manager = createChatSessionManager({ app });\n"
        f"{body}\n"
    )
    env = os.environ.copy()
    env["USER_DATA_DIR"] = str(user_data_dir)
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=str(ROOT_DIR),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout.strip() or "null")


def test_create_save_and_load_chat_session_roundtrip(tmp_path: Path) -> None:
    result = _run_chat_sessions_eval(
        tmp_path,
        (
            "manager.initialize();\n"
            "const state = manager.getChatSessionState();\n"
            "const sessionId = state.currentSessionId;\n"
            "manager.saveChatSessionMessages(sessionId, [\n"
            "  { role: 'user', text: 'hello', ts: 1 },\n"
            "  { role: 'assistant', text: 'hi', ts: 2 },\n"
            "  { role: 'unknown', text: 'ignore me', ts: 3 }\n"
            "]);\n"
            "const loaded = manager.loadChatSessionData(sessionId);\n"
            "process.stdout.write(JSON.stringify({\n"
            "  sessionId,\n"
            "  messageCount: loaded.messages.length,\n"
            "  roles: loaded.messages.map((item) => item.role),\n"
            "}));"
        ),
    )

    assert result["sessionId"]
    assert result["messageCount"] == 2
    assert result["roles"] == ["user", "assistant"]


def test_archiving_current_session_moves_it_to_archived_list(tmp_path: Path) -> None:
    result = _run_chat_sessions_eval(
        tmp_path,
        (
            "manager.initialize();\n"
            "const state = manager.getChatSessionState();\n"
            "const archivedId = state.currentSessionId;\n"
            "manager.saveChatSessionMessages(archivedId, [{ role: 'user', text: 'persist this', ts: 1 }]);\n"
            "const nextState = manager.archiveChatSession(archivedId);\n"
            "const archivedIds = nextState.archivedSessions.map((item) => item.sessionId);\n"
            "process.stdout.write(JSON.stringify({\n"
            "  archivedId,\n"
            "  archivedIds,\n"
            "  currentSessionId: nextState.currentSessionId,\n"
            "}));"
        ),
    )

    assert result["archivedId"] in result["archivedIds"]
    assert result["currentSessionId"] != result["archivedId"]
