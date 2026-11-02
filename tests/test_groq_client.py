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
