"""Offline eval suite for the support agent.

The four metrics that matter (resolution rate, hallucination rate, tone, and the
handoff threshold tau*) are produced here, on the held-out ticket set, on real
hardware. Nothing in this package states a number for the agent that a run did
not measure; a value that has not been measured is shown as its reproduce
command, per ``FACTS.md`` Section 5.
"""
