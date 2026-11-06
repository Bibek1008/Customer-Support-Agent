"""Typed Langfuse observations, masked before capture and again before export."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import lru_cache, wraps
from inspect import signature

from support_agent.config import get_settings
from support_agent.schemas import CostRecord

_root: ContextVar[_Span | None] = ContextVar("support_trace_root", default=None)
_pii_summary: ContextVar[dict | None] = ContextVar("support_pii_summary", default=None)


def chat_messages(messages):
    """Render message/tool blocks as a role-labelled conversation in Langfuse."""
    if not isinstance(messages, list):
        return messages
    result = []
    for message in sanitize(messages):
        content = message.get("content")
        if not isinstance(content, list):
            result.append(message)
            continue
        texts, calls = [], []
        for block in content:
            if block.get("type") == "text":
                texts.append(block["text"])
            elif block.get("type") == "tool_use":
                calls.append(
                    {
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block["input"]),
                        },
                    }
                )
            elif block.get("type") == "tool_result":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": block["content"],
                    }
                )
        if texts or calls:
            converted = {"role": message["role"], "content": "\n".join(texts) or None}
            if calls:
                converted["tool_calls"] = calls
            result.append(converted)
    return result


def sanitize(value):
    """Non-instrumented PII rules avoid recursive traces during masking."""
    if isinstance(value, str):
        from support_agent.guardrails.pii import PIIRedactor

        s = get_settings()
        for secret in (
            s.anthropic_api_key,
            s.groq_api_key,
            s.gemini_api_key,
            s.openai_api_key,
            s.langfuse_secret_key,
            s.langfuse_public_key,
            s.ticketing_api_key,
            s.hugging_face_hub_token,
            s.database_url,
            s.admin_api_key,
            s.service_api_key,
        ):
            if secret and len(secret) >= 8:
                value = value.replace(secret, "<SECRET>")
        redactor = object.__new__(PIIRedactor)
        return redactor._redact_regex(redactor._redact_ssn(value).text).text
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [sanitize(item) for item in value]
    if hasattr(value, "model_dump"):
        return sanitize(value.model_dump(mode="json"))
    if hasattr(value, "__dict__"):
        return sanitize(vars(value))
    return value


def mask_otel_spans(*, params):
    """SDK v5 export hook, including attributes from other instrumentations."""
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches = {}
    for identifier, span in params.spans.items():
        replacements = {}
        for key, value in span.attributes.items():
            if isinstance(value, str):
                try:
                    decoded = json.loads(value)
                except (ValueError, TypeError):
                    masked = sanitize(value)
                else:
                    masked = json.dumps(sanitize(decoded), ensure_ascii=False)
                if masked != value:
                    replacements[key] = masked
        if replacements:
            patches[identifier] = OtelSpanPatch(set_attributes=replacements)
    return MaskOtelSpansResult(span_patches=patches)


@lru_cache(maxsize=1)
def get_langfuse():
    s = get_settings()
    if not s.tracing_enabled or not all(
        (s.langfuse_public_key, s.langfuse_secret_key, s.langfuse_base_url)
    ):
        return None
    from langfuse import Langfuse
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    from support_agent import __version__

    return Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key,
        base_url=s.langfuse_base_url.rstrip("/"),
        environment=s.langfuse_environment,
        release=__version__,
        mask_otel_spans=mask_otel_spans,
        tracer_provider=TracerProvider(
            resource=Resource.create({"service.name": s.otel_service_name})
        ),
    )


@lru_cache(maxsize=1)
def _generic_tracer():
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    s = get_settings()
    provider = TracerProvider(resource=Resource.create({"service.name": s.otel_service_name}))
    if s.otel_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=s.otel_endpoint.rstrip("/") + "/v1/traces")
            )
        )
    return provider


@contextmanager
def _span(name: str, kind: str = "span", **kwargs):
    if not get_settings().tracing_enabled:
        yield _Span()
        return
    client = get_langfuse()
    error = None
    if client is not None:
        # Re-raise AFTER SDK context exit: automatic exception events can carry
        # raw source text, and the export masking hook cannot modify events.
        with client.start_as_current_observation(
            name=name, as_type=kind, **sanitize(kwargs)
        ) as obs:
            wrapped = _Span(observation=obs)
            try:
                yield wrapped
            except Exception as exc:  # noqa: BLE001 - re-raised below without exporting raw exception text
                wrapped.update(level="ERROR", status_message=type(exc).__name__)
                error = (exc, exc.__traceback__)
    else:
        with (
            _generic_tracer()
            .get_tracer("support-agent")
            .start_as_current_span(
                name, record_exception=False, set_status_on_exception=False
            ) as obs
        ):
            wrapped = _Span(otel_span=obs)
            wrapped.set("langfuse.observation.type", kind)
            wrapped.update(**kwargs)
            try:
                yield wrapped
            except Exception as exc:  # noqa: BLE001 - re-raised below without exporting raw exception text
                wrapped.update(level="ERROR", status_message=type(exc).__name__)
                error = (exc, exc.__traceback__)
    if error is not None:
        raise error[0].with_traceback(error[1])


def trace_turn(function):
    """One agent per turn; no implicit argument or return-object capture."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        params = signature(function).bind(*args, **kwargs).arguments
        client = get_langfuse() if get_settings().tracing_enabled else None
        context = nullcontext()
        if client is not None:
            from langfuse import propagate_attributes

            from support_agent.request_context import current_request

            def identifier(value):
                return hashlib.sha256(value.encode()).hexdigest() if value else None

            request_context = current_request.get()
            context = propagate_attributes(
                session_id=identifier(params.get("conversation_id")),
                user_id=request_context.owner_hash
                if request_context
                else identifier(params.get("customer_id")),
                tags=["customer-support"],
                metadata={
                    "feature": "support-chat",
                    **({"request_id": request_context.request_id} if request_context else {}),
                },
            )
        with context, _span("handle-support-request", "agent") as span:
            token = _root.set(span)
            summary = {"checks": 0, "entities": set()}
            pii_token = _pii_summary.set(summary)
            try:
                result = function(*args, **kwargs)
                if client is not None:
                    result.langfuse_trace_id = client.get_current_trace_id()
                if result.decision is not None:
                    d = result.decision
                    span.update(
                        output=d.answer,
                        metadata={
                            "decision": d.type.value,
                            "confidence": d.confidence,
                            "threshold": d.threshold,
                            "handoff_reason": d.handoff_reason,
                            "source_ids": [c.source_id for c in d.citations],
                            "pii_checks": summary["checks"],
                            "pii_entity_types": sorted(summary["entities"]),
                        },
                    )
                return result
            finally:
                _pii_summary.reset(pii_token)
                _root.reset(token)

    return wrapped


def record_request_input(text: str):
    if (span := _root.get()) is not None:
        span.update(input=text)


@contextmanager
def model_span(model: str, effort: str | None = None, *, name="generate-response", input=None):
    with _span(
        name,
        "generation",
        model=model,
        input=chat_messages(input),
        model_parameters={"effort": effort} if effort else {},
    ) as span:
        span.set("gen_ai.provider.name", get_settings().llm_provider)
        span.set("gen_ai.request.model", model)
        yield span


@contextmanager
def embedding_span(model: str, input, task_type: str):
    with _span(
        "embed-text",
        "embedding",
        model=model,
        input=input,
        metadata={
            "provider": get_settings().embedding_provider,
            "dimensions": get_settings().embedding_dim,
            "task_type": task_type,
        },
    ) as span:
        yield span


@contextmanager
def tool_span(tool_name: str, input=None):
    kind = "retriever" if tool_name == "knowledge_base" else "tool"
    name = "retrieve-context" if kind == "retriever" else f"run-{tool_name.replace('_', '-')}"
    with _span(name, kind, input=input) as span:
        span.set("gen_ai.tool.name", tool_name)
        yield span


@contextmanager
def guardrail_span(check: str):
    summary = _pii_summary.get() if check == "pii" else None
    repeated = summary is not None and summary["checks"] > 0
    if summary is not None:
        summary["checks"] += 1
    context = (
        nullcontext(_Span()) if repeated else _span(f"check-{check.replace('_', '-')}", "guardrail")
    )
    with context as span:
        span.set("guardrail.check", check)
        yield span
        span.update(output=span._metadata)
        from support_agent.observability.audit import record_guardrail

        record_guardrail(check, span._metadata)
        if summary is not None:
            entities = span._metadata.get("guardrail.pii.entities", "")
            summary["entities"].update(filter(None, entities.split(",")))


class _Span:
    def __init__(self, observation=None, otel_span=None):
        self._observation = observation
        self._span = otel_span
        self._metadata = {}

    def update(self, **kwargs):
        if kwargs.get("metadata"):
            self._metadata.update(kwargs["metadata"])
        if self._observation is not None:
            self._observation.update(**sanitize(kwargs))
        elif self._span is not None:
            for key, value in kwargs.items():
                self.set(f"langfuse.observation.{key}", value)

    def set(self, key: str, value):
        self._metadata[key] = value
        if self._observation is not None:
            self.update(metadata={key: value})
        elif self._span is not None and value is not None:
            clean = sanitize(value)
            self._span.set_attribute(
                key, clean if isinstance(clean, (str, int, float, bool)) else json.dumps(clean)
            )

    def record_cost(self, cost: CostRecord):
        self.update(
            usage_details={
                "input": cost.input_tokens,
                "output": cost.output_tokens,
                "cache_read_input_tokens": cost.cache_read_input_tokens,
                "cache_creation_input_tokens": cost.cache_creation_input_tokens,
            },
            cost_details={"total": cost.usd},
            metadata={"cost_basis": "published-list-price-equivalent"},
        )

    def record_response(self, response):
        if self._observation is None and self._span is None:
            return
        blocks = sanitize(response.content)
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        output = {"role": "assistant", "content": text or None}
        calls = [
            {
                "id": b["id"],
                "type": "function",
                "function": {
                    "name": b["name"],
                    "arguments": json.dumps(b["input"]),
                },
            }
            for b in blocks
            if b.get("type") == "tool_use"
        ]
        if calls:
            output["tool_calls"] = calls
        self.update(output=[output])
        thoughts = [b["thinking"] for b in blocks if b.get("type") == "thinking"]
        if thoughts:
            self.update(metadata={"reasoning": thoughts})
        if reasoning := getattr(response, "reasoning", None):
            self.update(metadata={"reasoning": reasoning})
        self.set("stop_reason", response.stop_reason)


def flush_tracing():
    if get_settings().tracing_enabled and (client := get_langfuse()) is not None:
        client.flush()


def shutdown_tracing():
    if get_langfuse.cache_info().currsize and (client := get_langfuse()) is not None:
        client.shutdown()
    if _generic_tracer.cache_info().currsize:
        _generic_tracer().shutdown()
