"""Quota-only fallback, tool history, actual costs, and fail-closed safety."""

from types import SimpleNamespace

import httpx
import pytest

from support_agent.agent.fallback import QuotaFallbackClient
from support_agent.agent.groq_client import GeminiClient, GroqClient, GroqRequestError, _messages
from support_agent.config import get_settings
from support_agent.guardrails.safety import SafetyClassifier, SafetyRole
from support_agent.observability.cost import cost_from_usage
from support_agent.observability.tracing import sanitize
from tests.test_groq_client import _response


def request(client):
    return client.messages.create(
        model="openai/gpt-oss-20b",
        max_tokens=256,
        system="Support",
        messages=[{"role": "user", "content": "Hello"}],
    )


def clients():
    return QuotaFallbackClient(GroqClient("groq-test-key"), GeminiClient("gemini-test-key"))


def test_primary_success_never_contacts_gemini(monkeypatch):
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        return _response({"content": "Ready"})

    monkeypatch.setattr(httpx, "post", post)
    assert request(clients()).provider == "groq"
    assert urls == [GroqClient.endpoint]


def test_quota_fallback_uses_separate_key_model_and_cooldown(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if url == GroqClient.endpoint:
            return httpx.Response(429)
        assert kwargs["headers"] == {"Authorization": "Bearer gemini-test-key"}
        assert kwargs["json"]["model"] == "gemini-3.5-flash-lite"
        assert "max_tokens" in kwargs["json"] and "max_completion_tokens" not in kwargs["json"]
        return _response({"content": "Ready"})

    monkeypatch.setattr(httpx, "post", post)
    client = clients()
    response = request(client)
    assert response.provider == "gemini" and response.fallback_from == "groq"
    assert cost_from_usage("openai/gpt-oss-20b", response.usage).model == "gemini-3.5-flash-lite"
    request(client)
    assert calls == [GroqClient.endpoint, GeminiClient.endpoint, GeminiClient.endpoint]


@pytest.mark.parametrize("status", [400, 401, 403, 500, 502])
def test_non_quota_error_never_switches_provider(status, monkeypatch):
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        return httpx.Response(status, text="private error")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(GroqRequestError) as error:
        request(clients())
    assert "private" not in str(error.value)
    assert urls == [GroqClient.endpoint]


def test_both_quotas_exhausted_stops_after_two_calls(monkeypatch):
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        return httpx.Response(429)

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(GroqRequestError) as error:
        request(clients())
    assert error.value.status_code == 429
    assert urls == [GroqClient.endpoint, GeminiClient.endpoint]


def test_signatures_preserved_on_wire_masked_in_traces_and_not_sent_to_groq(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _response(
            {
                "tool_calls": [
                    {
                        "id": "tool-1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"query":"returns"}'},
                        "extra_content": {"google": {"thought_signature": "opaque-signature"}},
                    }
                ]
            },
            "tool_calls",
        ),
    )
    response = request(GeminiClient("gemini-test-key"))
    messages = [
        {"role": "assistant", "content": response.content},
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "30 days"}],
        },
    ]
    assert (
        _messages("Support", messages, gemini=True)[1]["tool_calls"][0]["extra_content"]["google"][
            "thought_signature"
        ]
        == "opaque-signature"
    )
    assert "extra_content" not in _messages("Support", messages)[1]["tool_calls"][0]
    assert "opaque-signature" not in str(sanitize(response.content))
    assert _messages("Support", messages, gemini=True)[-1]["tool_call_id"] == "tool-1"


def test_migrated_groq_tool_history_uses_documented_marker():
    block = SimpleNamespace(
        type="tool_use", id="groq-call", name="lookup", input={"query": "returns"}
    )
    converted = _messages("Support", [{"role": "assistant", "content": [block]}], gemini=True)
    assert (
        converted[1]["tool_calls"][0]["extra_content"]["google"]["thought_signature"]
        == "skip_thought_signature_validator"
    )


def test_gemini_schema_and_thinking_tokens_accounted(monkeypatch):
    schema = {
        "type": "object",
        "properties": {"safe": {"type": "boolean"}},
        "required": ["safe"],
        "additionalProperties": False,
    }

    def post(url, **kwargs):
        assert kwargs["json"]["response_format"]["json_schema"]["schema"] == schema
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"safe":true}'}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 35,
                    "completion_tokens_details": {"reasoning_tokens": 20},
                },
            },
        )

    monkeypatch.setattr(httpx, "post", post)
    response = GeminiClient("gemini-test-key").create(
        model="gemini-3.5-flash-lite",
        max_tokens=256,
        system="Classify",
        messages=[{"role": "user", "content": "Hello"}],
        output_config={"format": {"schema": schema}},
    )
    assert response.usage.output_tokens == 25
    cost = cost_from_usage("openai/gpt-oss-20b", response.usage)
    assert cost.model == "gemini-3.5-flash-lite" and cost.usd == 0.000066


def safety(monkeypatch):
    monkeypatch.setenv("GEMINI_FALLBACK_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("SAFETY_PROVIDER", "groq")
    get_settings.cache_clear()
    return SafetyClassifier()


@pytest.mark.parametrize(
    "content,safe",
    [('{"safe":true,"categories":[]}', True), ('{"safe":false,"categories":["ILLEGAL"]}', False)],
)
def test_safety_uses_validated_gemini_verdict_after_quota(monkeypatch, content, safe):
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        return (
            httpx.Response(429) if url == GroqClient.endpoint else _response({"content": content})
        )

    monkeypatch.setattr(httpx, "post", post)
    classifier = safety(monkeypatch)
    verdict = classifier.classify("Support request", SafetyRole.USER)
    assert verdict.checked and verdict.safe == safe
    assert verdict.provider == "gemini" and verdict.fallback_from == "groq"
    classifier.classify("Another request", SafetyRole.USER)
    assert urls == [GroqClient.endpoint, GeminiClient.endpoint, GeminiClient.endpoint]


@pytest.mark.parametrize(
    "content",
    ["not json", '{"safe":true,"categories":["ILLEGAL"]}', '{"safe":"yes","categories":[]}'],
)
def test_malformed_safety_fallback_blocks(monkeypatch, content):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **k: (
            httpx.Response(429) if url == GroqClient.endpoint else _response({"content": content})
        ),
    )
    verdict = safety(monkeypatch).classify("Hello", SafetyRole.USER)
    assert verdict.checked and verdict.blocked and "INVALID_VERDICT" in verdict.categories


def test_safety_quota_on_both_providers_never_passes(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429))
    with pytest.raises(GroqRequestError) as error:
        safety(monkeypatch).classify("Hello", SafetyRole.USER)
    assert error.value.status_code == 429


def test_unsafe_primary_verdict_never_falls_back(monkeypatch):
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        response = _response({"content": '{"safe":false,"categories":["ILLEGAL"]}'})
        response.request = httpx.Request("POST", url)
        return response

    monkeypatch.setattr(httpx, "post", post)
    assert safety(monkeypatch).classify("Unauthorized request", SafetyRole.USER).blocked
    assert urls == [GroqClient.endpoint]


@pytest.mark.parametrize("status", [400, 401, 500])
def test_non_quota_safety_failure_stays_closed_without_switching(status, monkeypatch):
    urls = []

    def post(url, **kwargs):
        urls.append(url)
        return httpx.Response(status, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    verdict = safety(monkeypatch).classify("Hello", SafetyRole.USER)
    assert verdict.blocked and verdict.categories == ["UNAVAILABLE"]
    assert urls == [GroqClient.endpoint]


def test_enabled_fallback_requires_its_own_key(monkeypatch):
    from support_agent.agent.models import validate_credentials

    monkeypatch.setenv("GEMINI_FALLBACK_ENABLED", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        validate_credentials()


def test_inference_fallback_does_not_replay_completed_tool(monkeypatch):
    from support_agent.agent import loop
    from support_agent.agent.confidence import ConfidenceResult
    from support_agent.schemas import Citation
    from support_agent.tools.registry import ToolOutcome

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    get_settings.cache_clear()

    calls, writes, payloads = [], [], []

    def post(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return _response(
                {
                    "tool_calls": [
                        {
                            "id": "create-1",
                            "type": "function",
                            "function": {
                                "name": "create_ticket",
                                "arguments": '{"subject":"Synthetic case","body":"Support request"}',
                            },
                        }
                    ]
                },
                "tool_calls",
            )
        if url == GroqClient.endpoint:
            return httpx.Response(429)
        payloads.append(kwargs["json"])
        return _response({"content": "Ticket saved for review."})

    def dispatch(name, arguments):
        writes.append(name)
        return ToolOutcome(
            text="Ticket saved for review.",
            citations=[
                Citation(
                    source_id="ticket",
                    source_title="Ticket",
                    chunk="Ticket saved for review.",
                    score=1,
                )
            ],
        )

    monkeypatch.setattr(httpx, "post", post)
    client = clients()
    monkeypatch.setattr(loop, "get_client", lambda: client)
    monkeypatch.setattr(loop, "dispatch", dispatch)
    monkeypatch.setattr(
        loop, "score_confidence", lambda **_: ConfidenceResult(score=0.9, reason="Supported")
    )
    loop.run_turn("fallback-write", "Please record my support issue")
    assert writes == ["create_ticket"]
    assert (
        next(m for m in payloads[0]["messages"] if m["role"] == "tool")["tool_call_id"]
        == "create-1"
    )
