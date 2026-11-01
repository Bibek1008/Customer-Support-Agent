"""Sweep the confidence threshold and pick tau* holding hallucination <= target.

    python -m eval.threshold --hallucination-target 0.02 --k 8

For each candidate threshold tau, we re-derive what the agent would have done:
answers with confidence >= tau are kept, answers below tau become handoffs. On
the kept answers we measure coverage (fraction of tickets answered) and the
hallucination rate. tau* is the largest tau at which the hallucination rate is at
or below the target; below tau the agent escalates.

To keep the sweep cheap, each held-out ticket is run once through the agent and
its answer is judged for hallucination once; the sweep then re-applies each
candidate tau to those cached per-ticket results. The curve (tau, coverage,
hallucination rate) is written to ``threshold_curve.json`` for the report and the
website figure.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from eval.judges import judge_hallucination
from support_agent.agent.loop import run_turn
from support_agent.config import get_settings
from support_agent.kb.ingest import ingest_directory
from support_agent.kb.store import get_store
from support_agent.schemas import DecisionType

_DATASET = Path("eval/datasets/heldout_tickets.jsonl")
_KB_DOCS = Path("eval/datasets/kb_docs")
_CURVE = Path("threshold_curve.json")


@dataclass
class _PerTicket:
    confidence: float
    handed_off: bool
    hallucinated: bool  # only meaningful when the agent answered


def _collect(k: int, dataset_path: str | Path | None = None) -> list[_PerTicket]:
    """Run every held-out ticket once; cache its confidence and hallucination."""
    if get_store().count() == 0:
        ingest_directory(str(_KB_DOCS))
    path = Path(dataset_path) if dataset_path else Path(get_settings().heldout_dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset {path}")
    tickets = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    rows: list[_PerTicket] = []
    for ticket in tickets:
        # Run k independent trials and take the mean confidence, so a single
        # lucky/unlucky draw does not move tau* (this is the pass^k spirit
        # applied to the confidence estimate).
        confidences: list[float] = []
        hallucinated = False
        answered_once = False
        for _ in range(max(1, k)):
            trace = run_turn(
                conversation_id=f"thr-{ticket['id']}",
                user_message=ticket["message"],
                customer_id=ticket.get("customer_id"),
            )
            decision = trace.decision
            confidences.append(decision.confidence)
            if decision.type == DecisionType.ANSWER and decision.answer:
                answered_once = True
                verdict = judge_hallucination(decision.answer, decision.citations)
                hallucinated = hallucinated or verdict.has_hallucination
        mean_conf = sum(confidences) / len(confidences)
        rows.append(
            _PerTicket(
                confidence=mean_conf,
                handed_off=not answered_once,
                hallucinated=hallucinated,
            )
        )
    return rows


def sweep(target: float, k: int, dataset_path: str | Path | None = None) -> dict:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. The threshold sweep runs the live "
            "model on real hardware; set the key and re-run."
        )

    rows = _collect(k, dataset_path)
    curve = []
    tau_star = None
    for i in range(0, 101, 5):
        tau = i / 100.0
        answered = [r for r in rows if not r.handed_off and r.confidence >= tau]
        coverage = len(answered) / len(rows) if rows else 0.0
        hall_rate = (
            sum(r.hallucinated for r in answered) / len(answered) if answered else 0.0
        )
        curve.append(
            {"tau": tau, "coverage": round(coverage, 4), "hallucination_rate": round(hall_rate, 4)}
        )
        if hall_rate <= target and coverage > 0:
            # Largest tau that still holds the target: keep updating as tau rises,
            # but we want the LARGEST tau meeting the target, so record it and let
            # later (higher) taus overwrite only if they also meet the target.
            tau_star = tau

    result = {
        "hallucination_target": target,
        "k": k,
        "tau_star": tau_star,
        "curve": curve,
        "n_tickets": len(rows),
    }
    _CURVE.write_text(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Pick tau* holding hallucination under target.")
    parser.add_argument("--hallucination-target", type=float, default=0.02)
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument(
        "--dataset",
        default=None,
        help="JSONL ticket dataset (defaults to SUPPORT_HELDOUT_DATASET_PATH)",
    )
    args = parser.parse_args()

    result = sweep(
        target=args.hallucination_target,
        k=args.k,
        dataset_path=args.dataset,
    )
    print(
        f"Swept {result['n_tickets']} tickets at k={result['k']} "
        f"against hallucination target {result['hallucination_target']:.1%}."
    )
    if result["tau_star"] is None:
        print(
            "No threshold held hallucination under the target on this set. "
            "Improve retrieval or raise the target; do not ship a fabricated tau*."
        )
    else:
        print(f"Chosen tau* = {result['tau_star']:.2f}. Set HANDOFF_THRESHOLD to this value.")
    print("Wrote threshold_curve.json.")


if __name__ == "__main__":
    main()
