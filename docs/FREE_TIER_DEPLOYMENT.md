# Free tier and Render preparation

The service is prepared for Render's native Python Free web service. Current
Render documentation says free services sleep after 15 idle minutes and take
about one minute to restart; filesystem changes are lost after spin-down. It
describes Free as suitable for hobby projects and testing, not production
applications. The instance therefore stores no persistent application data on
its filesystem and uses a single worker. A local offline Windows measurement
initialized the FastAPI app and Presidio, loaded the cached FastEmbed model,
started the TestClient lifespan, and sent four concurrent mocked `/chat`
requests: peak RSS was 319,889,408 bytes (~305 MiB), with ~158 MiB incremental
RSS during model loading. First and warm embeddings took 1,173 ms and 9.7 ms.
The mock prevents hosted inference; no database pool is opened. This excludes a
separate Uvicorn process and Render runtime overhead, so it is a fuller local
baseline but not proof the deployed process fits the 512 MiB limit.

Neon's current published Free plan is $0 and lists 100 CU-hours/project/month,
up to 2 CU, 1 GB/project and 5 GB/month public network transfer. Free compute
scales to zero after 5 idle minutes. The account's plan, usage and the existing
database's actual storage have not been checked. Import is capped at 700 MB
actual PostgreSQL database size, reserving at least 300 MB from a 1 GB ceiling.

The app sends redacted Langfuse traces for every eligible request, up to an
application-side monthly trace cap of 1,000 by default. The cap is a local
safety limit, not a measurement of Langfuse billable units; check actual usage
in the Langfuse dashboard.

Groq Free plan availability and account quota vary. The application limits
concurrent calls, respects a numeric `Retry-After` value for 429 responses,
retries a transient 5xx or structured-output failure at most once, and never
switches to a paid provider automatically. Current account quotas are not
verified. Gemini fallback is disabled.

## Render Blueprint

`render.yaml` uses native Python, a single Uvicorn worker, the cheap `/healthz`
endpoint, the base `requirements.lock` plus the pinned FastEmbed extra, and the
verified app import path. The free extra's transitive package versions are
resolved by pip during the Render build. Build command:

```text
pip install --require-hashes -r requirements.lock && pip install -e ".[free]"
```

Database
migrations, dataset import and KB ingestion are explicit local commands; none
runs on startup. Keep Neon credentials and all API keys in Render's unsynced
secret variables. Render's `RENDER_EXTERNAL_URL` sets the deployed HTTPS origin
automatically when `APP_ORIGIN` retains its local default. Generate distinct
random 32+ character admin and service keys locally.

Before creating a Render service, verify the account still shows the Free
instance and available monthly hours. Creating the service itself is not done
by this repository task.

## Explicit database preparation commands

After checking Neon Free plan and remaining storage/compute, a developer can
run these commands from a local PowerShell window with `.env` set to the chosen
database. Cloud database commands require an explicit review/approval in this
task; they have not been run here.

```powershell
# Read current size; no mutation.
.venv/Scripts/python.exe -m support_agent.olist.importer --storage-report

# After the public Kaggle download has been authorized and placed under data/raw/olist:
.venv/Scripts/python.exe -m support_agent.olist.importer --validate-only
# Or save the report outside Git (data/reports is ignored):
.venv/Scripts/python.exe -m support_agent.olist.importer --validate-only --report data/reports/olist-validation.json

# Explicit migrations only after reviewing the current storage report:
.venv/Scripts/python.exe -m support_agent.db
.venv/Scripts/python.exe -m support_agent.olist.migrate

# Import is one transaction and aborts if the database exceeds 700 MB.
.venv/Scripts/python.exe -m support_agent.olist.importer --report data/reports/olist-import-v3.json
```

The current local app and all four hosted KB profiles use FastEmbed BGE Small
384. Five previous Gemini vectors remain preserved and filtered out. The Olist
version-3 import completed after explicit approval. The fresh database size was
291,995,648 bytes; measured Olist growth was 281,247,744 bytes, below the
399.57 MB projection and 700 MB cap. The importer preserved support data. Do not
re-ingest the KB during transaction initialization; do not use `--reset` against
shared profiles.

The application sends redacted traces at 100% sampling up to its app-side cap;
check the Langfuse usage dashboard during the month. Set `TRACING_ENABLED=0`
only when intentionally pausing exports. Observability errors never block chat
responses.
