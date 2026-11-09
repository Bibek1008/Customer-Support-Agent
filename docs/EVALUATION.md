# Evaluation

The evaluation framework scores held-out customer-support conversations against expected outcomes and policy evidence. See `eval/datasets/heldout_tickets.jsonl`, `eval/run.py`, `eval/metrics/`, and `docs/EVALUATION_GUIDE.md` for the dataset, runner, metrics, and setup.

The suite covers answer accuracy, citation/evidence grounding, retrieval quality, hallucination, response tone, correct abstention, handoff behavior, PII handling, prompt injection, and tool safety. Deterministic unit tests run without hosted inference. Hosted evaluation is a separate, quota-consuming operation and must be intentionally configured; do not treat unrun model evaluations as passing results.

Run deterministic checks with `python -m pytest tests`. The ingestion command is `python -m support_agent.kb.ingest --docs knowledge_base/approved`; it writes to the configured vector store. Do not ingest into Neon until the user approves, and do not use `--reset` against a shared database. The configured vector space is FastEmbed `BAAI/bge-small-en-v1.5`, dimension 384; stored vectors from another model/provider must not be mixed with it.
