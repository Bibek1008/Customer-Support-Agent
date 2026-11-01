"""A customer-support agent that is reliable and clear about what it does not know.

The package wires together five parts:

- an agent loop over the Claude tool runner (``agent``),
- tools over a knowledge base and a ticketing system (``tools``, ``kb``),
- a guardrail stack that runs on every step (``guardrails``),
- a confidence score and a handoff threshold (``agent.confidence``),
- tracing and exact cost accounting (``observability``).

Every model ID, price, and cited benchmark comes from ``FACTS.md``. Metrics that
describe this agent are produced by the offline eval suite in ``eval/``; this
package never states a benchmark number for itself.
"""

__version__ = "0.1.0"
