"""LLM-as-judge prompts: grounded hallucination check and tone rubric scorer.

Both judges use the cheap classifier (Haiku 4.5) with structured JSON output.
The hallucination judge copies the RAGTruth unit of analysis (FACTS.md Section
2.5): it splits the answer into factual claims and marks any claim not supported
by a retrieved chunk or a tool result as a hallucination. The tone judge scores
against the five-point rubric in ``agent.prompts``.

Every judge output should be spot-audited by a human before it is trusted as a
headline number; the judges make the metric cheap to compute at scale, not
authoritative on their own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from support_agent.agent.models import classifier_kwargs, get_client
from support_agent.agent.prompts import GROUNDING_RULE, TONE_RUBRIC
from support_agent.schemas import Citation

_HALLUCINATION_SCHEMA = {
    "type": "object",
    "properties": {
        "claims_total": {"type": "integer"},
        "claims_unsupported": {"type": "integer"},
        "unsupported_examples": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims_total", "claims_unsupported", "unsupported_examples"],
    "additionalProperties": False,
}

_TONE_SCHEMA = {
    "type": "object",
    "properties": {
        "meets_rubric": {"type": "boolean"},
        "points_met": {"type": "integer"},
        "notes": {"type": "string"},
    },
    "required": ["meets_rubric", "points_met", "notes"],
    "additionalProperties": False,
}


@dataclass
class HallucinationVerdict:
    claims_total: int
    claims_unsupported: int
    examples: list[str]

    @property
    def has_hallucination(self) -> bool:
        return self.claims_unsupported > 0


@dataclass
class ToneVerdict:
    meets_rubric: bool
    points_met: int
    notes: str


def judge_hallucination(answer: str, citations: list[Citation]) -> HallucinationVerdict:
    """Flag claims in ``answer`` not supported by ``citations`` (RAGTruth-style)."""
    sources = "\n\n".join(
        f"[{i + 1}] {c.source_title}: {c.chunk}" for i, c in enumerate(citations)
    ) or "(no sources were retrieved)"

    system = (
        "You are a grounding auditor for a support agent. "
        + GROUNDING_RULE
        + " Split the answer into individual factual claims. For each claim, "
        "decide whether a retrieved source supports it. Count the total claims "
        "and the unsupported ones, and quote up to three unsupported claims."
    )
    user = f"ANSWER:\n{answer}\n\nRETRIEVED SOURCES:\n{sources}"

    data = _judge(system, user, _HALLUCINATION_SCHEMA)
    return HallucinationVerdict(
        claims_total=int(data.get("claims_total", 0)),
        claims_unsupported=int(data.get("claims_unsupported", 0)),
        examples=list(data.get("unsupported_examples", []))[:3],
    )


def judge_tone(answer: str) -> ToneVerdict:
    """Score ``answer`` against the five-point brand tone rubric."""
    system = (
        "You are scoring a support answer against a brand tone rubric. "
        + TONE_RUBRIC
        + " Return whether it meets the rubric overall and how many of the five "
        "points it satisfies."
    )
    data = _judge(system, f"ANSWER:\n{answer}", _TONE_SCHEMA)
    return ToneVerdict(
        meets_rubric=bool(data.get("meets_rubric", False)),
        points_met=int(data.get("points_met", 0)),
        notes=str(data.get("notes", "")),
    )


def _judge(system: str, user: str, schema: dict) -> dict:
    kwargs = classifier_kwargs()
    resp = get_client().messages.create(
        **kwargs,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    return json.loads(text)
