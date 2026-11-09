"""Emit the eval report: JSON, Markdown, and (when matplotlib is present) figures.

The report only ever contains numbers this run measured. When a metric was not
selected, its row shows the reproduce command from ``FACTS.md`` Section 5 instead
of a value, so a reader can tell "not measured yet" from "measured and low".
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eval.run import EvalSummary

_JSON = Path("eval_report.json")
_MD = Path("eval_report.md")
_FIG_DIR = Path("figures")

# Reproduce commands for metrics that were not measured in a given run.
_REPRODUCE = {
    "resolution_rate": "python -m eval.run --suite heldout",
    "accuracy": "python -m eval.run --suite heldout",
    "hallucination_response_rate": "python -m eval.run --suite heldout --check hallucination",
    "tone_pass_rate": "python -m eval.run --suite heldout --check tone",
    "tau_star": "python -m eval.threshold --hallucination-target 0.02 --k 8",
}


def write_report(summary: EvalSummary) -> None:
    _JSON.write_text(json.dumps(asdict(summary), indent=2))
    _MD.write_text(_render_markdown(summary))
    _maybe_write_figure(summary)


def _cell(value: float | None, key: str, fmt: str = ".1%") -> str:
    if value is None:
        return f"run: `{_REPRODUCE.get(key, 'python -m eval.run')}`"
    return format(value, fmt)


def _render_markdown(summary: EvalSummary) -> str:
    lines = [
        "# Eval report: production support agent",
        "",
        (f"Held-out tickets: **{summary.n_tickets}**. Checks run: {', '.join(summary.checks)}."),
        "",
        (
            "Every value below was measured on this run. Rows shown as a `run:` "
            "command were not part of this run; execute the command to measure them."
        ),
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Handoff rate | {summary.handoff_rate:.1%} |",
        f"| Resolution rate | {_cell(summary.resolution_rate, 'resolution_rate')} |",
        f"| Accuracy | {_cell(summary.accuracy, 'accuracy')} |",
        (
            f"| Hallucination rate (per response) | "
            f"{_cell(summary.hallucination_response_rate, 'hallucination_response_rate')} |"
        ),
        (
            f"| Hallucination rate (per claim) | "
            f"{_cell(summary.hallucination_claim_rate, 'hallucination_response_rate')} |"
        ),
        f"| Tone pass rate | {_cell(summary.tone_pass_rate, 'tone_pass_rate')} |",
        f"| Handoff threshold tau* | run: `{_REPRODUCE['tau_star']}` |",
        "",
        "## Reference points (cited; other systems, not this agent)",
        "",
        ("- tau-bench GPT-4o: pass^1 under 50%, pass^8 under 25% in retail (arXiv 2406.12045)."),
        ("- AgentDojo GPT-4o: 69% benign utility, 45% under attack (OpenReview m1YYAQjO3w)."),
        "- tau-bench airline leaderboard ceiling near 0.70 (verify live).",
        "",
        (
            "These frame the problem; the headline for this agent is the resolution "
            "rate and hallucination rate above, plus the tau* that holds hallucination "
            "under target."
        ),
    ]
    return "\n".join(lines) + "\n"


def _maybe_write_figure(summary: EvalSummary) -> None:
    """Draw a small bar of the measured rates, if matplotlib is available."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    metrics = {
        "resolution": summary.resolution_rate,
        "accuracy": summary.accuracy,
        "hallucination": summary.hallucination_response_rate,
        "tone": summary.tone_pass_rate,
    }
    labels = [k for k, v in metrics.items() if v is not None]
    values = [metrics[k] for k in labels]
    if not labels:
        return

    _FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.bar(labels, values, color="#0f8f68")
    ax.set_ylim(0, 1)
    ax.set_ylabel("rate")
    ax.set_title(f"Measured on {summary.n_tickets} held-out tickets")
    for i, v in enumerate(values):
        ax.text(i, v + 0.02, f"{v:.0%}", ha="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(_FIG_DIR / "eval_rates.png", dpi=150)
    plt.close(fig)
