# Final release readiness

Date: 2026-11-09. **Local implementation verified; hosted release is NOT READY.**
The Olist-first interface and account-scoped tools are implemented. Version-3
transaction initialization completed on Neon after explicit approval. Fifteen
FastEmbed KB chunks were uploaded, all five Gemini vectors
were preserved, and the local app was switched to FastEmbed and restarted.
Live legal retrieval for the reported question returned Article 49 and the
e-commerce decree. Real Neon query paths returned historical results; hosted
answer generation and dedicated local PostgreSQL integration remain unverified.

## Verification performed

| Check | Result | Practical limit |
|---|---|---|
| Full Python suite | **245 passed, 4 skipped**, 28.05 seconds | Offline scripted model responses and deterministic embeddings; no hosted inference |
| Browser tests | **8 passed** within full suite | Chrome/Playwright on mobile and desktop; all app APIs mocked |
| Existing PostgreSQL integration | **3 skipped** | No explicitly enabled dedicated PostgreSQL test database |
| New Olist PostgreSQL integration | **1 skipped** | No loopback `OLIST_TEST_DATABASE_URL`; actual joins, date arithmetic and account isolation remain unverified on PostgreSQL |
| Ruff | **Pass** for src/tests/eval and new report generator | No new lint errors |
| Diff whitespace | **Pass** | Windows line-ending conversion notices are informational |
| Nine-CSV validation and import | **Pass, zero errors** | All source rows imported; zero relationship orphans; comments separated and raw geolocation retained |
| Source translation gaps | **Preserved** | 13 products without English category translation remain with source-category fallback |
| Review/privacy investigation | **Risk scan only** | Review comments map to a separate table, but tools cannot access them; Windows blocked Presidio and Portuguese privacy coverage is unvalidated |
| Full geolocation | **Imported and verified** | 1,000,163 raw rows and 19,015 ZIP-prefix aggregates; exact coordinates are not exposed to customer tools |
| UI visual inspection | **Pass** | Reviewed mobile/desktop screenshots; no horizontal overflow; account selector precedes transaction choices |
| Local web server | **Restarted; `/readyz` returns ready** | Startup performs read-only readiness checks against Neon |

Browser checks cover cited law answers, failed-message retry, end-session compose
disabling, public account/sample-order selection, uninitialized dataset state,
explicit Office Store isolation, responsive layout and staff inbox authentication,
reply/sign-out. The screenshots use mocked initialization data, not a real Neon
import. Screenshots are local under `.cache/olist-mobile.png` and
`.cache/olist-desktop.png`.

Olist regression checks cover conservative no-inference small talk and mixed
requests; required account context across all nineteen tools; account parameters
and public reference validation; multiple items/payment entries/installments;
missing records; seller/product/delivery/feedback query boundaries; comment PII
and injection assessment without text release; profile isolation and provenance;
return/refund/warranty/delivery legal retrieval with official URLs and BR
jurisdiction; unknown policy abstention; unsupported merchant terms, raw internal
IDs and unperformed refund claims; and qualified individual-case review.
Existing prompt-injection, safety, PII, confidence, tracing, sessions and request
controls remain covered. These checks do not establish a hosted model's semantic
accuracy. Real PostgreSQL semantics are intentionally not claimed from mocks.

## Storage projection

Measured source CSVs total **126.19 MB**. Complete version-3 import growth was
estimated at **399.57 MB** and measured at **281,247,744 bytes** for the Olist
schema. A fresh database measurement after import was **291,995,648 bytes**,
below the 700 MB project target. The account's broader plan usage is not
verified.
See [DATABASE_STORAGE_PREFLIGHT.md](DATABASE_STORAGE_PREFLIGHT.md).

## Release blockers and required approvals

1. Run actual SQL/ownership/date-arithmetic tests against a dedicated local
   PostgreSQL/pgvector test database. No local PostgreSQL runtime was available.
   The new Olist test accepts only loopback, port 5433, `support_agent_test`, rejects
   remote/host-address overrides and always rolls back synthetic changes.
2. **Completed:** additive support/Olist migrations and version-3 import were
   approved and applied. Preserve support data; another target or replacement
   source snapshot needs its own review.
3. **Completed for KB:** the existing column was verified as `vector(384)`. The
   approved local FastEmbed vectors were added without a schema migration;
   existing Gemini vectors were preserved and were not reused as FastEmbed.
4. **KB ingestion approved and completed:** five legal chunks, four dataset
   documentation chunks, one demo-procedure chunk and five Office Store chunks.
   Continue reviewing English summaries, official source status and case limits.
   The decree's
   original official publication was verified; subsequent consolidated status
   was not independently confirmed. No official Olist company consumer terms
   were verified. General law must never be presented as those terms.
5. Validate functioning Presidio and Portuguese PII coverage before any comment
   search, sentiment analysis or customer-facing use. Raw comments are stored
   separately by the prepared importer but not exposed to tools. Production's
   Presidio requirement remains enforced.
6. With separate approval, evaluate actual Groq generation, intent routing,
   safety, evidence relevance and refusal behavior using reviewed scenarios.
   No hosted inference or model benchmark score is claimed from this phase.
7. Verify Render memory/cold-start capacity, account-specific Groq/Neon/Langfuse
   quotas, model/profile coverage, indexes, backup/recovery and deployment smoke
   behavior. Deployment remains a later explicitly approved action.

## Prepared commands and artifacts

[OLIST_IMPLEMENTATION.md](OLIST_IMPLEMENTATION.md) contains the gated migration
and full version-3 import commands. It explicitly stops on
incompatible vector dimensions. No `--reset` is needed. To run the local SQL test
later, point `OLIST_TEST_DATABASE_URL` explicitly at the dedicated loopback
`support_agent_test` database on port 5433; it never uses .env credentials.

- [Architecture and diagram](ARCHITECTURE.md)
- [Complete dataset field coverage](OLIST_DATA_DICTIONARY.md)
- [Machine-readable local measurements](olist_preflight.json)
- [Official policy source register](POLICY_SOURCES.md)
- [Implementation, SQL tool list, profiles and approval runbook](OLIST_IMPLEMENTATION.md)

Hosted LLM inference, paid resources, Render deployment, commit or push did not
occur. The approved KB ingestion and local embedding switch are recorded above.
No support data was deleted or replaced. Comment use, actual PostgreSQL integration testing, customer authentication and
production readiness remain unverified as described above.
