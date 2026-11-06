"""Translate the loop's message blocks to Groq's Chat Completions API.

Only Groq is contacted. There is no automatic fallback to a paid provider.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx

from support_agent.request_context import remaining_timeout


class GroqRequestError(RuntimeError):
    """A provider failure with a safe message, never the raw response body."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class GroqOutputError(GroqRequestError):
    """The provider could not generate a parseable model response."""


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
        for attempt in range(2):
            response = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=remaining_timeout(),
            )
            # Groq can intermittently fail to parse even strict structured output.
            # Retry only generation failures, once, with the same provider/schema.
            code = None
            if response.status_code == 400:
                try:
                    body = response.json()
                    error = body.get("error") if isinstance(body, dict) else None
                    code = error.get("code") if isinstance(error, dict) else None
                except ValueError:
                    pass
            if code not in {"output_parse_failed", "json_validate_failed", "tool_use_failed"}:
                break
            if attempt == 1:
                raise GroqOutputError("Groq could not generate a valid response.", 502)
        if response.status_code == 429:
            raise GroqRequestError(
                "Groq usage limit reached. Wait before retrying; no fallback was used.", 429
            )
        if response.is_error:
            # Do not expose provider error bodies: they can include customer input.
            raise GroqRequestError(
                f"Groq request failed (HTTP {response.status_code}).", response.status_code
            )
        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict) or (
                message.get("content") is not None and not isinstance(message["content"], str)
            ):
                raise ValueError("Invalid message")
            for call in message.get("tool_calls") or []:
                arguments = json.loads(call["function"]["arguments"])
                if not isinstance(arguments, dict):
                    raise TypeError("Invalid tool arguments")
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise GroqOutputError(
                "Groq returned an invalid response. Please retry.", 502
            ) from error
        if choice["finish_reason"] == "length":
            raise GroqOutputError(
                "Groq response hit the output token limit; try a shorter request.", 502
            )
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
