"""Answer correctness against golden answers.

Accuracy is a stricter cousin of resolution: for tickets that carry a
``golden_answer`` key, it checks whether the agent's answer conveys the same
facts. The default check is substring coverage of the golden answer's key spans,
which is deterministic and cheap; a stricter deployment can swap in an LLM judge
that compares the two answers for factual equivalence.

Accuracy is reported alongside resolution because the two can diverge: an agent
can reach the golden *outcome* (resolution) while getting a supporting detail
wrong (accuracy), and catching that gap is the point of measuring both.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AccuracyResult:
    correct: bool
    detail: str


def score_accuracy(answer: str, golden_key_spans: list[str]) -> AccuracyResult:
    """Return whether ``answer`` covers every key span of the golden answer."""
    if not golden_key_spans:
        # No golden answer for this ticket; it does not count toward accuracy.
        return AccuracyResult(correct=True, detail="no golden answer to check")
    lowered = answer.lower()
    missing = [s for s in golden_key_spans if s.lower() not in lowered]
    if missing:
        return AccuracyResult(correct=False, detail=f"missing key facts: {missing}")
    return AccuracyResult(correct=True, detail="covers all golden key facts")
