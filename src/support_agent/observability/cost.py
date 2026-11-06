"""Per-step token and dollar accounting.

Cost is arithmetic on the real ``usage`` fields the API returns, multiplied by
the published rates in ``FACTS.md`` Section 1. It is exact, not an estimate, so
the tracing layer can report the dollar cost of a run without any benchmark.

Anthropic prices cache reads at 0.1x the input rate and 5-minute cache writes at
1.25x the input rate. Those multipliers are applied to the input rate below.
"""

from __future__ import annotations

from dataclasses import dataclass

from support_agent.schemas import CostRecord


@dataclass(frozen=True)
class Rate:
    """USD per 1M tokens, input and output, for one model."""

    input_per_mtok: float
    output_per_mtok: float


# Exact rates from FACTS.md Section 1. Sonnet 5 carries an intro rate through
# 2026-08-31; the standard rate is used here so cost is never understated. Swap
# to the intro rate only for runs you know fall inside the intro window.
MODEL_RATES: dict[str, Rate] = {
    # Groq published list rates: https://console.groq.com/docs/model/openai/gpt-oss-20b
    # For Groq this is a list-price equivalent, not the bill on a Free plan.
    "openai/gpt-oss-20b": Rate(input_per_mtok=0.075, output_per_mtok=0.30),
    "openai/gpt-oss-safeguard-20b": Rate(input_per_mtok=0.075, output_per_mtok=0.30),
    "claude-opus-4-8": Rate(input_per_mtok=5.00, output_per_mtok=25.00),
    "claude-sonnet-5": Rate(input_per_mtok=3.00, output_per_mtok=15.00),
    "claude-haiku-4-5": Rate(input_per_mtok=1.00, output_per_mtok=5.00),
}

# Standard Anthropic cache pricing multipliers on the input rate.
_CACHE_READ_MULTIPLIER = 0.10
_CACHE_WRITE_MULTIPLIER = 1.25


def cost_from_usage(model: str, usage: object) -> CostRecord:
    """Build a :class:`CostRecord` from an Anthropic ``usage`` object.

    ``usage`` is any object exposing ``input_tokens``, ``output_tokens``,
    ``cache_read_input_tokens`` and ``cache_creation_input_tokens`` (the
    Anthropic SDK ``Usage`` model, or a plain dict-like stand-in in tests).
    Unknown models raise, because we refuse to invent a price.
    """
    if model not in MODEL_RATES:
        raise KeyError(
            f"No published rate for model {model!r}; add it to MODEL_RATES "
            f"from FACTS.md before charging it."
        )
    rate = MODEL_RATES[model]

    def _field(name: str) -> int:
        value = getattr(usage, name, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(name)
        return int(value or 0)

    input_tokens = _field("input_tokens")
    output_tokens = _field("output_tokens")
    cache_read = _field("cache_read_input_tokens")
    cache_write = _field("cache_creation_input_tokens")

    per_tok_in = rate.input_per_mtok / 1_000_000
    per_tok_out = rate.output_per_mtok / 1_000_000

    usd = (
        input_tokens * per_tok_in
        + output_tokens * per_tok_out
        + cache_read * per_tok_in * _CACHE_READ_MULTIPLIER
        + cache_write * per_tok_in * _CACHE_WRITE_MULTIPLIER
    )

    return CostRecord(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        usd=round(usd, 6),
    )
