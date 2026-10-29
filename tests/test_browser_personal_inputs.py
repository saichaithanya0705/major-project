"""Personal form values must come from the human, before any browser write."""
from types import SimpleNamespace
import json
import pytest

from agents.browser.connected_runner import ConnectedBrowserRunner
from tests.test_connected_browser_runner import Client, decisions


def email_client(tmp_path):
    client = Client(tmp_path)
    client.nodes["e1"].update(type="email", label="Email")
    return client


async def test_invented_email_returns_question_before_typing(tmp_path):
    client = email_client(tmp_path)
    run = ConnectedBrowserRunner(client, decide=decisions(
        {"tool":"browser_type","arguments":{"target":"e1","text":"user@example.com"}},
        {"done":False,"summary":"Need details","evidence":[]}))
    result = await run.execute("Fill the application with my email address and age")
    assert result["success"] and result["result"]["awaiting_input"] and not result["complete"]
    assert not client.effects and client.nodes["e1"]["value"] == ""


async def test_entire_batch_is_checked_before_first_write(tmp_path):
    client = email_client(tmp_path)
    client.nodes["e3"].update(type="text", label="Project title", form=None)
    run = ConnectedBrowserRunner(client, decide=decisions({"tool":"browser_fill_form","arguments":{"fields":[
        {"target":"e3","type":"textbox","value":"Demo"},
        {"target":"e1","type":"textbox","value":"user@example.com"}]}}))
    result = await run.execute("Fill the project title with Demo and use my email")
    assert result["result"]["awaiting_input"] and not client.effects


@pytest.mark.parametrize("label,kind", [("Full name","text"),("Name","text"),("Age","number")])
async def test_invented_age_and_name_are_blocked_without_matching_url_digits(tmp_path,label,kind):
    client = Client(tmp_path)
    client.nodes["e1"].update(type=kind,label=label)
    run = ConnectedBrowserRunner(client,decide=decisions(
        {"tool":"browser_type","arguments":{"target":"e1","text":"25"}}))
    result = await run.execute("Fill my details on http://127.0.0.1:12588/form")
    # The user-directed link may create JARVIS's owned tab, but the invented
    # personal value must still be blocked before a field-write action.
    assert result["result"]["awaiting_input"]
    assert [name for name, _ in client.effects] == ["browser_tabs"]
    assert client.nodes["e1"]["value"] == ""


async def test_router_cannot_authorize_an_invented_personal_value(tmp_path):
    from models.shared.user_input_context import user_input_scope
    client = email_client(tmp_path)
    run = ConnectedBrowserRunner(client, decide=decisions(
        {"tool":"browser_type","arguments":{"target":"e1","text":"user@example.com"}}))
    with user_input_scope("Use my email in this form", "chat-a"):
        result = await run.execute("Fill the email with user@example.com")
    assert result["result"]["awaiting_input"] and not client.effects


async def test_personal_dropdown_cannot_bypass_the_value_guard(tmp_path):
    client = Client(tmp_path)
    client.nodes["e1"].update(tag="select",type="select-one",label="Age",selected=[])
    original = client.tool_schemas
    async def schemas():
        result = await original()
        result["browser_select_option"] = {"type":"object","properties":{
            "target":{"type":"string"},"values":{"type":"array","items":{"type":"string"}}},
            "required":["target","values"],"additionalProperties":False}
        return result
    client.tool_schemas = schemas
    run = ConnectedBrowserRunner(client,decide=decisions(
        {"tool":"browser_select_option","arguments":{"target":"e1","values":["25"]}}))
    result = await run.execute("Select my age on the application")
    assert result["result"]["awaiting_input"] and not client.effects


async def test_human_supplied_email_is_allowed_and_session_data_does_not_leak(tmp_path):
    from models.shared.user_input_context import user_input_scope
    client = email_client(tmp_path)
    action = {"tool":"browser_type","arguments":{"target":"e1","text":"presenter@example.test"}}
    run = ConnectedBrowserRunner(client, decide=decisions(action,
        {"done":True,"summary":"Filled the email","evidence":["Verified type"]},action))
    with user_input_scope("Use presenter@example.test as my email", "chat-a"):
        result = await run.execute("Fill the email")
    assert result["complete"] and len(client.effects) == 1
    with user_input_scope("Use my email", "chat-b"):
        result = await run.execute("Fill presenter@example.test in the email")
    assert result["result"]["awaiting_input"] and len(client.effects) == 1


async def test_same_chat_can_use_details_from_a_human_follow_up(tmp_path):
    from models.shared.user_input_context import user_input_scope
    client = email_client(tmp_path)
    run = ConnectedBrowserRunner(client, decide=decisions(
        {"done":False,"summary":"Ready for your next instruction","evidence":[]},
        {"tool":"browser_type","arguments":{"target":"e1","text":"presenter@example.test"}},
        {"done":True,"summary":"Filled the email","evidence":["Verified type"]}))
    with user_input_scope("My email is presenter@example.test", "chat-a"):
        await run.execute("Read the form")
    with user_input_scope("Fill it now", "chat-a"):
        result = await run.execute("Fill the email")
    assert result["complete"] and len(client.effects) == 1


async def test_batch_progress_names_each_verified_field_without_repeating_values(tmp_path):
    client = email_client(tmp_path)
    client.nodes["e3"].update(type="text",label="Full name",form=None)
    prompts = []
    async def decide(_system,user):
        prompts.append(json.loads(user))
        if len(prompts) == 1:
            return json.dumps({"tool":"browser_fill_form","arguments":{"fields":[
                {"target":"e3","type":"textbox","value":"Demo Presenter"},
                {"target":"e1","type":"textbox","value":"presenter@example.test"}]}})
        return json.dumps({"done":True,"summary":"Filled both fields","evidence":["Verified fill_form"]})
    result = await ConnectedBrowserRunner(client,decide=decide).execute(
        "Fill Full name with Demo Presenter and Email with presenter@example.test")
    assert result["complete"]
    progress = "\n".join(prompts[1]["verified_progress"])
    assert "Full name" in progress and "Email" in progress
    assert 'Verified field "Full name": requested value matches read-back.' in progress
    assert "Demo Presenter" not in progress and "presenter@example.test" not in progress


async def test_repeated_verified_typing_is_corrected_without_a_second_write(tmp_path):
    client = email_client(tmp_path)
    action = {"tool":"browser_type","arguments":{"target":"e1","text":"presenter@example.test"}}
    run = ConnectedBrowserRunner(client,decide=decisions(action,action,
        {"done":True,"summary":"Filled the email","evidence":["Verified type"]}))
    result = await run.execute("Fill my email with presenter@example.test")
    assert result["complete"] and len(client.effects) == 1


async def test_request_entrypoint_preserves_raw_input_and_resets_context():
    from models.runtime.request_entrypoint import run_gemini_request
    from models.shared.user_input_context import current_user_input
    observed = []
    async def run(**_): observed.append(current_user_input())
    await run_gemini_request(user_prompt="Raw human request",rapid_response_model="test",jarvis_model="test",
        session_id="chat-a",new_request_id=lambda:"test",log_assistant_event=lambda *_,**__:None,
        clean_text=lambda value,*_,**__:str(value),rapid_session_state=SimpleNamespace(normalize_session_id=lambda _:"chat-a"),
        build_rapid_orchestrator_deps=lambda **_:object(),run_rapid_request=run,model_factory=object,
        run_routed_agent_step=run,get_stored_screenshot=lambda:None,prepare_vision_screenshot=run,
        max_router_chain_steps=6,repeated_step_limit=3)
    assert observed[0].text == "Raw human request" and observed[0].session_id == "chat-a"
    assert current_user_input() is None
