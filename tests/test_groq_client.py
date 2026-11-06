"""Exercise provider translation across real loop calls, without external APIs."""

from types import SimpleNamespace

import httpx
import pytest

from support_agent.agent.groq_client import GroqClient


def _response(message, finish="stop"):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        },
    )


def test_groq_tool_roundtrip_and_structured_confidence(monkeypatch):
    from support_agent.agent import models
    from support_agent.agent.loop import run_turn
    from support_agent.schemas import Citation, DecisionType
    from support_agent.tools.registry import ToolOutcome

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("SAFETY_MODEL_URL", "")
    client = GroqClient("test-key")
    monkeypatch.setattr(models, "get_client", lambda: client)
    monkeypatch.setattr("support_agent.agent.loop.get_client", lambda: client)
    monkeypatch.setattr("support_agent.agent.confidence.get_client", lambda: client)
    citation = Citation(
        source_id="returns", source_title="Returns", chunk="Return within 30 days.", score=0.9
    )
    monkeypatch.setattr(
        "support_agent.agent.loop.dispatch",
        lambda *_: ToolOutcome(text=citation.chunk, citations=[citation]),
    )
    responses = iter(
        [
            _response(
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "knowledge_base",
                                "arguments": '{"query":"returns"}',
                            },
                        }
                    ],
                },
                "tool_calls",
            ),
            _response({"content": "Return within 30 days."}),
            _response({"content": '{"confidence":0.95,"reason":"Supported by source"}'}),
        ]
    )
    requests = []

    def post(url, **kwargs):
        assert url == "https://api.groq.com/openai/v1/chat/completions"
        requests.append(kwargs["json"])
        return next(responses)

    monkeypatch.setattr(httpx, "post", post)
    trace = run_turn("groq-test", "What is your return policy?")
    assert trace.decision.type == DecisionType.ANSWER
    assert trace.decision.citations[0].source_id == "returns"
    messages = requests[1]["messages"]
    assert messages[-2]["tool_calls"][0]["id"] == "call_1"
    assert messages[-1]["role"] == "tool"
    assert messages[-1]["tool_call_id"] == "call_1"
    assert "30 days" in messages[-1]["content"]
    assert requests[2]["response_format"]["json_schema"]["strict"] is True
    assert "thinking" not in requests[0]
    assert trace.spans[0].cost.input_tokens == 120


@pytest.mark.parametrize("status", [401, 429, 500])
def test_errors_do_not_leak_response_body_or_retry_other_providers(monkeypatch, status):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(status, text="sensitive input")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(RuntimeError) as error:
        GroqClient("test-key").create(
            model="openai/gpt-oss-20b",
            max_tokens=64,
            system="Test",
            messages=[{"role": "user", "content": "Hi"}],
        )
    assert "sensitive" not in str(error.value)
    assert len(calls) == 1


def test_cpu_embeddings_need_no_hosted_api_key(monkeypatch):
    import sys

    from support_agent.config import get_settings
    from support_agent.kb.embed import Embedder

    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.setenv("EMBEDDING_DIM", "3")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setitem(
        sys.modules,
        "fastembed",
        SimpleNamespace(TextEmbedding=lambda **_: SimpleNamespace(embed=lambda _: [[3, 4, 0]])),
    )
    assert Embedder().embed_one("returns") == [0.6, 0.8, 0.0]
    monkeypatch.setenv("EMBEDDING_DIM", "384")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="EMBEDDING_DIM"):
        Embedder().embed_one("returns")


def test_transient_output_parse_failure_retries_same_provider(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"code": "output_parse_failed"}})
        return _response({"content": '{"confidence":0.8,"reason":"Supported"}'})

    monkeypatch.setattr(httpx, "post", post)
    response = GroqClient("test-key").create(
        model="openai/gpt-oss-20b",
        max_tokens=128,
        system="Return JSON",
        messages=[{"role": "user", "content": "Score this answer"}],
        output_config={"format": {"schema": {"type": "object"}}},
    )
    assert response.content[0].text.startswith('{"confidence"')
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert calls[1][1]["response_format"]["json_schema"]["strict"] is True


def test_confidence_parse_failure_returns_handoff_instead_of_500(monkeypatch):
    from fastapi.testclient import TestClient

    from support_agent.agent import models
    from support_agent.server import app

    monkeypatch.setenv("SAFETY_MODEL_URL", "")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    client = GroqClient("test-key")
    monkeypatch.setattr(models, "get_client", lambda: client)
    monkeypatch.setattr("support_agent.agent.loop.get_client", lambda: client)
    monkeypatch.setattr("support_agent.agent.confidence.get_client", lambda: client)
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return _response({"content": "Hi! How can I help you today?"})
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "output_parse_failed",
                    "failed_generation": "private failed generation",
                }
            },
        )

    monkeypatch.setattr(httpx, "post", post)
    response = TestClient(app).post(
        "/chat",
        json={"conversation_id": "scoring-regression", "message": "What is your return policy?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["handoff"] is True
    assert data["confidence"] == 0
    assert data["ticket_id"]
    assert "private failed generation" not in response.text
    assert len(calls) == 3  # One draft, two attempts to score it; no unbounded retry.


@pytest.mark.parametrize(
    ("upstream_status", "api_status"), [(400, 502), (401, 502), (429, 429), (500, 502)]
)
def test_chat_reports_safe_provider_error(monkeypatch, upstream_status, api_status):
    from fastapi.testclient import TestClient

    from support_agent import server
    from support_agent.agent.groq_client import GroqRequestError

    def fail(**kwargs):
        raise GroqRequestError("private provider error", upstream_status)

    monkeypatch.setattr(server, "run_turn", fail)
    response = TestClient(server.app).post(
        "/chat",
        json={"conversation_id": "provider-regression", "message": "What is your return policy?"},
    )
    assert response.status_code == api_status
    assert "private provider error" not in response.text
    assert "try again" in response.json()["detail"].lower()


def test_chat_reports_safe_connection_error(monkeypatch):
    from fastapi.testclient import TestClient

    from support_agent import server

    def fail(**kwargs):
        raise httpx.ConnectError("private connection details")

    monkeypatch.setattr(server, "run_turn", fail)
    response = TestClient(server.app).post(
        "/chat",
        json={"conversation_id": "connection-regression", "message": "What is your return policy?"},
    )
    assert response.status_code == 503
    assert "private connection details" not in response.text


@pytest.mark.parametrize(
    "message",
    [
        {"content": {"invalid": "content"}},
        {
            "content": None,
            "tool_calls": [
                {"id": "bad", "function": {"name": "knowledge_base", "arguments": "not json"}}
            ],
        },
        {
            "content": None,
            "tool_calls": [
                {"id": "bad", "function": {"name": "knowledge_base", "arguments": "[]"}}
            ],
        },
    ],
)
def test_malformed_successful_provider_response_is_a_safe_error(monkeypatch, message):
    from support_agent.agent.groq_client import GroqOutputError

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _response(message))
    with pytest.raises(GroqOutputError, match="invalid response"):
        GroqClient("test-key").create(
            model="openai/gpt-oss-20b",
            max_tokens=100,
            system="Support",
            messages=[{"role": "user", "content": "Returns?"}],
        )
