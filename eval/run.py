"""Offline eval runner over the held-out ticket set.

    python -m eval.run --suite heldout
    python -m eval.run --suite heldout --check hallucination
    python -m eval.run --suite heldout --check tone

Runs the agent on each held-out ticket, scores the selected metric(s) against the
golden outcomes, and writes ``eval_report.json`` + ``eval_report.md``. Every
number the runner prints was produced by this run on this hardware; nothing is
filled in from memory. On a machine with no ANTHROPIC_API_KEY (or with the SDK
absent) the runner exits early and tells you what to set, rather than inventing
results.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from eval.judges import judge_hallucination, judge_tone
from eval.metrics.accuracy import score_accuracy
from eval.metrics.hallucination import HallucinationTally
from eval.metrics.resolution import score_resolution
from eval.metrics.tone import ToneTally
from support_agent.agent.loop import run_turn
from support_agent.config import get_settings
from support_agent.kb.ingest import ingest_directory
from support_agent.kb.store import get_store
from support_agent.schemas import DecisionType, Trace

_DATASET = Path("eval/datasets/heldout_tickets.jsonl")
_KB_DOCS = Path("eval/datasets/kb_docs")
_OUT_DIR = Path("eval/out")


@dataclass
class TicketRun:
    ticket_id: str
    handed_off: bool
    confidence: float
    answer: str
    resolved: bool | None = None
    correct: bool | None = None
    hallucinated: bool | None = None
    tone_ok: bool | None = None
    detail: str = ""


@dataclass
class EvalSummary:
    n_tickets: int
    checks: list[str]
    handoff_rate: float
    resolution_rate: float | None = None
    accuracy: float | None = None
    hallucination_response_rate: float | None = None
    hallucination_claim_rate: float | None = None
    tone_pass_rate: float | None = None
    per_ticket: list[dict] = field(default_factory=list)


def _load_tickets(limit: int | None, dataset_path: str | Path | None = None) -> list[dict]:
    path = Path(dataset_path) if dataset_path else Path(get_settings().heldout_dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset {path}")
    tickets = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return tickets[:limit] if limit else tickets


def _ensure_kb() -> None:
    if get_store().count() == 0:
        ingest_directory(str(_KB_DOCS))


def run(
    check: str,
    limit: int | None,
    dataset_path: str | Path | None = None,
) -> EvalSummary:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. This eval calls the live model on real "
            "hardware; set the key and re-run. It does not fabricate results."
        )

    _ensure_kb()
    tickets = _load_tickets(limit, dataset_path)
    checks = ["resolution", "accuracy", "hallucination", "tone"] if check == "all" else [check]

    runs: list[TicketRun] = []
    hall = HallucinationTally()
    tone = ToneTally()
    resolved_n = correct_n = correct_denom = resolution_denom = 0

    for ticket in tickets:
        trace = run_turn(
            conversation_id=f"eval-{ticket['id']}",
            user_message=ticket["message"],
            customer_id=ticket.get("customer_id"),
        )
        tr = _score_ticket(ticket, trace, checks, hall, tone)
        runs.append(tr)

        if "resolution" in checks and tr.resolved is not None:
            resolution_denom += 1
            resolved_n += int(tr.resolved)
        if "accuracy" in checks and tr.correct is not None and ticket.get("golden_answer_spans"):
            correct_denom += 1
            correct_n += int(tr.correct)

    handoff_rate = sum(r.handed_off for r in runs) / len(runs) if runs else 0.0
    summary = EvalSummary(
        n_tickets=len(runs),
        checks=checks,
        handoff_rate=round(handoff_rate, 4),
        resolution_rate=round(resolved_n / resolution_denom, 4) if resolution_denom else None,
        accuracy=round(correct_n / correct_denom, 4) if correct_denom else None,
        hallucination_response_rate=round(hall.response_rate, 4) if "hallucination" in checks else None,
        hallucination_claim_rate=round(hall.claim_rate, 4) if "hallucination" in checks else None,
        tone_pass_rate=round(tone.pass_rate, 4) if "tone" in checks else None,
        per_ticket=[asdict(r) for r in runs],
    )
    return summary


def _score_ticket(
    ticket: dict,
    trace: Trace,
    checks: list[str],
    hall: HallucinationTally,
    tone: ToneTally,
) -> TicketRun:
    decision = trace.decision
    handed_off = decision.type == DecisionType.HANDOFF
    answer = decision.answer or ""
    tr = TicketRun(
        ticket_id=ticket["id"],
        handed_off=handed_off,
        confidence=decision.confidence,
        answer=answer,
    )

    if "resolution" in checks:
        res = score_resolution(
            answer=answer,
            handed_off=handed_off,
            golden_kind=ticket.get("golden_kind", "answer"),
            expected_substrings=ticket.get("expected_substrings", []),
        )
        tr.resolved = res.resolved
        tr.detail = res.detail

    if "accuracy" in checks and ticket.get("golden_answer_spans"):
        acc = score_accuracy(answer, ticket["golden_answer_spans"])
        tr.correct = acc.correct

    # Hallucination and tone are scored only on answered responses.
    if not handed_off and answer:
        if "hallucination" in checks:
            verdict = judge_hallucination(answer, decision.citations)
            hall.add(verdict)
            tr.hallucinated = verdict.has_hallucination
        if "tone" in checks:
            tverdict = judge_tone(answer)
            tone.add(tverdict)
            tr.tone_ok = tverdict.meets_rubric

    return tr


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline eval.")
    parser.add_argument("--suite", default="heldout", choices=["heldout"])
    parser.add_argument(
        "--check",
        default="all",
        choices=["all", "resolution", "accuracy", "hallucination", "tone"],
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--dataset",
        default=None,
        help="JSONL ticket dataset (defaults to SUPPORT_HELDOUT_DATASET_PATH)",
    )
    args = parser.parse_args()

    summary = run(check=args.check, limit=args.limit, dataset_path=args.dataset)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    from eval.report import write_report

    write_report(summary)

    print(f"Ran {summary.n_tickets} held-out tickets. Checks: {', '.join(summary.checks)}.")
    print(f"  handoff rate:                {summary.handoff_rate:.1%}")
    if summary.resolution_rate is not None:
        print(f"  resolution rate:             {summary.resolution_rate:.1%}")
    if summary.accuracy is not None:
        print(f"  accuracy:                    {summary.accuracy:.1%}")
    if summary.hallucination_response_rate is not None:
        print(f"  hallucination (per response):{summary.hallucination_response_rate:.1%}")
        print(f"  hallucination (per claim):   {summary.hallucination_claim_rate:.1%}")
    if summary.tone_pass_rate is not None:
        print(f"  tone pass rate:              {summary.tone_pass_rate:.1%}")
    print("Wrote eval_report.json and eval_report.md.")


if __name__ == "__main__":
    main()
