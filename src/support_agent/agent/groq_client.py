"""Translate the loop's message blocks to Groq's Chat Completions API.

Only Groq is contacted. There is no automatic fallback to a paid provider.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx


def _field(block, name, default=None):
    return block.get(name, default) if isinstance(block, dict) else getattr(block, name, default)


def _messages(system: str, messages: list[dict]) -> list[dict]:
    result = [{"role": "system", "content": system}]
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            result.append(message)
            continue
        texts, calls = [], []
        for block in content:
            kind = _field(block, "type")
            if kind == "text":
                texts.append(_field(block, "text"))
            elif kind == "tool_use":
                calls.append(
                    {
                        "id": _field(block, "id"),
                        "type": "function",
                        "function": {
                            "name": _field(block, "name"),
                            "arguments": json.dumps(_field(block, "input")),
                        },
                    }
                )
            elif kind == "tool_result":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": _field(block, "tool_use_id"),
                        "content": _field(block, "content"),
                    }
                )
            else:
                raise ValueError(f"Unsupported message block: {kind}")
        if texts or calls:
            converted = {"role": message["role"], "content": "\n".join(texts) or None}
            if calls:
                converted["tool_calls"] = calls
            result.append(converted)
    return result


class GroqClient:
    """Expose the small messages.create interface consumed by the application."""

    def __init__(self, api_key: str) -> None:
        if not api_key or api_key.startswith("your-"):
            raise RuntimeError("Set GROQ_API_KEY in .env to a valid Groq API key.")
        self._api_key = api_key
        self.messages = self

    def create(self, *, model, max_tokens, system, messages, tools=None, output_config=None):
        payload = {
            "model": model,
            "messages": _messages(system, messages),
            "max_completion_tokens": max_tokens,
            "reasoning_effort": "low",
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
                for tool in tools
            ]
            payload["parallel_tool_calls"] = False
        if output_config and "format" in output_config:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "result",
                    "strict": True,
                    "schema": output_config["format"]["schema"],
                },
            }
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
            timeout=90.0,
        )
        if response.status_code == 429:
            raise RuntimeError(
                "Groq usage limit reached. Wait before retrying; no fallback was used."
            )
        if response.is_error:
            # Do not expose provider error bodies: they can include customer input.
            raise RuntimeError(f"Groq request failed (HTTP {response.status_code}).")
        data = response.json()
        choice = data["choices"][0]
        if choice["finish_reason"] == "length":
            raise RuntimeError("Groq response hit the output token limit; try a shorter request.")
        message = choice["message"]
        blocks = []
        if message.get("content"):
            blocks.append(SimpleNamespace(type="text", text=message["content"]))
        for call in message.get("tool_calls") or []:
            function = call["function"]
            blocks.append(
                SimpleNamespace(
                    type="tool_use",
                    id=call["id"],
                    name=function["name"],
                    input=json.loads(function["arguments"]),
                )
            )
        usage = data.get("usage", {})
        return SimpleNamespace(
            content=blocks,
            reasoning=message.get("reasoning"),
            stop_reason="tool_use" if message.get("tool_calls") else "end_turn",
            usage=SimpleNamespace(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            ),
        )
