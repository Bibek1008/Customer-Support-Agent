"""Audit real SDK exports locally, including hierarchy, masking, and failures."""

import json
from uuid import uuid4

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from support_agent.config import get_settings
from support_agent.observability import tracing
from support_agent.schemas import Citation
from support_agent.tools.registry import ToolOutcome
from tests.conftest import FakeResponse, TextBlock, ToolUseBlock


@pytest.fixture
def captured(monkeypatch):
    exporter = InMemorySpanExporter()
    monkeypatch.setenv("TRACING_ENABLED", "1")
    monkeypatch.setenv("SAFETY_MODEL_URL", "")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "secret-provider-key")
    get_settings.cache_clear()
    client = Langfuse(
        public_key=f"pk-lf-{uuid4()}",
        secret_key="test-secret",
        base_url="https://example.invalid",
        environment="test",
        tracer_provider=TracerProvider(),
        span_exporter=exporter,
        mask_otel_spans=tracing.mask_otel_spans,
    )
    monkeypatch.setattr(tracing, "get_langfuse", lambda: client)
    yield client, exporter
    client.shutdown()


def test_real_loop_export_hierarchy_usage_and_privacy(captured, make_client, monkeypatch):
    from support_agent.agent import confidence, loop

    client, exporter = captured
    fake = make_client(
        [
            FakeResponse(
                content=[
                    ToolUseBlock(id="tool_1", name="knowledge_base", input={"query": "returns"})
                ],
                stop_reason="tool_use",
            ),
            FakeResponse(
                content=[TextBlock("Returns are allowed within 30 days.")], stop_reason="end_turn"
            ),
            FakeResponse(
                content=[TextBlock('{"confidence":0.95,"reason":"Source supports answer"}')],
                stop_reason="end_turn",
            ),
        ]
    )
    monkeypatch.setattr(loop, "get_client", lambda: fake)
    monkeypatch.setattr(confidence, "get_client", lambda: fake)

    def dispatch(*_):
        with tracing.embedding_span("gemini-embedding-001", ["returns"], "RETRIEVAL_QUERY") as span:
            span.update(output={"vector_count": 1, "dimensions": 384})
        return ToolOutcome(
            text="Returns: 30 days. Contact jane@example.com. secret-provider-key",
            citations=[
                Citation(
                    source_id="returns",
                    source_title="Returns",
                    chunk="Returns: 30 days.",
                    score=0.9,
                )
            ],
        )

    monkeypatch.setattr(loop, "dispatch", dispatch)
    result = loop.run_turn(
        "session@example.com",
        "Can I return an item? Email jane@example.com.",
        customer_id="customer@example.com",
    )
    client.flush()
    spans = exporter.get_finished_spans()
    assert result.langfuse_trace_id
    assert len({s.context.trace_id for s in spans}) == 1
    roots = [s for s in spans if s.parent is None]
    assert len(roots) == 1
    root = roots[0]
    assert root.name == "handle-support-request"
    assert root.attributes["langfuse.observation.type"] == "agent"
    assert "30 days" in root.attributes["langfuse.observation.output"]
    generations = [
        s for s in spans if s.attributes.get("langfuse.observation.type") == "generation"
    ]
    assert len(generations) == 3
    for generation in generations:
        assert generation.parent.span_id == root.context.span_id
        assert generation.attributes["langfuse.observation.model.name"] == "openai/gpt-oss-20b"
        usage = json.loads(generation.attributes["langfuse.observation.usage_details"])
        assert usage["input"] == 100
        assert usage["output"] == 50
    retrieval = next(s for s in spans if s.name == "retrieve-context")
    embedding = next(s for s in spans if s.name == "embed-text")
    assert retrieval.parent.span_id == root.context.span_id
    assert embedding.parent.span_id == retrieval.context.span_id
    assert any(s.attributes.get("langfuse.observation.type") == "guardrail" for s in spans)
    serialized = json.dumps([dict(s.attributes) for s in spans])
    for secret in (
        "jane@example.com",
        "session@example.com",
        "customer@example.com",
        "secret-provider-key",
    ):
        assert secret not in serialized
    assert "EMAIL_ADDRESS" in serialized


def test_error_keeps_exception_private_and_propagates(captured):
    client, exporter = captured
    with (
        pytest.raises(ValueError, match="jane@example.com"),
        tracing._span("failing-operation", "tool"),
    ):
        raise ValueError("jane@example.com secret-provider-key")
    client.flush()
    span = exporter.get_finished_spans()[0]
    assert span.attributes["langfuse.observation.level"] == "ERROR"
    assert span.attributes["langfuse.observation.status_message"] == "ValueError"
    assert not span.events


def test_disabled_tracing_never_initializes_client(monkeypatch):
    monkeypatch.setenv("TRACING_ENABLED", "0")
    get_settings.cache_clear()
    monkeypatch.setattr(tracing, "get_langfuse", lambda: pytest.fail("Tracing should be disabled"))
    with tracing.model_span("any-model") as span:
        span.update(input="ignored")


def test_fallback_trace_records_actual_gemini_model_usage_and_provider(captured, monkeypatch):
    import httpx

    from support_agent.agent.fallback import QuotaFallbackClient
    from support_agent.agent.groq_client import GeminiClient, GroqClient
    from support_agent.observability.cost import cost_from_usage
    from tests.test_groq_client import _response

    client, exporter = captured
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **_: (
            httpx.Response(429) if url == GroqClient.endpoint else _response({"content": "Ready"})
        ),
    )
    fallback = QuotaFallbackClient(
        GroqClient("secret-provider-key"), GeminiClient("secret-gemini-key")
    )
    with tracing.model_span(
        "openai/gpt-oss-20b", name="fallback-test", input=[{"role": "user", "content": "Hello"}]
    ) as span:
        response = fallback.create(
            model="openai/gpt-oss-20b",
            max_tokens=256,
            system="Support",
            messages=[{"role": "user", "content": "Hello"}],
        )
        span.record_response(response)
        span.record_cost(cost_from_usage("openai/gpt-oss-20b", response.usage))
    client.flush()
    generation = next(s for s in exporter.get_finished_spans() if s.name == "fallback-test")
    assert generation.attributes["langfuse.observation.model.name"] == "gemini-3.5-flash-lite"
    assert (
        json.loads(generation.attributes["langfuse.observation.metadata.gen_ai.provider.name"])
        == "gemini"
    )
    assert (
        json.loads(generation.attributes["langfuse.observation.metadata.fallback.from"]) == "groq"
    )
    assert json.loads(generation.attributes["langfuse.observation.usage_details"])["input"] == 120
    serialized = json.dumps([dict(s.attributes) for s in exporter.get_finished_spans()])
    assert "secret-gemini-key" not in serialized
