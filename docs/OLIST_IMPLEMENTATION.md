# Olist implementation and approval runbook

Updated 2026-11-09. After explicit approval, support schema version 4 and the
additive Olist version-3 schema were applied, then all nine Olist CSVs were
imported in one transaction. Neon measured 291,995,648 bytes after import;
`olist_demo` tables measured 281,616,384 bytes. All 99,224 review rows, 42,706
separate comment rows, 1,000,163 raw geolocation rows and 19,015 ZIP aggregates
were verified with zero relationship orphans. The import preserved existing
support data and KB vectors. The separate approved FastEmbed ingestion added 15
chunks and preserved five Gemini vectors. No hosted inference, paid resource,
Render deployment, commit or push occurred.

Live retrieval for the reported online-return/withdrawal-period question now
returns Article 49 and the electronic-commerce decree with official URLs. An
empty knowledge profile is detected before embedding, and its setup diagnostic
reaches the customer reply instead of the generic unknown-answer message.

## Interface and routing

Olist is the default new-conversation profile and primary interface. Office Store
requires an explicit switch and a separate conversation. Existing conversations
are not rewritten. The SQL schema default remains compatible with older rows;
the repository explicitly supplies the Olist default on new conversation inserts.

Nine customer choices cover historical tracking/history, payments, products,
delivery performance, returns, refunds, product issues and feedback. Account
selection precedes transaction choices and shows clickable public sample order
references. Transaction choices are disabled without an account. General-law
questions do not require account selection, subject to approved KB initialization.

The accounts endpoint distinguishes `not_initialized`, `upgrade_required`,
`no_accounts` and `ready`. A version-3 completed-import marker is required. It
explains missing initialization and never silently switches to Office Store.
Simple whole-message greetings/thanks use local replies. Mixed greeting/support
messages continue through semantic intent classification and existing safeguards.

## Fixed, read-only SQL tools

All transaction tools require a server-selected account. The model can supply
only validated public aliases, never identity or SQL. Every lookup enforces
account scope in backend parameterized queries. Shared queries intentionally
serve related tool names.

| Tool | Data and limits |
|---|---|
| `olist_order_history` | Up to 20 newest orders and total purchase frequency/count |
| `olist_order_lookup` | One order's recorded status/dates, item/freight totals and seller count |
| `olist_order_items` | Up to 100 item lines: product/seller aliases, category, price, freight, shipping limit |
| `olist_product_lookup` | Category, dimensions, weight, photos/name/description-length counts, account-observed sales/prices |
| `olist_category_lookup` | Authorized translated category and product details |
| `olist_historical_prices` | Account-observed minimum, maximum and mean item price, BRL |
| `olist_payment_summary` | Total, methods, entry count and each payment entry |
| `olist_installments` | Payment-entry method/value/installment count; no due-date schedule |
| `olist_seller_info` | Public alias, state, selected-account statistics and dataset-wide seller sales, delivery and review metrics |
| `olist_delivery_status` | Purchase, approval, carrier handover, actual/estimated delivery timestamps |
| `olist_delivery_comparison` | Actual minus estimated calendar days; nonnegative delay; null for missing comparison |
| `olist_delivery_performance` | Account totals, comparable/late/missing denominators and mean date difference |
| `olist_cancellation_statistics` | Account recorded canceled/unavailable counts |
| `olist_review_lookup` | Historical scores and creation/answer timestamps; no comments |
| `olist_feedback_history` | Up to 50 account feedback entries with public order references |
| `olist_marketplace_summary` | Historical dataset order counts, cancellation and late rates, average review score |
| `olist_payment_distribution` | Historical payment-method counts, shares and recorded amounts |
| `olist_category_satisfaction` | Category-level structured review scores; groups under 100 observations suppressed |
| `olist_regional_statistics` | Brazilian state order counts; groups under 100 orders suppressed |

Product lookup also returns dataset-wide product popularity and structured review
statistics alongside the selected profile's observed prices. Review-comment
sentiment and complaint themes remain unavailable until Portuguese PII
validation is complete.

The complete nine-CSV field dictionary, null counts and coverage decisions are
in [OLIST_DATA_DICTIONARY.md](OLIST_DATA_DICTIONARY.md). No raw IDs or customer
location are displayed. Order/item tools discover aliases for follow-up calls.
Product/seller account measures and dataset-wide aggregates are labeled separately.
Item/payment queries are separate to prevent join multiplication. Missing dates
stay unknown; source timestamps have no invented timezone. Prices are historical.

## Policy-aware RAG

`consumer_policy` searches only `brazil_consumer_law`. Olist `knowledge_base`
searches that profile plus `olist_transaction_profile` (dataset documentation)
and `olist_demo_policy` (demo procedures). Both paths exclude `office_store`.
Profile/provider/model filtering remains mandatory. Legal ingestion and retrieval
validate complete provenance, an official source allowlist and BR jurisdiction.
Transaction/review documents cannot be ingested as policies.

The UI labels historical transaction records, official legal sources,
demonstration assumptions and unavailable information. Legal citations retain
article, authority, URLs, retrieval date, jurisdiction, status and version. General
law is never Olist policy or proof that an old order qualifies for a remedy.
Unknown company terms remain unknown; individual legal determinations require
qualified review. Demo staff review cannot contact a real merchant or guarantee
legal relief. See [POLICY_SOURCES.md](POLICY_SOURCES.md).

## Reviews and geolocation

Version 3 stores review scores/dates in `reviews` and source comment title/message
in a separate `review_comments` table keyed to the source row. Comments are
untrusted data; customer tools, RAG, citations and generated answers cannot read
them. The bounded first-200 regex fallback scan is not representative and does
not validate Portuguese PII detection. Any future comment search, sentiment or
customer-facing use must first apply validated Portuguese PII redaction and
instruction quarantine. No comments are embedded as policy.

Version 3 preserves all 1,000,163 geolocation CSV rows in `geolocation_raw`,
including source row number, ZIP prefix as text, coordinates, city and state. It
builds `geolocation_prefixes` by deduplicating coordinate pairs within each ZIP
prefix and stores source counts, unique-point counts, a centroid and source-state
list. ZIP prefixes stay text to preserve leading zeroes. These data support
internal regional aggregates; no exact coordinate or customer location is
returned by a customer tool. The storage estimate includes the raw rows.

## Initialization commands and approval status

Before hosted changes, confirm recovery/backup, Neon quota, fresh database and
index sizes, compatible vector dimensions and the storage projection below
700 MB. Never delete or replace existing support data. Do not use `--reset` on
shared KB profiles. The four KB profiles and version-3 migrations/import were
run against the configured Neon database after explicit user approval; running
them against another target requires a separate review.

Offline measurements are safe to repeat:

```powershell
$env:TRACING_ENABLED='0'
.venv/Scripts/python.exe -m support_agent.olist.preflight
.venv/Scripts/python.exe ops/build_olist_reports.py
```

Only after explicit approval for the intended database:

```powershell
.venv/Scripts/python.exe -m support_agent.olist.importer --storage-report
.venv/Scripts/python.exe -m support_agent.db
.venv/Scripts/python.exe -m support_agent.olist.migrate
.venv/Scripts/python.exe -m support_agent.olist.importer --report data/reports/olist-import-v3.json
```

The completed version-3 importer validated all nine files and mapped every source field. It
stores reviews/comments separately, preserves every geolocation row, builds the
ZIP-prefix aggregate, creates opaque historical references and records release 3
only after success. It preserves support conversations/tickets. The complete
local projection is 399.57 MB of growth including all comments/geolocation and
50% base margin. In this instance, measured `olist_demo` growth was 281,247,744
bytes, below the estimate. The importer
requires the fresh preflight and checks the 700 MB ceiling inside its transaction.
Excess triggers rollback, although PostgreSQL allocation/WAL still require
measurement. Same version/fingerprint retries are idempotent. Replacing the
source snapshot needs a separately reviewed alias/import plan.

The four KB profiles were already ingested with FastEmbed after explicit user
approval. Do not re-ingest them as part of Olist import. Before any future
re-ingestion, verify the target embedding space:

```powershell
$env:EMBEDDING_PROVIDER='fastembed'
$env:EMBEDDING_MODEL='BAAI/bge-small-en-v1.5'
$env:EMBEDDING_DIM='384'
```

If the existing vector column has another dimension, STOP before re-ingestion.
The schema initializer does not change existing vector dimensions. Prepare a
compatible staging target and approve a separate preservation/storage/cutover
migration; do not truncate or blindly alter shared vectors. Existing vectors and
support data must remain recoverable. Current hosted vector shape/model coverage
was not rechecked in this local-only phase.

Provider/model filters exclude incompatible vectors. Re-ingestion archives older
chunks only for the same profile/model/provider/source. Legacy `olist_demo`
chunks remain preserved but are excluded from new Olist retrieval paths.
Production requires the three Olist document profiles with its configured model.
Startup now checks readiness only; migrations/imports are explicit operations.

Before deployment, verify actual storage/indexes, legal source metadata, profile
coverage, account isolation, citations, missing initialization and all security
controls against a dedicated test database. Local SQL integration tests are
prepared in `tests/test_olist_postgres.py` and always roll back synthetic changes.
They refuse remote destinations and never load .env credentials. No local
PostgreSQL runtime was available. See [FINAL_RELEASE_READINESS.md](FINAL_RELEASE_READINESS.md).
