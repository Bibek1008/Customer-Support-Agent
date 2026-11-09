# Final release readiness

Verified 2026-11-09 for the restored Demo Office Store support application. This pass made local code and documentation edits only. No Neon write, migration, knowledge-base ingestion, hosted inference, deployment, commit, or push was run.

## Product scope

The active application is the original Demo Office Store Support Desk: customer chat, policy retrieval, demo order lookup, ticketing/escalation, and the staff inbox. The five approved documents are `account-access.md`, `billing.md`, `returns-policy.md`, `shipping.md`, and `warranty.md` under `knowledge_base/approved/`.

Olist routes, transaction tools, account mapping, Olist UI, and Olist source modules are absent from `src/` and `website/`; no Olist references remain in the active app, README, SPEC, or Render blueprint. The Neon database still contains rows tagged `brazil_consumer_law`, `olist_demo_policy`, and `olist_transaction_profile`. The restored retrieval query filters these profiles out. This stabilization pass did not delete or change those database rows.

## Verification

- Complete test suite: **170 passed, 3 skipped**. The three skips are the PostgreSQL integration tests, which require an explicitly enabled integration database. Hosted safety and tracing were disabled for the test run; no model inference ran.
- Ruff lint: clean across `eval`, `src`, `tests`, and `ops`.
- Ruff formatter: all 84 Python files in those directories pass. Only the 11 files reported by the requested formatter check were reformatted.
- `.env.example`: all 10 secret-key entries are empty or obvious placeholders; the database URL uses `USER:PASSWORD@HOST:5432/DATABASE`. The existing `.env` remains present and git-ignored; its contents were not printed or changed.
- Render YAML: native Python runtime, locked dependency install, bounded single-worker start command, and `/healthz` check are configured. Production values and secret checklist are described in `docs/RENDER_DEPLOYMENT.md`.

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
