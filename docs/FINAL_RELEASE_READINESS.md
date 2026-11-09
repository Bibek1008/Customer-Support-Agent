# Final release readiness

Verified 2026-11-09 for the restored Demo Office Store support application. No hosted inference, KB ingestion, deployment, commit, or push was run. One local server restart inadvertently invoked the development auto-migration; its database effects are recorded below.

## Product scope

The active application is the original Demo Office Store Support Desk: customer chat, policy retrieval, demo order lookup, ticketing/escalation, and the staff inbox. The five approved documents are `account-access.md`, `billing.md`, `returns-policy.md`, `shipping.md`, and `warranty.md` under `knowledge_base/approved/`.

Olist routes, transaction tools, account mapping, Olist UI, and Olist source modules are absent from `src/` and `website/`; no Olist references remain in the active app, README, SPEC, or Render blueprint. The Neon database still contains rows tagged `brazil_consumer_law`, `olist_demo_policy`, and `olist_transaction_profile`. The restored retrieval query filters these profiles out. This stabilization pass did not delete or change those database rows.

## Verification

### Second-stage independent review (2026-11-09)

**Readiness blocked by isolated PostgreSQL infrastructure; not cleared for controlled staging.** Reviewed the actual diff and reproduced/fixed missing-context ticket access, malformed server safety responses, and incorrect unconfigured-production checked state. Hardened integration target validation before migrations. Final local suite: **249 passed, 0 failed, 3 skipped**; separate integration-enabled attempt: **0 passed, 3 setup errors, 0 skipped**. Windows application-control policy blocks the portable PostgreSQL initializer/controller, so real database ownership, lease/concurrent-retry and persistence coverage is not established. Ruff, formatting (87 Python files), compilation and diff checks pass. Langfuse checks cover local SDK exporters, including explicit failure; hosted receipt was not verified. Production Neon, `.env`, Render and user edits remain untouched; no commit/push/deploy occurred. See [SECOND_STAGE_REVIEW.md](SECOND_STAGE_REVIEW.md) for scenarios A–E, file rationale, exact blocker and safe integration commands.

### Production guardrail and ticket workflow corrections (2026-11-09, local only)

- Verified against the current code and the supplied November 9 activity exports: canned social/off-topic/unsafe responses returned before `refusal.check_input`; successful `create_ticket` results were not carried into finalization; repeated human requests used a textual reference and returned answer/null-ticket metadata. The specific `tkt_0164680e677f` creation sequence described in the request was reproduced with isolated tests, not independently fetched from production.
- Every uncached agent turn now runs the dedicated input safety gate after PII redaction and before intent classification, ticket recovery, or any early return. Unsafe inputs do not reach routing, generation, or ticket writes. Configured safety providers fail closed on unavailable, malformed, invalid, or unchecked verdicts. The existing unconfigured local-development classifier behavior is unchanged; production validation still requires a provider. Grounded/generated policy answers retain the output safety gate. Fixed refusals and ticket confirmations are application templates, so traces do not invent output-classifier calls for them.
- A validated `ticket` intent represents an explicit request to open a ticket or receive staff follow-up. Only that intent authorizes the reasoner's `create_ticket` call. Existing human-request, pricing-review, and account-recovery escalation routes remain; insufficient evidence or low confidence alone never authorizes a write.
- Successful tool writes immediately set `Trace.created_ticket_id`, stop further model/tool execution, and yield a confirmation and handoff metadata based on the authoritative ticket ID. Finalization cannot replace a committed ticket with a knowledge abstention. Escalations save their initial escalated status in the creation write.
- Repeated human/ticket/follow-up requests verify and reuse an active ticket in the authenticated conversation, with handoff=true, decision=handoff, and the same ticket ID. Resolved or deleted historical references are not treated as proof of an active request. A ticket already committed for the same request ID is recovered after a failed turn even if it has since been resolved. The existing request replay and database request-ID uniqueness protections remain.
- Traces and persisted activity include input-safety/refusal results, ticket-creation authorization, actual ticket results, created/reused state, and final handoff/ticket metadata. Guardrail failures retain only error types. Presidio and masking remain enabled. Canonical request/conversation UUID fields survive numeric PII false positives while configured secrets and ordinary PII remain masked.
- Full suite: **218 passed, 3 skipped** in 17.68 seconds. Added 31 workflow regression cases and two tracing/privacy tests; existing structured-intent tests also cover the new explicit-ticket label. The skips are the three opt-in PostgreSQL integration tests: durable session/isolation/replay/history/staff-reply persistence; conversation leases/stale completion; and database rate-limit/evaluation persistence. No isolated PostgreSQL instance was enabled. New HTTP workflow tests use isolated fake repositories; local tracing tests inspect the real Langfuse SDK with an in-memory exporter. They do not independently verify deployed providers, Neon transactions, or hosted trace delivery.
- Ruff, formatting (85 Python files), Python compilation, and `git diff --check` passed. No model/embedding changes, ingestion, migrations, production Neon writes, hosted inference, deployment, commit, or push were performed. `.env` was untouched and remains ignored/untracked. A separate user edit to the opening sentence of `docs/ARCHITECTURE.md` was preserved.

Files changed for this correction:

| Files | Purpose |
| --- | --- |
| `src/support_agent/agent/loop.py` | Put input safety first, authorize ticket creation, retain committed ticket IDs, and return consistent verified handoff outcomes. |
| `src/support_agent/agent/prompts.py`, `src/support_agent/guardrails/conversation.py` | Distinguish explicit ticket requests from policy questions; remove unverified-reference confirmations. |
| `src/support_agent/guardrails/refusal.py`, `src/support_agent/guardrails/safety.py` | Reject unchecked configured-provider verdicts and record actual verdict/error state. |
| `src/support_agent/tools/registry.py`, `src/support_agent/tools/ticketing.py`, `src/support_agent/tools/handoff.py` | Return authoritative ticket outcomes, redact write contents, retrieve authenticated existing tickets, and create escalations in one write. |
| `src/support_agent/schemas.py` | Track a successful ticket write independently of later answer finalization. |
| `src/support_agent/http_api.py`, `src/support_agent/repository.py` | Persist redacted guardrail audit data on failed turns; support conversation-scoped ticket reuse and request-level recovery. |
| `src/support_agent/observability/tracing.py` | Export ticket/handoff metadata, record failed guardrail checks, and avoid masking validated UUID identifiers while retaining secret/PII masking. |
| `tests/test_workflow_regressions.py` | New isolated HTTP, guardrail-ordering, failure, ticket-confirmation, privacy, replay, and recovery regressions. |
| `tests/test_tracing.py` | Verify real SDK in-memory exports for ticket creation/reuse and identifier/secret masking. |
| `tests/test_conversation_guardrail.py`, `tests/test_production_controls.py` | Update previous buggy metadata expectations and provide real isolated ticket records for reuse checks. |
| `tests/test_gemini_fallback.py` | Preserve the completed-write/no-replay fallback test with a status-update operation; creation now ends with an authoritative confirmation. |
| `docs/FINAL_RELEASE_READINESS.md` | Record local findings, behavior, validation, and remaining verification limits. |

- Complete test suite after the return-policy fallback, migration-startup, and Render PII-model fixes: **180 passed, 3 skipped**. The three skips are the PostgreSQL integration tests, which require an explicitly enabled integration database. Hosted safety and tracing were disabled for the test run; no model inference ran.
- Ruff lint: clean across `eval`, `src`, `tests`, and `ops`.
- Ruff formatter: all 84 Python files in those directories pass. Only the 11 files reported by the requested formatter check were reformatted.
- `.env.example`: all 10 secret-key entries are empty or obvious placeholders; the database URL uses `USER:PASSWORD@HOST:5432/DATABASE`. The existing `.env` remains present and git-ignored; its contents were not printed or changed.
- The website's exact suggested question, “What is your return policy?”, retrieves `returns-policy` first with a citation from the configured Neon store. Three recent saved turns had no knowledge-base tool call and therefore abstained without citations. The agent now performs a read-only retrieval fallback when a model finishes without using the knowledge-base tool; it only returns the matched source excerpt after the normal relevance and confidence checks. No source match still yields the existing unknown response.
- Render YAML: native Python 3.12 runtime, locked dependency install, bounded single-worker start command, and `/healthz` check are configured. Presidio explicitly uses the installed spaCy small English model to avoid an automatic 400 MB model download during startup; noisy organization-only NER results are ignored. Production values and secret checklist are described in `docs/RENDER_DEPLOYMENT.md`.
- Local Windows runtime probe with FastAPI, Presidio small model, FastEmbed 384d, a bounded psycopg pool, and 24 concurrent mocked chats: **375.9 MiB peak working set**, **709.1 MiB peak private committed memory**. Production database readiness and safety inference were mocked; the pool used a refused loopback address. This is not a Render cgroup measurement; details and startup/shutdown timings are in `docs/RENDER_DEPLOYMENT.md`.
- Render startup stabilization: production credential checks remain synchronous, while Presidio and one-query PostgreSQL/schema/policy readiness checks run after the server lifespan starts. The live Groq safety probe was removed from startup; each real customer input and generated response remains safety-checked, with provider outages returning 503. `/healthz` is liveness only, `/readyz` reports required dependency readiness, and persisted customer/staff routes return 503 until ready. Locally, mocked production lifespan setup took **20.1 ms** and health returned 200; real small-model Presidio initialization took **2,159.6 ms** in the background, with **193.2 MiB** working set (**202.6 MiB peak**) and **525.3 MiB** private committed memory. The database, safety inference, and embedding model were mocked/not loaded. Render's earlier logs had no per-operation timings, so they do not identify which old synchronous check consumed the deployment timeout. See `docs/RENDER_DEPLOYMENT.md`.

## Database startup incident

Restarting the local development server ran `migrate()` automatically. Its support-schema transaction completed; the subsequent KB schema transaction failed while creating the unique `(source_id, content_hash)` index because five hash groups are duplicated. A read-only audit afterward found schema version 4, 20 KB vectors, zero null content hashes, five duplicate hash groups, and no unique index. The failed KB transaction rolled back, and no policy vectors were ingested or deleted. The support-schema DDL transaction may have applied idempotent `CREATE ... IF NOT EXISTS` statements. Development startup and vector-store connection no longer run migrations; migrations must be invoked explicitly.

## Neon embedding compatibility and policy citations

The inventory ran in a PostgreSQL read-only transaction. The `kb_chunks.embedding` column is `vector(384)` and all 20 stored vectors report 384 dimensions. Metadata contains five active office-store chunks using `fastembed` / `BAAI/bge-small-en-v1.5`, five legacy Gemini office-store chunks, five Brazil-law chunks, and five Olist-profile chunks. Runtime retrieval filters by the configured FastEmbed model/provider and the empty or `office_store` profile, so it selects only the five compatible office-store chunks and excludes the other profiles. No re-embedding is required for the current five approved policies.

Read-only retrieval used local FastEmbed embeddings with tracing disabled. All five queries returned citations with the expected policy ranked first: warranty (0.738), shipping (0.688), returns (0.774), billing (0.737), and account access (0.763).

If a future approved policy change or model switch requires ingestion, use this non-destructive sequence:

1. Inventory provider/model/profile metadata, active counts, source IDs, and vector dimensions in a read-only transaction; verify and record a database backup before any write.
2. Prepare chunks and local FastEmbed vectors outside Neon. Compare the five expected source IDs, chunk counts, content hashes, and 384-dimensional vectors against the approved files.
3. Review a plan to upsert only the compatible `office_store` profile, preserving unrelated profiles and the old vectors. Never use `--reset` or truncate shared KB data.
4. Run a policy-by-policy citation check against the candidate vectors, then review counts and retrieval results before any separately authorized database write. Keep the previous compatible vectors available until the new set is verified.

## Render production checklist

The blueprint sets `APP_ENV=production`, persistent PostgreSQL, demo mode with fixture orders disabled, Groq generation and safety, FastEmbed BGE Small at 384 dimensions, and Langfuse tracing tagged as `production`. Configure these manual Render values before deploying:

- `DATABASE_URL` for the approved PostgreSQL database and `APP_ORIGIN` for the final HTTPS service origin.
- `GROQ_API_KEY` for generation and safety.
- Distinct random `ADMIN_API_KEY` and `SERVICE_API_KEY` values, each at least 32 characters.
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and the project-region `LANGFUSE_BASE_URL`.

Confirm the support schema and five approved office-store chunks are present before starting the service. `/healthz` checks process liveness only; validate database access, policy citations, chat, ticket storage, staff access, and Langfuse traces in the deployment environment. No Render service has been created or updated.
