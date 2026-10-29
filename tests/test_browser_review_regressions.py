"""Regressions reproduced by the final review, including the actual private reader."""
import asyncio
import json
import shutil
import subprocess
import re
from pathlib import Path

import pytest

from agents.browser.connected_gateway import ELEMENT_STATE
from agents.browser.connected_runner import ConnectedBrowserRunner
from tests.test_connected_browser_runner import Client, decisions


def test_declared_node_floor_covers_locked_runtime_dependencies():
    root=Path(__file__).resolve().parents[1]/"integrations/playwright_mcp"
    package=json.loads((root/"package.json").read_text())
    lock=json.loads((root/"package-lock.json").read_text())
    floor=lambda text:int(re.search(r">=\s*(\d+)",text).group(1))
    declared=floor(package["engines"]["node"])
    required=max(floor(value["engines"]["node"]) for key,value in lock["packages"].items() if key and value.get("engines",{}).get("node", "").startswith(">="))
    assert declared >= required


def test_actual_reader_binds_sensitive_values_and_submitter_destination():
    script = r"""
const fn = eval('(' + JSON.parse(process.argv[1]) + ')');
globalThis.crypto = require('node:crypto').webcrypto;
globalThis.location = {href:'https://forms.example/application'};
const form = {id:'application',action:'https://forms.example/submit',method:'post',target:'_self',
  getAttribute:()=>null,querySelectorAll:()=>[password,button]};
const base = {isConnected:true,getAttribute:()=>null,closest:()=>form,form,labels:[]};
const password = {...base,tagName:'INPUT',type:'password',name:'password',value:'first-private-value'};
const button = {...base,tagName:'BUTTON',type:'submit',innerText:'Continue',
  formAction:'https://forms.example/submit',formMethod:'post',formTarget:'_self',
  getAttribute(name){return ({formaction:this.formAction,formmethod:this.formMethod,formtarget:this.formTarget})[name] ?? null;}};
globalThis.document = {activeElement:button};
(async()=>{const a=await fn(button);password.value='second-private-value';const b=await fn(button);
button.formAction='https://other.example/collect';const c=await fn(button);
console.log(JSON.stringify({sensitiveChanged:JSON.stringify(a)!==JSON.stringify(b),
  destinationChanged:JSON.stringify(b)!==JSON.stringify(c),states:[a,b,c]}));})();
"""
    result = subprocess.run([shutil.which("node") or "node", "-e", script, json.dumps(ELEMENT_STATE)], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert data["sensitiveChanged"] and data["destinationChanged"]
    assert "first-private-value" not in result.stdout and "second-private-value" not in result.stdout


async def test_submit_label_alone_cannot_prove_task_completion(tmp_path):
    client = Client(tmp_path)
    finish = {"done":True,"summary":"Application submitted successfully", "evidence":["Submit"]}
    result = await ConnectedBrowserRunner(client, decide=decisions(finish,finish,finish)).execute("Submit the application")
    assert not result["complete"] and not client.effects


async def test_negative_submission_report_does_not_require_a_post(tmp_path):
    client = Client(tmp_path)
    finish = {"done":True,"summary":"The page says Submit. No forms were submitted.","evidence":["Submit"]}
    result = await ConnectedBrowserRunner(client,decide=decisions(finish,finish,finish)).execute("Read the page; do not submit any forms")
    assert result["complete"] and not client.effects


async def test_submission_without_observed_acceptance_stops_without_replay(tmp_path):
    client = Client(tmp_path)
    client.emit_receipt = False
    async def approve(_): return True
    result = await ConnectedBrowserRunner(client, confirm=approve, decide=decisions(
        {"tool":"browser_click","arguments":{"target":"e2"}},
        {"tool":"browser_click","arguments":{"target":"e2"}}
    )).execute("Submit the application")
    assert not result["complete"] and len(client.effects) == 1
    assert "acceptance could not be verified" in result["error"]


async def test_closed_selected_tab_cannot_leak_a_replacement_page(tmp_path):
    from agents.browser.connected_gateway import StalePageError
    client = Client(tmp_path)
    prompts = []
    async def decide(_system,user):
        prompts.append(user)
        if len(prompts) == 1:
            client.tab_id = "private-neighbor"
            client.snapshot = '- paragraph "Synthetic private neighbor data" [ref=e1]'
            return json.dumps({"tool":"browser_click","arguments":{"target":"e2"}})
        return json.dumps({"done":False,"summary":"Need input", "evidence":[]})
    result = await ConnectedBrowserRunner(client, decide=decide).execute("Open the details button")
    assert not result["complete"] and not client.effects
    assert len(prompts) == 1 and "Synthetic private neighbor data" not in "".join(prompts)


async def test_repeated_connect_without_token_cannot_read_a_replacement_tab(tmp_path,monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_MCP_EXTENSION_TOKEN",raising=False)
    client=Client(tmp_path)
    client.extension=True
    run=ConnectedBrowserRunner(client)
    await run.connect()
    if run.state == "awaiting_tab_selection": await run.select_tab(0)
    client.tab_id="replacement-tab"
    result=await run.execute("Read this page")
    assert not result["complete"]
    await run.connect()
    await run.connect()
    assert run.state == "awaiting_tab_selection"


async def test_model_timeout_is_not_reported_as_expired_task_budget(tmp_path):
    async def timeout(*_): raise TimeoutError()
    result=await ConnectedBrowserRunner(Client(tmp_path),decide=timeout).execute("Read the page")
    assert "model" in result["error"].lower() and "active-time limit" not in str(result)


async def test_approval_wait_is_excluded_from_active_deadline(tmp_path,monkeypatch):
    from agents.browser import connected_runner
    monkeypatch.setattr(connected_runner,"ACTIVE_SECONDS",0.08)
    client = Client(tmp_path)
    async def approve(_): await asyncio.sleep(0.12); return True
    run = ConnectedBrowserRunner(client, confirm=approve, decide=decisions(
        {"tool":"browser_click","arguments":{"target":"e2"}},
        {"done":True,"summary":"Application submitted", "evidence":["Verified submission outcome"]}
    ))
    assert (await run.execute("Submit the application"))["complete"]


async def test_active_deadline_also_bounds_tool_execution(tmp_path, monkeypatch):
    from agents.browser import connected_runner
    monkeypatch.setattr(connected_runner,"ACTIVE_SECONDS",0.03,raising=False)
    client = Client(tmp_path)
    original = client.call_result
    async def call(name,args=None):
        if name == "browser_type": await asyncio.sleep(0.1)
        return await original(name,args)
    client.call_result = call
    result = await ConnectedBrowserRunner(client, decide=decisions(
        {"tool":"browser_type","arguments":{"target":"e1","text":"Demo"}},
        {"done":True,"summary":"Filled", "evidence":["Verified type"]}
    )).execute("Fill the name with Demo")
    assert not result["complete"] and not client.effects


async def test_browser_question_returns_to_chat_without_replanning():
    from types import SimpleNamespace
    from models.orchestrator_adapters import plan_from_route
    from models.rapid_step_execution_runtime import execute_delegated_step
    replies = []
    history = []
    async def step(**kwargs):
        return {"agent":"browser","task":"Fill the application", "success":True,"complete":False,
            "message":"Choose a browser tab first.","source":"browser_use", "metadata":{"awaiting_input":True}}
    deps = SimpleNamespace(run_routed_agent_step=step, prepare_vision_screenshot=None,
        record_step_context=lambda *_:None, append_rapid_history=lambda *args:history.append(args),
        log_assistant_event=lambda *_,**__:None, clean_text=lambda value,*_:str(value),
        routing_task_text=lambda route:route["task"], finalize_direct_response_text=lambda **kwargs:kwargs["text"],
        router_tool_map={"direct_response":lambda **kwargs:replies.append(kwargs["text"])})
    route={"agent":"browser","task":"Fill the application"}
    plan=plan_from_route("Fill the application",route,max_parallel=1)
    result=await execute_delegated_step(model=object(),user_prompt="Fill the application",routing_result=route,
        orchestration_plan=plan,orchestration_task=plan.tasks[0],chain_steps=[],jarvis_model="test",request_id="test",deps=deps)
    assert result.disposition == "awaiting_input" and replies == ["Choose a browser tab first."]
    assert sum(role == "assistant" and text == "Choose a browser tab first." for role,text,_ in history) == 1
