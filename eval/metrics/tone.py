"""Tone rubric scoring.

The tone rate is the fraction of answered responses that meet the five-point
brand tone rubric. Per-response judging is delegated to ``eval.judges.judge_tone``;
this module aggregates. Handoff messages are excluded by the evaluation runner.
"""

from __future__ import annotations

from dataclasses import dataclass

from eval.judges import ToneVerdict


@dataclass
class ToneTally:
    scored: int = 0
    met: int = 0
    points_sum: int = 0

    def add(self, verdict: ToneVerdict) -> None:
        self.scored += 1
        self.points_sum += verdict.points_met
        if verdict.meets_rubric:
            self.met += 1

    @property
    def pass_rate(self) -> float:
        if self.scored == 0:
            return 0.0
        return self.met / self.scored

    @property
    def average_points(self) -> float:
        if self.scored == 0:
            return 0.0
        return self.points_sum / self.scored
