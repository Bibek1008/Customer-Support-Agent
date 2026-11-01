"""Resolution rate vs golden outcomes.

A ticket counts resolved only when the agent answers (does not hand off) *and*
the golden outcome is reached. Two golden outcome kinds are supported:

- ``answer``: the golden ``expected_outcome`` names substrings that must all
  appear in the agent's answer (e.g. an order status, a policy window).
- ``handoff``: the golden outcome is that the agent should escalate. Here a
  handoff is the correct resolution, not a failure.

This mirrors the FACTS.md definition: resolution rate is the fraction of held-out
tickets the agent closes correctly with no human handoff, except for the tickets
whose correct close *is* a handoff.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResolutionResult:
    resolved: bool
    detail: str


def score_resolution(
    answer: str,
    handed_off: bool,
    golden_kind: str,
    expected_substrings: list[str],
) -> ResolutionResult:
    """Return whether the agent reached the golden outcome for one ticket."""
    if golden_kind == "handoff":
        if handed_off:
            return ResolutionResult(True, "correctly escalated to a human")
        return ResolutionResult(False, "should have escalated but answered instead")

    # golden_kind == "answer": the agent must answer and hit every expected span.
    if handed_off:
        return ResolutionResult(False, "escalated a ticket it should have resolved")

    lowered = answer.lower()
    missing = [s for s in expected_substrings if s.lower() not in lowered]
    if missing:
        return ResolutionResult(False, f"answer missing expected content: {missing}")
    return ResolutionResult(True, "answer reached the golden outcome")
