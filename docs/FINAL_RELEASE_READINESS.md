# Release readiness

## Restoration baseline

The restored application baseline is commit `db6a4f4c68208305a910844961aa47d10811f8ab`, the parent of `c72546e` (`chore: organize project and finalize Render deployment preparation`), which is the first commit that adds the Olist integration. The baseline contains Demo Office Store branding, the original Support Desk chat, the five approved KB documents, pgvector RAG, order/ticket tools, escalation, and the staff inbox. The restoration was performed in the worktree only; no branch, index, commit history, or remote was changed.

## Current scope

- Original customer chat and authenticated staff inbox restored.
- Approved KB documents are under `knowledge_base/approved/`; no Brazil-law, FAQ-seed, or Olist aggregate KB is active.
- Olist runtime routes, prompts, transaction tools, schema modules, account mapping, UI, and evaluation scenarios removed from the active worktree.
- Session security, request IDs, rate limits, PII redaction, safety checks, injection defenses, evaluation framework, Groq, FastEmbed, and Langfuse remain.
- Raw local Olist CSV files and `data/reports/` were left untouched. No Neon rows were deleted and no migrations/imports were run.
- The native Python Render blueprint is restored. No deployment was created.

## Verification status

- Full test suite: **170 passed, 3 skipped**. Tests ran with hosted safety and tracing disabled; no hosted model inference was used.
- Playwright with local Edge: customer Support Desk page, original topic shortcuts, cited-answer rendering, and staff inbox access shell passed using mocked chat/session APIs.
- Local FastEmbed: query vector dimension is **384** for `BAAI/bge-small-en-v1.5`.
- Read-only retrieval against the configured Neon vectors returned the matching original policy for shipping, returns, refunds, warranty, billing, and account access. An unrelated astronomy query produced no eligible source after the active-profile and lexical relevance filters. No rows were written.
- Ruff lint and format checks pass for the changed application/retrieval, browser-route, and database-safety test files plus the preserved measurement helpers. A full-repository Ruff check still reports 13 baseline findings in `eval/report.py`, `eval/tau_bench_adapter.py`, and `tests/test_injection.py`; the repository-wide format check reports 11 unrelated files that differ from the configured formatter. Those unrelated files were left unchanged.
- Python compilation and Render Native Python YAML validation passed. Original approved and eval KB fixtures match the baseline commit exactly.
- Neon schema inventory was read-only. Cleanup details are in `docs/OLIST_DATABASE_CLEANUP_PLAN.md`; no Neon rows, migrations, or KB ingestion were changed.

The raw CSVs and `data/reports/` remain untouched. The raw directory is now Git-ignored. No deployment, commit, or push was performed.
