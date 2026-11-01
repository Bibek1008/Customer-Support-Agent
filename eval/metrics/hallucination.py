"""Hallucination rate, RAGTruth-style unit of analysis.

The hallucination rate is the fraction of *answered* responses that contain at
least one claim not supported by a retrieved chunk or a tool result. Handoffs
are excluded from the denominator, because a handoff makes no factual claim to
ground. The per-claim judging is delegated to ``eval.judges.judge_hallucination``
(the LLM judge that copies the RAGTruth protocol); this module aggregates.
"""

from __future__ import annotations

from dataclasses import dataclass

from eval.judges import HallucinationVerdict


@dataclass
class HallucinationTally:
    answered: int = 0
    responses_with_hallucination: int = 0
    claims_total: int = 0
    claims_unsupported: int = 0

    def add(self, verdict: HallucinationVerdict) -> None:
        self.answered += 1
        self.claims_total += verdict.claims_total
        self.claims_unsupported += verdict.claims_unsupported
        if verdict.has_hallucination:
            self.responses_with_hallucination += 1

    @property
    def response_rate(self) -> float:
        """Fraction of answered responses with any unsupported claim."""
        if self.answered == 0:
            return 0.0
        return self.responses_with_hallucination / self.answered

    @property
    def claim_rate(self) -> float:
        """Fraction of factual claims that were unsupported."""
        if self.claims_total == 0:
            return 0.0
        return self.claims_unsupported / self.claims_total
