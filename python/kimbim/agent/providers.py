# SPDX-License-Identifier: GPL-3.0-or-later
"""Model providers for studio sessions (D252): one interface, two adapters.

A provider keeps its conversation in its own native shape and offers:

- `add_user(text)` — a message from the architect (or the brief);
- `step()` — one model call; the assistant output is appended to the history and returned as a `Turn`
  (its text, the tool calls it asked for, and a short reasoning summary when the provider gives one);
- `add_results(results, note)` — the tool results for the last turn's calls, plus optional architect text that
  arrived meanwhile (steering lands next to the results, so it reaches the model mid-run);
- `size()` — a rough size of the history in characters, for the runner's compaction decision;
- `reset(text)` — start again from a summary (the runner's own compaction, used where the provider has none).

`AnthropicProvider` uses the official SDK (adaptive thinking with an effort, streaming, prompt caching,
server-side compaction, refusal fallbacks). `OpenAIProvider` speaks the OpenAI Responses API (reasoning effort)
over the same raw HTTP the in-app Assistant uses, for any OpenAI-compatible endpoint, falling back to Chat
Completions when an endpoint has no Responses API.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

ANTHROPIC_MODEL = "claude-opus-5-5"
OPENAI_DEFAULT = "https://api.openai.com/v1"


class ProviderError(Exception):
    def __init__(self, message: str, retry: bool = False):
        super().__init__(message)
        self.message, self.retry = message, retry


@dataclass
class Call:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    text: str = ""
    calls: list[Call] = field(default_factory=list)
    reasoning: str = ""
    stop: str = ""
    usage: dict = field(default_factory=dict)


IMAGE_BYTES = 3_500_000  # a snapshot larger than this is not sent to the model


def _image(path: str) -> tuple[str, str] | None:
    """(media type, base64) of a PNG/JPEG snapshot, or None."""
    if not path:
        return None
    import base64
    suffix = os.path.splitext(path)[1].lower()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(suffix)
    try:
        if media is None or os.path.getsize(path) > IMAGE_BYTES:
            return None
        with open(path, "rb") as f:
            return media, base64.standard_b64encode(f.read()).decode("ascii")
    except OSError:
        return None


def _key(provider: str) -> str:
    from .credentials import KeyStoreError, get_key
    try:
        return get_key(provider) or ""
    except KeyStoreError:
        return ""


# ---------------------------------------------------------------- Anthropic (official SDK)

class AnthropicProvider:
    name = "anthropic"

    def __init__(self, system: str, tools: list[dict], model: str = "", effort: str = "high",
                 base_url: str = "", max_tokens: int = 64000):
        import anthropic  # the SDK is only needed when this provider is chosen
        self._anthropic = anthropic
        key = _key("anthropic")
        kwargs = {"max_retries": 4}
        if key:
            kwargs["api_key"] = key
        if base_url:
            kwargs["base_url"] = base_url
        try:
            self.client = anthropic.Anthropic(**kwargs)
        except anthropic.AnthropicError as ex:
            raise ProviderError(f"no Anthropic credentials: {ex}. Set the key in Preferences › Assistant "
                                "or ANTHROPIC_API_KEY.") from None
        self.model = model or ANTHROPIC_MODEL
        self.effort = effort or "high"
        self.max_tokens = max_tokens
        self.system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        self.tools = [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                      for t in tools]
        if self.tools:  # the tool list is the biggest stable prefix: cache it
            self.tools[-1] = {**self.tools[-1], "cache_control": {"type": "ephemeral"}}
        self.messages: list[dict] = []

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": [{"type": "text", "text": text}]})

    def add_results(self, results: list[tuple], note: str = "") -> None:
        content = []
        for call, body, ok, *rest in results:
            image = _image(rest[0] if rest else "")
            inner = [{"type": "text", "text": body}]
            if image:
                inner.append({"type": "image", "source": {"type": "base64", "media_type": image[0],
                                                           "data": image[1]}})
            content.append({"type": "tool_result", "tool_use_id": call.id, "content": inner,
                            **({"is_error": True} if not ok else {})})
        if note:
            content.append({"type": "text", "text": note})
        self.messages.append({"role": "user", "content": content})

    def size(self) -> int:
        return len(json.dumps(self.messages, default=str))

    def reset(self, text: str) -> None:
        self.messages = []
        self.add_user(text)

    def step(self) -> Turn:
        a = self._anthropic
        betas = ["compact-2026-01-12", "server-side-fallback-2026-07-01"]
        try:
            with self.client.beta.messages.stream(
                    model=self.model, max_tokens=self.max_tokens, system=self.system, tools=self.tools,
                    messages=self.messages, betas=betas,
                    thinking={"type": "adaptive", "display": "summarized"},
                    output_config={"effort": self.effort},
                    context_management={"edits": [{"type": "compact_20260112"}]},
                    fallbacks="default") as stream:
                response = stream.get_final_message()
        except a.RateLimitError as ex:
            raise ProviderError(f"rate limited: {ex}", retry=True) from None
        except a.APIStatusError as ex:
            raise ProviderError(f"the provider answered {ex.status_code}: {ex.message}",
                                retry=ex.status_code >= 500) from None
        except a.APIConnectionError as ex:
            raise ProviderError(f"cannot reach the provider: {ex}", retry=True) from None
        blocks = [b.model_dump(exclude_none=True) for b in response.content]
        # compaction, thinking and fallback blocks go back unchanged: the API needs them on the next request
        self.messages.append({"role": "assistant", "content": blocks})
        turn = Turn(stop=str(response.stop_reason or ""),
                    usage=response.usage.model_dump(exclude_none=True) if response.usage else {})
        for b in blocks:
            kind = b.get("type")
            if kind == "text":
                turn.text += b.get("text", "")
            elif kind == "thinking" and b.get("thinking"):
                turn.reasoning += b["thinking"]
            elif kind == "tool_use":
                turn.calls.append(Call(b.get("id", ""), b.get("name", ""), b.get("input") or {}))
        if turn.stop == "refusal":
            details = getattr(response, "stop_details", None)
            turn.text = turn.text or f"(the model declined: {getattr(details, 'explanation', '') or 'refusal'})"
        if turn.stop == "max_tokens" and turn.calls:
            turn.calls = []  # a cut-off tool input may be incomplete: never run it
            turn.text += "\n(the answer was cut off at the token limit; ask again in smaller steps)"
        return turn


# ---------------------------------------------------------------- OpenAI-compatible (raw HTTP)

def _post(url: str, key: str, body: dict, timeout: float = 600) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode("utf-8", "replace")[:1000]
        raise ProviderError(f"the provider answered {ex.code}: {detail}", retry=ex.code == 429 or ex.code >= 500) \
            from None
    except (urllib.error.URLError, OSError) as ex:
        raise ProviderError(f"cannot reach the provider: {ex}", retry=True) from None
    except ValueError as ex:
        raise ProviderError(f"the provider sent invalid JSON: {ex}", retry=True) from None


def _root(base: str) -> str:
    base = (base or OPENAI_DEFAULT).strip().rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    return base if base.endswith("/v1") else base + "/v1"


class OpenAIProvider:
    name = "openai"

    def __init__(self, system: str, tools: list[dict], model: str = "", effort: str = "high",
                 base_url: str = "", key_name: str = "openai", post=_post):
        self.key = _key(key_name) or os.environ.get("OPENAI_API_KEY", "")
        if not self.key:
            raise ProviderError("no OpenAI key: set it in Preferences › Assistant or OPENAI_API_KEY.")
        self.root = _root(base_url)
        self.model = model or "gpt-6-luna"
        self.effort = effort or "high"
        self.system = system
        self.tools = tools
        self.post = post
        self.items: list[dict] = []
        self.chat = False  # switched on when the endpoint has no Responses API

    def add_user(self, text: str) -> None:
        self.items.append({"role": "user", "content": text})

    def add_results(self, results: list[tuple], note: str = "") -> None:
        images = []
        for call, body, _ok, *rest in results:
            if self.chat:
                self.items.append({"role": "tool", "tool_call_id": call.id, "content": body})
            else:
                self.items.append({"type": "function_call_output", "call_id": call.id, "output": body})
            image = _image(rest[0] if rest else "")
            if image:
                images.append(f"data:{image[0]};base64,{image[1]}")
        if images:  # pictures go in a user message after the outputs (function outputs are text)
            if self.chat:
                parts = [{"type": "image_url", "image_url": {"url": url}} for url in images]
                self.items.append({"role": "user", "content": [{"type": "text", "text": "Snapshot(s):"}, *parts]})
            else:
                parts = [{"type": "input_image", "image_url": url} for url in images]
                self.items.append({"role": "user", "content": [{"type": "input_text", "text": "Snapshot(s):"},
                                                               *parts]})
        if note:
            self.add_user(note)

    def size(self) -> int:
        return len(json.dumps(self.items, default=str))

    def reset(self, text: str) -> None:
        self.items = []
        self.add_user(text)

    def step(self) -> Turn:
        if not self.chat:
            try:
                return self._responses()
            except ProviderError as ex:
                if "404" not in ex.message or any(i.get("type") == "function_call" for i in self.items):
                    raise
                self.chat = True  # no Responses API here, and nothing in the history depends on it
        return self._chat()

    def _responses(self) -> Turn:
        tools = [{"type": "function", "name": t["name"], "description": t["description"],
                  "parameters": t["input_schema"]} for t in self.tools]
        body = {"model": self.model, "instructions": self.system, "input": self.items, "tools": tools,
                "reasoning": {"effort": self.effort, "summary": "auto"}, "store": False,
                "include": ["reasoning.encrypted_content"]}
        try:
            data = self.post(self.root + "/responses", self.key, body)
        except ProviderError as ex:
            if "reasoning" not in ex.message.lower():
                raise
            body.pop("reasoning")
            body.pop("include")  # a model without reasoning: ask again plainly
            data = self.post(self.root + "/responses", self.key, body)
        output = data.get("output") or []
        self.items.extend(output)
        turn = Turn(stop=str(data.get("status") or ""), usage=data.get("usage") or {})
        for item in output:
            kind = item.get("type")
            if kind == "message":
                turn.text += "".join(p.get("text", "") for p in item.get("content") or []
                                     if p.get("type") == "output_text")
            elif kind == "reasoning":
                turn.reasoning += "".join(s.get("text", "") for s in item.get("summary") or [])
            elif kind == "function_call":
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except ValueError:
                    args = {"_invalid_json": item.get("arguments")}
                turn.calls.append(Call(item.get("call_id", ""), item.get("name", ""), args))
        return turn

    def _chat(self) -> Turn:
        tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                    "parameters": t["input_schema"]}} for t in self.tools]
        data = self.post(self.root + "/chat/completions", self.key,
                         {"model": self.model, "messages": [{"role": "system", "content": self.system}, *self.items],
                          "tools": tools})
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("the provider sent no answer", retry=True)
        message = choices[0].get("message") or {}
        self.items.append(message)
        turn = Turn(text=message.get("content") or "", stop=str(choices[0].get("finish_reason") or ""),
                    usage=data.get("usage") or {})
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {"_invalid_json": fn.get("arguments")}
            turn.calls.append(Call(call.get("id", ""), fn.get("name", ""), args))
        return turn


def make(provider: str, system: str, tools: list[dict], model: str = "", effort: str = "high",
         base_url: str = ""):
    provider = (provider or "anthropic").lower()
    if provider == "anthropic":
        return AnthropicProvider(system, tools, model, effort, base_url)
    if provider in ("openai", "openai-compatible"):
        return OpenAIProvider(system, tools, model, effort, base_url)
    raise ProviderError(f"unknown provider {provider!r}: use anthropic or openai")
