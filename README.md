# Customer Support Agent

A customer support application with a Next.js TypeScript frontend, a FastAPI backend, document retrieval, safety checks, and human escalation. The application demonstrates a fictional Demo Office Store; its policies and sample orders are demonstration data.

## Live application

| Service | URL |
| --- | --- |
| Customer chat (Vercel) | https://customer-support-agent-c28c.vercel.app/ |
| Staff inbox (Vercel) | https://customer-support-agent-c28c.vercel.app/admin/inbox |
| Backend (Render) | https://customer-support-agent-k21j.onrender.com/ |
| Backend readiness | https://customer-support-agent-k21j.onrender.com/readyz |

Staff access requires the private `ADMIN_API_KEY`. Render's free backend can sleep when idle; the frontend loads independently and displays a startup state while it checks backend readiness. AI provider rate limits and quotas can also delay or prevent answers.

## Features

- Saved conversations and staff replies backed by PostgreSQL.
- Answers grounded in approved knowledge-base documents, with source citations.
- Returns, shipping, billing, warranty, and account support.
- PII redaction, safety classification, and injection checks.
- Confidence and relevance checks, clarification, and human handoff.
- Staff ticket review, replies, status updates, and activity/evaluation reports.
- Groq inference with optional Gemini fallback for quota errors.
- FastEmbed embeddings, PostgreSQL/pgvector retrieval, and optional Langfuse tracing.

The default extractive answer mode selects approved source excerpts after relevance and evidence checks. Missing knowledge produces an explicit unknown response; staff review remains available on request. Evaluation scores must come from an actual run on a documented dataset.

## Deployment architecture

```text
Browser -> Next.js on Vercel -> FastAPI on Render
                                  |-- PostgreSQL / pgvector
                                  |-- Approved knowledge base
                                  |-- AI and safety providers
                                  `-- Optional tracing
```

The Next.js server proxies an allowlisted set of API routes through `/api/backend/`. It validates frontend request origins, forwards session cookies and staff authorization, and uses the backend origin for upstream requests. This keeps browser sessions first-party on Vercel without adding cross-origin browser requests.

### Vercel frontend

Set the Vercel project **Root Directory** to `frontend`, choose the Next.js framework, and use Node.js 24. Configure this server-only environment variable:

```dotenv
BACKEND_URL=https://customer-support-agent-k21j.onrender.com
```

The frontend proxy declares a 300-second maximum function duration. Ensure your Vercel runtime supports it; see [function duration settings](https://vercel.com/docs/functions/configuring-functions/duration). Full setup and verification instructions are in [frontend/README.md](frontend/README.md).

### Render backend

The Native Python blueprint is [render.yaml](render.yaml). Keep this backend setting:

```dotenv
APP_ORIGIN=https://customer-support-agent-k21j.onrender.com
```

Keep database credentials, provider keys, staff/service keys, and tracing credentials on Render. Use [.env.example](.env.example) as the configuration reference. To enable the existing Gemini quota fallback, configure:

```dotenv
GEMINI_FALLBACK_ENABLED=true
GEMINI_API_KEY=your-private-key
```

Gemini fallback requires available Gemini quota and access to the model configured by the backend. Keep the existing Groq settings. Save environment changes and deploy them before testing. Local `.env` changes do not update Render.

The backend retains small HTML chat and staff pages for compatibility with its existing routes. The public frontend is the Next.js app on Vercel; the old static landing page and its separate Vercel configuration have been removed.

## Local development

### Frontend against the deployed backend

```powershell
cd frontend
Copy-Item .env.example .env.local
npm.cmd ci
npm.cmd run dev
```

Set `BACKEND_URL` in `frontend/.env.local` to the Render URL above. Open http://localhost:3000. Use `npm` instead of `npm.cmd` on macOS/Linux. To use a local backend, set `BACKEND_URL=http://127.0.0.1:8001`.

### Python backend

Use Python 3.12 and run from the repository root:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev,pii,free]"
.venv/Scripts/python.exe -m spacy download en_core_web_sm
Copy-Item .env.example .env
```

Copy the example environment file only when creating a new local configuration; preserve any existing `.env`. Configure a development PostgreSQL database with the `vector` extension and the providers you intend to use. The deployed configuration uses 384-dimensional FastEmbed `BAAI/bge-small-en-v1.5` embeddings. Changing embedding models requires re-embedding documents, even if dimensions match.

Run schema setup and ingestion only against the database you intend to modify:

```powershell
.venv/Scripts/python.exe -m support_agent.db
.venv/Scripts/python.exe -m support_agent.kb.ingest --docs knowledge_base/approved
.venv/Scripts/python.exe -m uvicorn support_agent.server:app --host 127.0.0.1 --port 8001 --no-access-log
```

Schema setup and ingestion write to `DATABASE_URL`. Server startup does not automatically migrate the database. Keep `PERSISTENCE_ENABLED=1` for saved browser conversations. Use distinct staff and service keys and follow the production settings in [deployment instructions](docs/RENDER_DEPLOYMENT.md).

## Verification

Frontend checks, from `frontend/`:

```powershell
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test:smoke
```

The smoke check uses a temporary mock backend to verify pages, cookie and authorization forwarding, origin handling, endpoint restrictions, body limits, and backend error propagation. It does not test live model quotas or the deployed database.

Backend unit checks, from the repository root:

```powershell
$env:SAFETY_MODEL_URL=''
$env:TRACING_ENABLED='0'
.venv/Scripts/python.exe -m pytest tests -p no:cacheprovider
```

Database integration tests require a separate, explicitly configured test database. After deployment, verify a chat answer, history restoration, source citations, a staff reply appearing in chat, ticket status updates, and reconnect after backend inactivity. See [verification](docs/VERIFICATION.md) and the [evaluation guide](docs/EVALUATION_GUIDE.md) for detailed procedures.

## Repository layout

```text
frontend/                Next.js TypeScript customer chat and staff inbox
src/support_agent/       FastAPI, agent loop, storage, guardrails, and tools
knowledge_base/approved/ Approved support documents
website/                 Compatibility HTML pages served by FastAPI
tests/                   Backend unit and database integration tests
eval/                    Evaluation runners, datasets, metrics, benchmarks
ops/                     Verification and measurement scripts
docs/                    Architecture, security, deployment, evaluation guides
external/benchmarks/     Benchmark provenance and download metadata
render.yaml              Render backend blueprint
requirements.lock        Hashed Python dependency lock
```

Local caches, virtual environments, model downloads, generated evaluation reports, environment files, and recovery backups are ignored. They are not deployment source. Do not commit secrets or customer records.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [security](docs/SECURITY.md)
- [Frontend setup](frontend/README.md) and [Render deployment](docs/RENDER_DEPLOYMENT.md)
- [Production operations](docs/PRODUCTION.md) and [verification](docs/VERIFICATION.md)
- [Evaluation](docs/EVALUATION.md), [dataset documentation](docs/DATASET_DOCUMENTATION.md), and [benchmark setup](docs/BENCHMARK_SETUP.md)
- [Release readiness](docs/FINAL_RELEASE_READINESS.md), [reference facts](FACTS.md), and [original specification](SPEC.md)
