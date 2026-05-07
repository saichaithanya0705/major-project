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


def test_chat_session_preserves_assistant_agent_trace(tmp_path: Path) -> None:
    result = _run_chat_sessions_eval(
        tmp_path,
        (
            "manager.initialize();\n"
            "const state = manager.getChatSessionState();\n"
            "const sessionId = state.currentSessionId;\n"
            "manager.saveChatSessionMessages(sessionId, [\n"
            "  {\n"
            "    role: 'assistant',\n"
            "    text: 'Done',\n"
            "    ts: 2,\n"
            "    agentTrace: {\n"
            "      isOpen: false,\n"
            "      status: 'completed',\n"
            "      summary: 'CLI task completed.',\n"
            "      entries: [\n"
            "        { label: 'CLI', source: 'cua_cli', status: 'running', text: 'Running CLI task...' },\n"
            "        { label: 'CLI', source: 'cua_cli', status: 'completed', text: 'CLI task completed.' }\n"
            "      ]\n"
            "    }\n"
            "  }\n"
            "]);\n"
            "const loaded = manager.loadChatSessionData(sessionId);\n"
            "process.stdout.write(JSON.stringify(loaded.messages[0]));"
        ),
    )

    assert result["role"] == "assistant"
    assert result["agentTrace"]["isOpen"] is False
    assert result["agentTrace"]["status"] == "completed"
    assert result["agentTrace"]["summary"] == "CLI task completed."
    assert result["agentTrace"]["entries"][-1]["text"] == "CLI task completed."


def test_chat_session_preserves_assistant_vision_artifact(tmp_path: Path) -> None:
    result = _run_chat_sessions_eval(
        tmp_path,
        (
            "manager.initialize();\n"
            "const state = manager.getChatSessionState();\n"
            "const sessionId = state.currentSessionId;\n"
            "manager.saveChatSessionMessages(sessionId, [\n"
            "  {\n"
            "    role: 'assistant',\n"
            "    text: 'Screen analysis snapshot',\n"
            "    ts: 2,\n"
            "    artifacts: [\n"
            "      {\n"
            "        kind: 'vision_screenshot',\n"
            "        title: 'Analyzed screen',\n"
            "        imageDataUrl: 'data:image/png;base64,iVBORw0KGgo=',\n"
            "        width: 1920,\n"
            "        height: 1080,\n"
            "        outlineCount: 7\n"
            "      }\n"
            "    ]\n"
            "  }\n"
            "]);\n"
            "const loaded = manager.loadChatSessionData(sessionId);\n"
            "process.stdout.write(JSON.stringify(loaded.messages[0]));"
        ),
    )

    assert result["role"] == "assistant"
    assert result["artifacts"][0]["kind"] == "vision_screenshot"
    assert result["artifacts"][0]["width"] == 1920
    assert result["artifacts"][0]["height"] == 1080
    assert result["artifacts"][0]["outlineCount"] == 7
    assert result["artifacts"][0]["imageDataUrl"].startswith("data:image/png;base64,")


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


def test_unarchiving_session_restores_it_to_active_current_chat(tmp_path: Path) -> None:
    result = _run_chat_sessions_eval(
        tmp_path,
        (
            "manager.initialize();\n"
            "const state = manager.getChatSessionState();\n"
            "const sessionId = state.currentSessionId;\n"
            "manager.saveChatSessionMessages(sessionId, [{ role: 'user', text: 'reuse this later', ts: 1 }]);\n"
            "manager.archiveChatSession(sessionId);\n"
            "const restoredState = manager.unarchiveChatSession(sessionId);\n"
            "const saveResult = manager.saveChatSessionMessages(sessionId, [\n"
            "  { role: 'user', text: 'reuse this later', ts: 1 },\n"
            "  { role: 'assistant', text: 'ready again', ts: 2 }\n"
            "]);\n"
            "const activeIds = restoredState.activeSessions.map((item) => item.sessionId);\n"
            "const archivedIds = restoredState.archivedSessions.map((item) => item.sessionId);\n"
            "const restored = manager.loadChatSessionData(sessionId);\n"
            "process.stdout.write(JSON.stringify({\n"
            "  sessionId,\n"
            "  currentSessionId: restoredState.currentSessionId,\n"
            "  activeIds,\n"
            "  archivedIds,\n"
            "  restoredArchivedAt: restored.archivedAt,\n"
            "  saveReadOnly: saveResult.readOnly,\n"
            "  messageCount: restored.messages.length,\n"
            "}));"
        ),
    )

    assert result["currentSessionId"] == result["sessionId"]
    assert result["sessionId"] in result["activeIds"]
    assert result["sessionId"] not in result["archivedIds"]
    assert result["restoredArchivedAt"] is None
    assert result["saveReadOnly"] is False
    assert result["messageCount"] == 2


def test_deleting_archived_session_removes_it_from_history_and_disk(tmp_path: Path) -> None:
    result = _run_chat_sessions_eval(
        tmp_path,
        (
            "const fs = require('fs');\n"
            "manager.initialize();\n"
            "const state = manager.getChatSessionState();\n"
            "const sessionId = state.currentSessionId;\n"
            "manager.saveChatSessionMessages(sessionId, [{ role: 'user', text: 'remove this', ts: 1 }]);\n"
            "manager.archiveChatSession(sessionId);\n"
            "const sessionPath = path.join(userDataDir, 'chat_sessions', `${sessionId}.json`);\n"
            "const deleteState = manager.deleteChatSession(sessionId);\n"
            "process.stdout.write(JSON.stringify({\n"
            "  sessionId,\n"
            "  existsAfterDelete: fs.existsSync(sessionPath),\n"
            "  activeIds: deleteState.activeSessions.map((item) => item.sessionId),\n"
            "  archivedIds: deleteState.archivedSessions.map((item) => item.sessionId),\n"
            "}));"
        ),
    )

    assert result["existsAfterDelete"] is False
    assert result["sessionId"] not in result["activeIds"]
    assert result["sessionId"] not in result["archivedIds"]


def test_deleting_all_archived_sessions_leaves_active_chats_intact(tmp_path: Path) -> None:
    result = _run_chat_sessions_eval(
        tmp_path,
        (
            "const fs = require('fs');\n"
            "manager.initialize();\n"
            "const firstArchivedId = manager.getChatSessionState().currentSessionId;\n"
            "manager.saveChatSessionMessages(firstArchivedId, [{ role: 'user', text: 'archive one', ts: 1 }]);\n"
            "manager.archiveChatSession(firstArchivedId);\n"
            "const secondArchived = manager.createChatSession(true);\n"
            "const secondArchivedId = secondArchived.sessionId;\n"
            "manager.saveChatSessionMessages(secondArchivedId, [{ role: 'user', text: 'archive two', ts: 2 }]);\n"
            "manager.archiveChatSession(secondArchivedId);\n"
            "const active = manager.createChatSession(true);\n"
            "const activeId = active.sessionId;\n"
            "manager.saveChatSessionMessages(activeId, [{ role: 'user', text: 'keep me', ts: 3 }]);\n"
            "const firstPath = path.join(userDataDir, 'chat_sessions', `${firstArchivedId}.json`);\n"
            "const secondPath = path.join(userDataDir, 'chat_sessions', `${secondArchivedId}.json`);\n"
            "const activePath = path.join(userDataDir, 'chat_sessions', `${activeId}.json`);\n"
            "const deleteState = manager.deleteArchivedChatSessions();\n"
            "process.stdout.write(JSON.stringify({\n"
            "  firstArchivedId,\n"
            "  secondArchivedId,\n"
            "  activeId,\n"
            "  firstExists: fs.existsSync(firstPath),\n"
            "  secondExists: fs.existsSync(secondPath),\n"
            "  activeExists: fs.existsSync(activePath),\n"
            "  activeIds: deleteState.activeSessions.map((item) => item.sessionId),\n"
            "  archivedIds: deleteState.archivedSessions.map((item) => item.sessionId),\n"
            "  currentSessionId: deleteState.currentSessionId,\n"
            "}));"
        ),
    )

    assert result["firstExists"] is False
    assert result["secondExists"] is False
    assert result["activeExists"] is True
    assert result["archivedIds"] == []
    assert result["activeId"] in result["activeIds"]
    assert result["currentSessionId"] == result["activeId"]
