# SPDX-License-Identifier: GPL-3.0-or-later
"""Studio providers (D252) against fake API answers: requests are well formed, answers become turns."""
import json
import types

import pytest

from kimbim.agent import providers
from kimbim.agent.providers import Call

TOOLS = [{"name": "project_info", "description": "Describe the project.", "input_schema": {"type": "object",
                                                                                          "properties": {}}}]


def test_openai_responses_round_trip(monkeypatch):
    monkeypatch.setattr(providers, "_key", lambda name: "sk-test")
    sent = []

    def post(url, key, body, timeout=600):
        sent.append((url, body))
        if len(sent) == 1:
            return {"status": "completed", "output": [
                {"type": "reasoning", "summary": [{"text": "Read first."}]},
                {"type": "message", "content": [{"type": "output_text", "text": "Reading"}]},
                {"type": "function_call", "call_id": "c1", "name": "project_info", "arguments": "{}"}]}
        return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text",
                                                                                   "text": "Two levels."}]}]}

    p = providers.OpenAIProvider("system", TOOLS, model="m", effort="low", base_url="https://x.test/v1", post=post)
    p.add_user("How many levels?")
    turn = p.step()
    assert turn.text == "Reading" and turn.reasoning == "Read first." and turn.calls[0].name == "project_info"
    url, body = sent[0]
    assert url == "https://x.test/v1/responses" and body["reasoning"]["effort"] == "low"
    assert body["tools"][0]["name"] == "project_info" and body["instructions"] == "system"
    p.add_results([(turn.calls[0], '{"ok": true}', True, "")], "Architect: hurry")
    assert p.step().text == "Two levels."
    items = sent[1][1]["input"]
    assert {"type": "function_call_output", "call_id": "c1", "output": '{"ok": true}'} in items
    assert items[-1] == {"role": "user", "content": "Architect: hurry"}


def test_openai_falls_back_to_chat_completions(monkeypatch):
    monkeypatch.setattr(providers, "_key", lambda name: "sk-test")

    def post(url, key, body, timeout=600):
        if url.endswith("/responses"):
            raise providers.ProviderError("the provider answered 404: not found")
        return {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": "",
                "tool_calls": [{"id": "t1", "function": {"name": "project_info", "arguments": "{}"}}]}}]}

    p = providers.OpenAIProvider("s", TOOLS, post=post)
    p.add_user("hi")
    assert p.step().calls[0].id == "t1" and p.chat


class _Block:
    def __init__(self, **kw):
        self.kw = kw

    def model_dump(self, exclude_none=True):
        return dict(self.kw)


class _Stream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.message


def test_anthropic_request_and_turn(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setattr(providers, "_key", lambda name: "sk-ant-test")
    p = providers.AnthropicProvider("system", TOOLS, effort="high")
    seen = {}

    def stream(**kwargs):
        seen.update(kwargs)
        usage = _Block(input_tokens=10, output_tokens=5)
        return _Stream(types.SimpleNamespace(stop_reason="tool_use", usage=usage, content=[
            _Block(type="thinking", thinking="Check the levels.", signature="x"),
            _Block(type="text", text="Reading"),
            _Block(type="tool_use", id="tu1", name="project_info", input={})]))

    p.client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(stream=stream)))
    p.add_user("How many levels?")
    turn = p.step()
    assert seen["model"] == "claude-opus-5-5" and seen["thinking"]["type"] == "adaptive"
    assert seen["output_config"] == {"effort": "high"} and "compact-2026-01-12" in seen["betas"]
    assert seen["tools"][-1]["cache_control"] == {"type": "ephemeral"}  # the tool list is cached
    assert turn.text == "Reading" and turn.reasoning == "Check the levels." and turn.calls == [Call("tu1", "project_info", {})]
    # the assistant blocks go back unchanged (thinking included), then the results with steering beside them
    p.add_results([(turn.calls[0], '{"ok": true}', True, "")], "Architect: hurry")
    assert p.messages[1]["content"][0]["type"] == "thinking"
    last = p.messages[-1]["content"]
    assert last[0]["type"] == "tool_result" and last[0]["tool_use_id"] == "tu1" and last[-1]["text"] == "Architect: hurry"


def test_anthropic_without_credentials_is_a_clear_error(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setattr(providers, "_key", lambda name: "")
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(providers.os.path, "isdir", lambda p: False)
    with pytest.raises(providers.ProviderError, match="no Anthropic credentials"):
        providers.AnthropicProvider("s", TOOLS)
