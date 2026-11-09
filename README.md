# Brazilian E-Commerce Customer Support

The Olist-first application now uses the full public historical dataset for
account-scoped SQL lookups and general Brazilian consumer-law retrieval. The
version-3 schema migration and import completed in Neon after explicit approval.
The database measured 291,995,648 bytes after import; the Olist schema measured
281,616,384 bytes (281,247,744 bytes growth from the pre-import baseline).

Imported source rows: 71 categories, 99,441 customers, 32,951 products, 3,095
sellers, 99,441 orders, 112,650 order items, 103,886 payment entries, 99,224
reviews, 42,706 separate review-comment rows and 1,000,163 auditable
geolocation rows, summarized to 19,015 ZIP-prefix aggregates. All 7 foreign-key
checks returned zero orphans. Review comments are isolated from tools because
Portuguese PII redaction is not validated. Coordinates stay in the database and
are not returned by customer tools.

All four knowledge-base profiles use FastEmbed BGE Small 384. Fifteen chunks
were ingested after explicit approval; five prior Gemini vectors remain
preserved and excluded from FastEmbed retrieval. Live legal retrieval returns
Article 49 and official source citations. No hosted answer generation, Render
deployment or real customer authentication has been verified. Public historical
profiles are not verified customer accounts.

Nineteen fixed SQL tools cover historical orders, payments, items, products,
sellers, reviews, delivery, regional summaries and marketplace aggregates.
`consumer_policy` retrieves general Brazilian law, not merchant terms or a
case-specific legal determination. Office Store remains a separate optional
experience.

See [implementation and approval runbook](docs/OLIST_IMPLEMENTATION.md),
[complete data dictionary](docs/OLIST_DATA_DICTIONARY.md),
[policy sources](docs/POLICY_SOURCES.md),
[storage preflight](docs/DATABASE_STORAGE_PREFLIGHT.md), and
[current release readiness](docs/FINAL_RELEASE_READINESS.md).

A FastAPI support assistant with durable PostgreSQL conversations, a staff inbox, tool calls, evidence-checked RAG, PII redaction, prompt-injection defenses, safety checks, evaluations and Langfuse observability. Tracing is enabled with full sampling up to the configurable monthly trace cap; captured fields are redacted before export. Office Store and Olist conversations are isolated. Olist retrieval separates dataset documentation, general Brazilian law and labeled demo procedures; transactions and feedback stay in relational tables. Fictional Office Store policies remain in their own profile.

The Olist Brazilian E-Commerce Public Dataset is historical marketplace data released on Kaggle for roughly 2016–2018. It contains transactional records and post-purchase reviews, **not customer-support chat transcripts or customer-agent conversations**. This project is an independent, non-live demonstration and is not affiliated with Olist. The Kaggle page lists **CC BY-NC-SA 4.0**; attribution, non-commercial use and share-alike terms apply. Review the [dataset source and current terms](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) before reuse. Do not present the demo as live order support.

## What works in the repository

- FastAPI chat with secure browser sessions, saved conversation history and idempotent retry.
- Separate authenticated staff inbox for support handoffs and replies.
- Groq GPT-OSS generation and Groq GPT-OSS Safeguard checks, configured for quota-based use. Limits are account-specific; the app does not promise unlimited free usage.
- PII redaction using Presidio pattern recognizers without loading a large spaCy NER model; injection quarantine; fail-closed safety behavior.
- pgvector RAG with relevance and evidence checks. Missing evidence produces an honest unavailable answer.
- The approved Olist version-3 import is complete in Neon for all nine validated CSVs. The importer maps every source field, keeps review comments in separate restricted storage, and preserves raw geolocation rows plus a deduplicated ZIP-prefix aggregate. Local source files remain ignored under `data/raw/olist/`.
- Approved support knowledge and policies are stored as a separate pgvector RAG source. Olist transactions and reviews are never ingested into that policy knowledge base.
- PostgreSQL `support_conversations` and `support_messages` store conversations created by users in this application. These are application chat history, not Olist historical records. No historical customer-agent conversations are fabricated.
- Langfuse direct tracing is enabled for every eligible request until the application-side monthly trace cap is reached. Check actual usage units in the Langfuse dashboard.
- Separate evaluation scenarios exist for the Olist demo. They are not a scored benchmark.

## Architecture

```mermaid
flowchart LR
  B[Browser] --> A[FastAPI session and authorization]
  A --> P[PII, safety and injection checks]
  P --> G[Groq tool loop and evidence check]
  K[Approved support KB and policies<br/>pgvector RAG] --> G
  G -->|historical lookup tools| Q[Fixed account-scoped SQL]
  Q --> ODB[(PostgreSQL olist_demo<br/>customers, orders, payments,<br/>products, delivery, optional reviews)]
  G -->|application chat only| CDB[(PostgreSQL support schema<br/>user-created conversations/messages,<br/>tickets and staff replies)]
  G --> O[Output safety]
  O --> B
  G -. redacted traces .-> LF[Langfuse observability]
  Staff[Staff bearer key] --> CDB
```

There are three distinct data sources: approved support knowledge and policies for pgvector RAG; Olist's historical transactional tables for fixed read-only SQL tools; and conversations/messages generated by users interacting with this application. Olist tables use the separate `olist_demo` schema. The dataset contains no support chats. Reviews are optional historical feedback, stored separately from the policy knowledge base; comment text is excluded by default and never treated as a transcript or policy. The Olist model cannot execute SQL or perform refunds, cancellations, shipping changes or seller contact. Account choice is bound to an owned, empty application conversation. Order IDs and dataset customer IDs are never authentication credentials; public UI references are opaque aliases. Queries still check that every alias belongs to the selected demo account.

Knowledge profiles filter by profile and embedding provider/model. All four profiles were ingested into Neon with local FastEmbed BGE Small 384 after explicit approval; five old Gemini vectors remain preserved and excluded from FastEmbed retrieval. Verify profile/model coverage before deployment.

See [architecture](docs/ARCHITECTURE.md), [security](docs/SECURITY.md), [dataset and storage](docs/DATABASE_STORAGE_REPORT.md), [evaluations](docs/EVALUATION.md), and [free-tier deployment](docs/FREE_TIER_DEPLOYMENT.md).

## Local setup

Use Python 3.12. Copy `.env.example` to `.env`, generate distinct random 32+ character `ADMIN_API_KEY` and `SERVICE_API_KEY`, and fill in `DATABASE_URL` and `GROQ_API_KEY` locally. Never paste credentials into chat or commit `.env`.

```powershell
uv pip install --python .venv/Scripts/python.exe -e ".[dev,pii,free]"
.venv/Scripts/python.exe -m support_agent.db
.venv/Scripts/python.exe -m support_agent.kb.ingest --docs knowledge_base/approved --profile office_store
.venv/Scripts/python.exe -m uvicorn support_agent.server:app --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001/`. Staff inbox: `/admin/inbox`. Use a PostgreSQL database with pgvector enabled. The app does not import data or run migrations at startup in production. `GET /healthz` is inexpensive liveness; `/readyz` checks database readiness.

To change embedding provider/model, first plan a controlled re-ingestion of each KB profile. Never run `kb.ingest --reset` against shared knowledge data; `--reset` only deactivates the selected profile now.

## Olist dataset and account setup

The dataset files are not included in Git. After dataset download has been authorized, install the Kaggle CLI and run from the repository root:

```powershell
kaggle datasets download -d olistbr/brazilian-ecommerce -p data/raw/olist --unzip
.venv/Scripts/python.exe -m support_agent.olist.importer --validate-only
```

Validation requires all nine expected CSVs, checks columns, nulls, primary-key duplicates, date/numeric formats and foreign-key orphans, then reports file sizes and row counts. Version 3 imports all source fields: comments are stored separately as untrusted text and unavailable to tools pending validated Portuguese redaction; geolocation raw rows and ZIP-prefix aggregates are stored separately. No Olist transaction, review, or customer-agent conversation is embedded into the approved support-policy knowledge base. Raw CSV data remains under the ignored `data/raw/olist/` path.

Prepare the database only after confirming Neon plan, remaining quota and current storage:

```powershell
.venv/Scripts/python.exe -m support_agent.olist.importer --storage-report
.venv/Scripts/python.exe -m support_agent.db
.venv/Scripts/python.exe -m support_agent.olist.migrate
.venv/Scripts/python.exe -m support_agent.olist.importer --report data/reports/olist-import-v3.json
```

Import is one transaction, maps every CSV field, and rolls back if actual database size crosses 700 MB. It preserves support data. The complete local projection is 399.57 MB of growth including comments and raw geolocation; this is not actual Neon growth. Get a fresh `--storage-report`, confirm backups and quota, and review these exact migration/import effects before approval. No Olist import has run. The four KB profiles are already ingested; do not re-ingest them as part of this process. See [storage preflight](docs/DATABASE_STORAGE_PREFLIGHT.md) and [database storage report](docs/DATABASE_STORAGE_REPORT.md).

The primary chat page offers curated historical account selection and displays that account's opaque sample order references. General-law questions can be asked without selecting an account; transaction tools always require one. Office Store requires an explicit profile switch and a separate conversation.

## Tests and evaluations

Run deterministic tests and lint without cloud inference:

```powershell
$env:SAFETY_MODEL_URL=''; $env:TRACING_ENABLED='0'; .venv/Scripts/python.exe -m pytest tests -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check src tests eval
```

PostgreSQL integration tests are opt-in and require an explicitly designated test database. They must never point to the user's production database. The Olist scenarios in `eval/datasets/olist_demo_scenarios.jsonl` cover authorization, missing records, payments, products, historical status, unsupported actions, prompt injection, PII, service failures, ambiguity and evidence gaps. No Olist model evaluation score or tau2-bench result is claimed.

## Render native Python preparation

`render.yaml` describes a native Python Free web service with one worker and no persistent disk. Build command:

```text
pip install --require-hashes -r requirements.lock && pip install -e ".[free]"
```

Start command:

```text
uvicorn support_agent.server:app --host 0.0.0.0 --port $PORT --workers 1 --limit-concurrency 4 --timeout-keep-alive 5 --no-access-log
```

Health path: `/healthz`. Supply Neon, Groq, admin and service secrets through Render's unsynchronized environment variables. Gemini fallback defaults off. Verify every provider's actual account plan and quotas before use. Free Render services sleep after idle and have cold starts; they are for a portfolio demo, not production-critical support. Account-level limits and actual Render memory use remain unverified. See [deployment details](docs/FREE_TIER_DEPLOYMENT.md).

## License and intended use

Application code is MIT licensed. Olist data has separate CC BY-NC-SA 4.0 terms. The demonstration uses public historical, pseudonymous records and curated public demo identities; it is not live customer data or live support. It is not suitable for production-critical customer support. Do not claim current Olist affiliation, commercial dataset rights, live order status, or operations the app cannot perform.
