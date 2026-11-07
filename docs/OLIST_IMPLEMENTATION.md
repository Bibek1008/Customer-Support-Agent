# Olist extension audit and execution record

Audit date: 2026-11-07. Branch: main. Initial working tree: clean.

## Existing application

FastAPI serves the customer chat and separate staff inbox. PostgreSQL stores
sessions, conversations, idempotent turns, tickets, replies, audit events and
evaluations. Fixed tool handlers, semantic routing, source relevance checks,
Presidio, injection quarantine and hosted input/output safety checks exist.
pgvector chunks already carry embedding model/provider metadata. Langfuse is
integrated directly. Unit tests mock providers; database tests are opt-in.
The tau2 adapter previews/executes the external benchmark's agent; downloading
its data does not establish a benchmark result for this application.

## Gaps and risks found before implementation

- No Olist importer, schema, customer authorization or profile isolation.
- Existing KB uniqueness uses source/content only: re-embedding replaces vectors.
- Default Presidio loads en_core_web_lg; its memory is unsuitable to assume a
  512 MB deployment. FastEmbed memory has not been measured with the whole app.
- Production startup makes a safety inference; avoid spending quota on restarts.
- Local Gemini fallback was enabled, but billing state is unverified. The new
  zero-cost constraint requires it disabled pending verification.
- Pool defaults to ten connections. No global inference concurrency control,
  provider Retry-After handling, trace sampling or monthly observation budget.
- Langfuse setup/update failures can interrupt requests.
- README mixes obsolete tutorial instructions with current behavior.
- Render native Python configuration is prepared in `render.yaml`.

## Incremental implementation plan

1. Verify public free-tier documentation and dataset attribution. Keep actual
   account quotas/billing explicitly unverified until dashboard confirmation.
2. Validate all nine CSVs offline. Build additive olist_demo migrations,
   transaction-safe idempotent bulk import and database storage preflight.
3. Add curated demo accounts, opaque public aliases and fixed read-only queries
   that enforce ownership independently of model arguments.
4. Isolate office_store/olist_demo knowledge and preserve original documents
   and held-out tickets. Version embeddings without replacing existing vectors.
5. Preserve guardrails; add authorization/regression cases, resource controls,
   optional resilient sampled tracing and separate Olist evaluation scenarios.
6. Prepare native Render Free configuration and reproducible local preparation
   commands. Measure memory and report platform limitations honestly.
7. Run tests/lint, document evidence and outstanding cloud verification.

No commit, push, deployment, paid service or billing activation is authorized.
No cloud import or inference before applicable account free-tier verification.

## Current status (2026-11-07)

The additive schema, importer, account-scoped Olist tools, profile-aware
retrieval, account selector, Render blueprint, migration guidance, and offline
evaluation scenarios are prepared locally. The nine source CSVs are present in
the ignored `data/raw/olist/` directory and passed local validation. Counts
include 99,441 customers, 99,441 orders, 112,650 items, 103,886 payments,
32,951 products, 3,095 sellers, 99,224 reviews, and 71 category translations.
Geolocation and free-text review comments are excluded from the initial import;
13 untranslated-category products are retained with a fallback label. No
Olist data has been imported into Neon.

The approved read-only Neon storage preflight measured 9,650,176 bytes
(9.20 MiB) before Olist import. The 170 MB planning allowance projects
179,650,176 bytes total; this is an estimate, not a post-import measurement.
See [DATABASE_STORAGE_PREFLIGHT.md](DATABASE_STORAGE_PREFLIGHT.md).

The local offline FastEmbed/application probe measured 319,889,408 bytes
(~305 MiB) process peak RSS with Presidio, FastAPI TestClient lifespan and four
concurrent mocked chat requests. It did not use hosted inference, open a DB
pool, or run in Render, so it does not establish target-runtime memory fit.
Provider account plans and quotas remain unverified. No migration, import,
hosted model inference, deployment, commit, or push was performed. The one
approved database action was the read-only sizing query.

Latest local suite: `171 passed, 3 skipped`; the skips are PostgreSQL integration
tests without an explicitly configured local test database. Ruff lint and
format checks, Python compilation, application `/healthz`/frontend smoke test,
and Render/OTel YAML parsing passed. Browser tests use mocked APIs. See
`docs/FINAL_RELEASE_READINESS.md` for limitations and the release decision.
