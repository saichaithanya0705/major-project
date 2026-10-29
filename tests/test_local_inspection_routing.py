import pytest
import sys

from models.routing.routing_question_policy import is_direct_chat_request, is_source_grounded_qa_request
from models.routing.routing_guardrails import apply_routing_guardrails
from agents.cua_cli.direct_command_policy import extract_safe_direct_command


@pytest.mark.parametrize("prompt", [
    "what r the current running processes on my laptop?",
    "What programs are running on my PC?",
    "How much free RAM is available on my computer?",
    "Check disk space on this laptop",
])
def test_local_state_questions_require_local_observation(prompt):
    assert not is_direct_chat_request(prompt)
    assert not is_source_grounded_qa_request(prompt)
    result = apply_routing_guardrails(user_prompt=prompt,
        routing_result={"agent": "direct", "response_text": "Here are web instructions."},
        latest_screen_context=None)
    assert result.route == {"agent": "cua_cli", "task": prompt}


@pytest.mark.parametrize("prompt", [
    "How do I check running processes on my laptop?",
    "Search the web for how to check running processes on Windows",
    "What is the latest cyclone news in India?",
    "What is a computer process?",
])
def test_general_instructional_and_news_questions_keep_chat(prompt):
    assert is_direct_chat_request(prompt)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process inspection command")
def test_process_inspection_is_read_only_and_needs_no_model():
    command = extract_safe_direct_command("what r the current running processes on my laptop?")
    assert command is not None
    assert "Get-Process" in command.argv[-1]
    assert "Stop-Process" not in command.argv[-1]
    assert "CommandLine" not in command.argv[-1]
    assert extract_safe_direct_command("Stop processes on my laptop") is None
