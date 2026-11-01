"""OpenTelemetry GenAI spans for every step, exported over OTLP.

We follow the OpenTelemetry GenAI semantic conventions so a run reads the same
in Langfuse, Arize Phoenix, or any OTLP backend: model calls carry
``gen_ai.request.model`` and ``gen_ai.usage.input_tokens`` /
``gen_ai.usage.output_tokens``; tool and guardrail steps carry their own
attributes. The tracer is a no-op when tracing is disabled, so unit tests and
offline eval run without a collector.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from support_agent.config import get_settings
from support_agent.schemas import CostRecord

try:  # OpenTelemetry is optional at import time so tests do not require it.
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - only hit when the extra is not installed
    _OTEL_AVAILABLE = False


_provider_configured = False


def _ensure_provider() -> None:
    global _provider_configured
    if _provider_configured or not _OTEL_AVAILABLE:
        return
    settings = get_settings()
    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    if settings.otel_endpoint:
        exporter = OTLPSpanExporter(endpoint=f"{settings.otel_endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _provider_configured = True


def _enabled() -> bool:
    return _OTEL_AVAILABLE and get_settings().tracing_enabled


@contextmanager
def model_span(model: str, effort: str | None = None) -> Iterator["_Span"]:
    """Span for one model call. Set the cost on it when the call returns."""
    with _span(f"chat {model}", kind="model") as s:
        s.set("gen_ai.system", "anthropic")
        s.set("gen_ai.request.model", model)
        if effort:
            s.set("gen_ai.request.effort", effort)
        yield s


@contextmanager
def tool_span(tool_name: str) -> Iterator["_Span"]:
    """Span for one tool invocation."""
    with _span(f"tool {tool_name}", kind="tool") as s:
        s.set("gen_ai.tool.name", tool_name)
        yield s


@contextmanager
def guardrail_span(check: str) -> Iterator["_Span"]:
    """Span for one guardrail check (PII, safety, refusal, injection)."""
    with _span(f"guardrail {check}", kind="guardrail") as s:
        s.set("guardrail.check", check)
        yield s


@contextmanager
def _span(name: str, kind: str) -> Iterator["_Span"]:
    if _enabled():
        _ensure_provider()
        tracer = trace.get_tracer("support-agent")
        with tracer.start_as_current_span(name) as otel_span:
            wrapper = _Span(otel_span)
            wrapper.set("span.kind", kind)
            yield wrapper
    else:
        yield _Span(None)


class _Span:
    """Thin wrapper so callers use the same API whether or not OTel is active."""

    def __init__(self, otel_span: object | None):
        self._span = otel_span

    def set(self, key: str, value: object) -> None:
        if self._span is not None:
            self._span.set_attribute(key, value)

    def record_cost(self, cost: CostRecord) -> None:
        """Attach usage + dollar cost using GenAI attribute names."""
        self.set("gen_ai.usage.input_tokens", cost.input_tokens)
        self.set("gen_ai.usage.output_tokens", cost.output_tokens)
        self.set("gen_ai.usage.cache_read_input_tokens", cost.cache_read_input_tokens)
        self.set(
            "gen_ai.usage.cache_creation_input_tokens",
            cost.cache_creation_input_tokens,
        )
        self.set("gen_ai.usage.cost_usd", cost.usd)
