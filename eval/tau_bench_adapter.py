"""Optional external cross-check: run the agent against tau-bench / tau2-bench.

    python -m eval.tau_bench_adapter --domain retail

This is a comparison against the cited references in ``FACTS.md`` Section 2, not
our headline. tau-bench's reliability metric is **pass^k**: the fraction of tasks
solved on *all* k independent trials (not "at least one"), which is what a support
deployment cares about. This adapter wraps our agent so tau-bench's user
simulator can drive it, and computes pass^k over the runs.

The tau-bench package is an optional, heavier dependency (it ships its own task
databases and user simulator). We import it lazily and print install
instructions if it is missing, rather than vendoring their data.
"""

from __future__ import annotations

import argparse

from support_agent.agent.loop import run_turn


class SupportAgentPolicy:
    """Adapter so tau-bench can call our agent as its policy.

    tau-bench hands the policy the running message history and the available
    tools; it expects an assistant action back (a message or a tool call). Our
    agent already owns its tool loop, so we expose a single-turn entry point and
    let tau-bench treat the whole resolution as one policy step per user turn.
    """

    def __init__(self, domain: str):
        self.domain = domain

    def act(self, conversation_id: str, user_message: str) -> str:
        trace = run_turn(conversation_id=conversation_id, user_message=user_message)
        decision = trace.decision
        return decision.answer or ""


def _run(domain: str, k: int) -> None:
    try:
        # tau-bench exposes its environments and a runner; see
        # https://github.com/sierra-research/tau-bench
        from tau_bench.envs import get_env  # type: ignore
        from tau_bench.run import run_pass_k  # type: ignore
    except ImportError:
        raise SystemExit(
            "tau-bench is not installed. Install it from "
            "https://github.com/sierra-research/tau-bench to run this cross-check. "
            "This is an optional comparison against FACTS.md Section 2, not our "
            "headline metric."
        )

    env = get_env(domain)
    policy = SupportAgentPolicy(domain=domain)
    # run_pass_k runs each task k times and reports the fraction solved on all k.
    results = run_pass_k(env=env, policy=policy, k=k)
    print(f"tau-bench {domain} pass^{k}: {results['pass_k']:.3f} over {results['n_tasks']} tasks.")
    print(
        "Reference (FACTS.md 2.1): GPT-4o is under 50% at pass^1 and under 25% at "
        "pass^8 in retail. Compare, do not conflate with our held-out numbers."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-check against tau-bench.")
    parser.add_argument("--domain", default="retail", choices=["retail", "airline", "telecom"])
    parser.add_argument("--k", type=int, default=8)
    args = parser.parse_args()
    _run(domain=args.domain, k=args.k)


if __name__ == "__main__":
    main()
