# Render Native Python deployment

The repository blueprint is `render.yaml`. It defines one Python web service, a bounded single-worker runtime, `/healthz`, PostgreSQL persistence, Groq generation and safety, FastEmbed `BAAI/bge-small-en-v1.5` at 384 dimensions, and Langfuse tracing.

Before creating or updating a Render service, configure `DATABASE_URL`, `GROQ_API_KEY`, distinct `ADMIN_API_KEY` and `SERVICE_API_KEY` values, and the Langfuse public key, secret key, and base URL in Render's secret environment settings. Set `APP_ORIGIN` to the final HTTPS origin. Do not put credentials in `render.yaml`, source files, or browser code.

The service expects the support schema and approved policy chunks to exist in PostgreSQL. Database setup and knowledge-base ingestion are separate write operations. Do not run migrations or ingest into Neon until the database target and operation have explicit approval. Before approved ingestion, confirm that the database vector column and stored vectors match FastEmbed BGE Small at 384 dimensions; do not use `--reset` on a shared database.

Render checks `/healthz` for process liveness. Production readiness also depends on working PostgreSQL access, the approved knowledge base, required credentials, and configured safety checks. A successful health response alone does not establish that chat generation, retrieval, or ticket storage works. No deployment was created as part of the restoration.
