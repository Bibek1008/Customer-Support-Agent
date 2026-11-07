# Final release readiness

Date: 2026-11-07. This phase ran local checks only. The only cloud interaction
was the previously approved read-only Neon sizing query. No Neon migrations or
imports, hosted model calls, paid resources, or deployment occurred. Container
deployment files and their CI/task references were removed for the Render native
Python target. GitHub publication status is reported in the release-session
result.

## Decision

**NOT READY.** PostgreSQL-backed behavior and the full database load test remain
unverified because no PostgreSQL test database is configured locally, and cloud
database writes were not authorized. The owner has since confirmed rotation or
revocation of the historical Gemini credential and the Langfuse credentials
exposed during local configuration work. Render capacity, account quotas, and
live deployment behavior also remain unverified.

## Verification results

| Check | Result | Evidence / limitation |
|---|---|---|
| Full Python suite | **PASS** | 179 passed, 3 skipped in 37.06s; no failures. Includes all five Playwright browser tests. |
| PostgreSQL integration | **SKIPPED** | `pytest -rs` confirms all three skips are because `SUPPORT_TEST_DATABASE` is not set to `1`. No local PostgreSQL executable, Windows service, or listener on ports 5432/5433 was found. No test used Neon. |
| New load-test DB guard | **PASS** | Six tests accept only `support_agent_test` on loopback:5433 and reject Neon/remote hosts, other DB names/ports, and URL query overrides. |
| Full-app load measurement | **NOT RUN** | `ops/measure_full_app.py` is prepared, but requires the dedicated local pgvector database described below. It refuses remote database targets before importing the app. |
| Python dependency audit | **PASS WITH EXCLUSIONS** | Both `pip-audit -r requirements.lock` and `pip-audit --local` found no known vulnerabilities. The environment audit could not audit `en-core-web-lg` (model package) or editable `support-agent` because they are not PyPI distributions. `pip check` passes. |
| Frontend dependency audit | **NOT APPLICABLE** | No `package.json` or npm/yarn/pnpm lockfile exists; no JavaScript package tree is present. The landing page references Google Fonts remotely, which is an external asset rather than an installed package. |
| Git-history secret scan | **PASS, ROTATION CONFIRMED BY OWNER** | Scanned 282 reachable blobs (2,419,055 bytes) across 40 commits. No private-key or common provider-token signature was found. A historical Gemini key candidate was treated as exposed; the owner confirmed rotation/revocation. The owner also confirmed rotation/revocation of Langfuse credentials exposed during a later local configuration edit. |
| Browser E2E | **PASS, MOCKED** | Chrome/Playwright tests cover cited chat and retry, session ending, Olist account-selection UI, and staff login/inbox/reply/sign-out. Every backend endpoint is mocked; these do not verify database authorization or persistence. |
| App smoke | **PASS, TEST MODE** | FastAPI TestClient returned `/healthz` 200 and frontend 200 while persistence was disabled. Does not verify production database startup. |
| Ruff / compile / config | **PASS** | Ruff lint, format check (92 files), Python compilation, Render YAML/runtime/build/start/health checks, `pip check`, and Windows-aware `git diff --check` pass. |
| Frontend build | **NOT APPLICABLE** | The frontend is static HTML/CSS/JavaScript with no package manifest or build command. Five Playwright browser tests are included in the full suite and use mocked APIs. |
| Olist dataset validation | **PASS** | Ran the local `--validate-only` command against nine CSVs; report written to ignored `data/reports/olist-validation.json`. Thirteen untranslated categories were preserved with the configured fallback; no import was run. |

The three skipped PostgreSQL tests in `tests/test_database_integration.py` cover
durable chat/session isolation and staff reply flow, turn leases/stale completion,
and rate-limit/evaluation persistence. Each test run calls the project migration
and writes synthetic rows. They must remain counted as skipped until they run
against an explicitly approved, isolated test database.

## Repository cleanup

Removed the container-only `Dockerfile`, `docker-compose.yml`,
`compose.production.yaml`, `.dockerignore`, and `ops/Caddyfile`. The Caddyfile
was referenced only by the removed production Compose configuration. Removed
the Docker image CI job and the `make db-up` target. Updated the website,
operations, Olist, specification, and verification documentation for Render
native Python, Neon PostgreSQL, Groq, FastEmbed, and Langfuse. README and
architecture docs were reviewed and already match that deployment direction. No
application source, migration, test, evaluation dataset, approved knowledge-base
document, Olist importer, Render config, or required dependency was removed.
No Python packages were removed; Anthropic remains an implemented optional
provider. There is no frontend package manifest or build pipeline; browser E2E
tests exercise the static frontend with mocked backend APIs.

The repository already follows the main maintainable layout: application code
is in `src/support_agent/`, tests in `tests/`, evaluation code/data in `eval/`,
approved and Olist knowledge profiles in `knowledge_base/`, source CSVs and
validation output in `data/`, operational scripts in `ops/`, documentation in
`docs/`, the static frontend in `website/`, and optional third-party benchmark
checkouts in `external/`. No empty placeholder packages or unnecessary module
splits were introduced. Root configuration (`pyproject.toml`, requirements
files, `render.yaml`, `Makefile`) remains at the root where packaging, Render,
or developer tooling expects it. `FACTS.md` stays at the root because code and
docs reference it directly; `SPEC.md` is the project-level specification.
`eval_report.json`, `eval_report.md`, and `threshold_curve.json` remain local
generated artifacts at the root: the evaluator and verification scripts
currently write/read those exact paths, and `.gitignore` excludes them. Moving
them without changing those workflows would break report generation and
references. No source files were relocated in this phase; existing reports
and datasets were retained.

Temporary local state was retained rather than destructively cleaned: `.venv`,
`.cache`, `.ruff_cache`, Python bytecode, and the two inaccessible pytest temp
directories are ignored by Git. `.env`, downloaded Olist data, and generated
data reports are also ignored. Docker-only deployment files were removed as
listed above. No dependency versions were changed in this organization and
configuration audit.

### Local environment configuration audit

The root `.env` was inspected locally using variable names and effective
non-secret settings only; no values were printed, logged, copied, or sent to
any service. It is ignored by `.gitignore` and is not in the Git index. The
effective local setup is Groq for chat and safety, Gemini `gemini-embedding-001`
for embeddings, and Gemini fallback disabled. This local Gemini embedding space
is distinct from Render's FastEmbed `BAAI/bge-small-en-v1.5` space; never reuse
vectors between them. Provider credentials configured locally include
Anthropic, Groq, Gemini, OpenAI, Hugging Face, Neon/database, staff/service, and
Langfuse variables. Their values are not recorded here.

`.env.example` now mirrors the 41 variable names and ordering in the local
`.env`, with non-secret settings aligned for reproducibility. Credential,
database, and private endpoint values are blank in the example; only `.env`
contains the real local values. `ROUTER_MODEL` was removed from both dotenv
files because no runtime or evaluation code consumes it. Other optional
provider/model settings remain available for the Anthropic, OpenAI, self-hosted
safety, evaluation, and tracing paths implemented by the project.

During a local dotenv edit, the Langfuse public and secret key assignments were
briefly copied into `.env.example` and displayed in a local tool result. The
example has since been sanitized and `.env` was preserved. The owner confirmed
that both Langfuse credentials were rotated or revoked. This adds to the
historical Gemini credential rotation review below.

Render must receive secrets through the service environment settings, not from
the repository. The `sync: false` entries in `render.yaml` are `GROQ_API_KEY`,
`DATABASE_URL`, `ADMIN_API_KEY`, `SERVICE_API_KEY`, `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL`. Set `APP_ORIGIN` to the deployed
HTTPS origin if required by the chosen Render configuration; `RENDER_EXTERNAL_URL`
is available as an automatic fallback. Keep `GEMINI_FALLBACK_ENABLED=0` unless
its use is explicitly approved and quotas are confirmed. Before deployment,
rotate the locally configured provider, database, staff/service, and observability
credentials as appropriate, configure distinct staging and production values,
and verify no secret has been added to the index. The historical Gemini
credential candidate below needs immediate rotation if it was valid; deployment-
time rotation must not be treated as confirmation that it has already occurred.

### PostgreSQL integration test options

Docker is not required for Render deployment or these tests. For a fully local
option, install PostgreSQL with the `vector` extension using a native Windows
PostgreSQL distribution or another approved local PostgreSQL service, create a
dedicated empty database named `support_agent_test`, and listen only on
`127.0.0.1:5433`. Confirm the installed server has the pgvector extension
available before running tests. The existing test guard and load harness accept
only that database name and loopback host/port for the full-app load harness.
The three integration tests themselves only check the `SUPPORT_TEST_DATABASE=1`
opt-in; they do not validate the URL host, database name, or staging identity.
No local PostgreSQL server was available during this verification, so this
option has not been run.

A separate Neon staging branch/database can also serve as a PostgreSQL
integration target in principle, provided the project has the required
PostgreSQL/pgvector compatibility and the connection is positively verified as
the dedicated staging target. Neon branches provide isolated database
environments; a branch may initially inherit its parent data, so use an empty
dedicated test database or otherwise confirm the test target contains no
production data. Never point these tests at the production URL or promote/merge
the staging branch as part of testing. Neon documents branch isolation and
pgvector support ([branch model](https://neon.com/blog/neon-object-hierarchy),
[pgvector](https://neon.com/blog/optimizing-postgres-vector-search)).

The suite is not read-only: its fixture runs `migrate()` and test cases insert
synthetic conversations, turns, rate-limit records, evaluations, and tickets.
Therefore no staging run is authorized by this report. Before a staging run,
obtain explicit approval for those schema/data writes, create/verify a separate
staging database, and set `DATABASE_URL` from that staging branch in a private
local shell (do not paste the URL into chat or commit it). Independently verify
the host and database identity from the Neon dashboard before enabling the
tests; `SUPPORT_TEST_DATABASE=1` alone is not a production safety check. Then
the operator can opt into the test gate:

```powershell
$env:SUPPORT_TEST_DATABASE='1'
$env:DATABASE_URL='<verified isolated staging database URL>'
$env:SAFETY_MODEL_URL=''
$env:TRACING_ENABLED='0'
.venv/Scripts/python.exe -m pytest tests/test_database_integration.py -p no:cacheprovider
```

The command is documented only; it was not run. `ops/measure_full_app.py` has a
deliberately stricter loopback-only guard and cannot be pointed at Neon. Use a
local PostgreSQL service for that measurement. Remove the disposable local test
database after review if desired; no cleanup of an existing or cloud database
is authorized here.

## Dependency and secret findings

The hash-locked Python requirements and the installed environment both returned
“No known vulnerabilities found.” The audit omitted `en-core-web-lg` because it
is not a PyPI distribution and `support-agent` because it is the local editable
project. No dependency was upgraded or removed. The `pip-audit` tool was
installed only into `.venv`; it was not added to project requirements.

The current-tree check found `.env` ignored and absent from the Git index;
`data/raw/` and `kaggle.json` are ignored, and no Olist CSV is tracked. The
`.env.example` API/database credentials are blank or placeholders. A
signature-only scan of tracked and untracked non-ignored files found no actual
provider token signature; URL-shaped matches are synthetic test examples and
configuration defaults, and values were not printed. The history scan found no
tracked private configuration such as `.env`,
`kaggle.json`, private-key files, or credential bundles. Its only
high-priority manual review is the unverified literal Gemini key assignment in
`.env.example` at commits:

- `.env.example` — `11abf6aa5e8e`
- `.env.example` — `90e12c071a1b`
- `.env.example` — `db6a4f4c6820`

The value was never printed by the history scan. The current working
`.env.example` has blank credential/private endpoint values. The owner confirmed
the historical Gemini credential was rotated and revoked. Git history was not
rewritten. Also rotate any credentials placed in those examples outside Git if
they were reused. Other matches were local
database examples, blank templates, or environment-variable references. The
scan is broad but heuristic; it is not a Gitleaks-certified result.

## Embedding migration readiness

The intended Render vector space is `fastembed` / `BAAI/bge-small-en-v1.5` /
384 dimensions. The local configuration’s Gemini model also emits 384 values,
but those vectors are incompatible. Retrieval SQL filters by profile,
`embedding_provider`, and `embedding_model`; the unit test
`test_vector_search_filters_profile_provider_and_model` verifies that all
three predicates and parameters are used.

Safe staged plan, not executed:

1. In a disposable local PostgreSQL database, set `EMBEDDING_PROVIDER=fastembed`,
   `EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, and `EMBEDDING_DIM=384`. Keep
   tracing off and use the local model cache; do not use Gemini for embedding.
2. Ingest the profiles separately, without `--reset`:

   ```powershell
   .venv/Scripts/python.exe -m support_agent.kb.ingest --docs knowledge_base/approved --profile office_store
   .venv/Scripts/python.exe -m support_agent.kb.ingest --docs knowledge_base/olist_demo --profile olist_demo
   ```

3. Verify active chunk counts for each profile/provider/model, expected source
   IDs and document coverage. Run the retrieval/citation evaluation for
   Office Store policies and the Olist dataset overview; confirm no result
   crosses profiles or model spaces. Repeat ingestion and confirm counts stay
   stable. Existing unit coverage verifies repeat-ingestion idempotence in the
   in-memory store; database-backed idempotence was not run here.
4. Only after staging passes, request separate approval for any production
   database operation. Ingest the two profiles one at a time with the exact
   target settings, then deploy those same settings. The content-addressed
   upsert is transactional and keys rows by profile/model/source/content; old
   provider/model rows remain available and retrieval will not mix them.
5. Roll back by restoring the former provider/model settings. Do not delete old
   embeddings during cutover. Remove old rows only after validation, a backup,
   an explicit retention decision, and separate approval.

Ingestion marks chunks inactive only for sources included in that run. If a
document was removed from the input directory, its old rows are not automatically
retired; reconcile the source list explicitly before declaring a profile fully
replaced. No Neon connection or re-ingestion occurred.

## Browser/backend coverage

The expanded browser suite now covers the customer chat, source citation UI,
retry text, customer session ending, Olist demo account-selection UI, and staff
key/inbox/reply/sign-out behavior. All browser API responses are simulated.
Existing TestClient/unit coverage separately checks session revocation,
authorization rules, staff throttling, PII, and retrieval. The real PostgreSQL
tests remain skipped, so database persistence, cross-customer isolation, actual
staff ticket persistence, Olist account isolation against populated tables,
and database outage behavior are **not verified end to end**.

## Resource results

The previous 305 MiB figure and this repeat run use `ops/measure_fastembed.py`.
The probe had FastAPI/application modules imported, initialized Presidio,
loaded FastEmbed BGE Small, entered FastAPI TestClient lifespan, and sent four
concurrent `/chat` requests with the intent classifier mocked. It disables
hosted safety, hosted inference, tracing, and database persistence. The RSS
baseline is taken after module imports, so transient import-time peaks may be
underrepresented. It excludes a PostgreSQL connection pool, a separate Uvicorn
process, real model calls, Render overhead, and real database load.

Latest repeat run: **320,016,384 bytes peak RSS (~305.2 MiB)** from a baseline of
155,131,904 bytes; the incremental peak was 164,884,480 bytes (~157.2 MiB).
First/warm embedding times were **1,161.5 ms / 7.6 ms**. These are local Windows
measurements, not Render capacity evidence.

The new `ops/measure_full_app.py` measures FastAPI startup, Presidio, FastEmbed,
local PostgreSQL migration/connection-pool startup, and four concurrent
mocked-agent requests with persisted conversation history. It records peak
working set and per-request latency, disables hosted providers, uses the local
embedding cache, and refuses anything except `support_agent_test` on
127.0.0.1:5433. It was not run because no local PostgreSQL service was available.
No Render compatibility claim is made.

## Database and remaining cloud requirements

The approved read-only Neon query measured **9,650,176 bytes (9.20 MiB)** before
Olist import. Olist growth is estimated at 120–165 MB; the 170 MB planning
allowance projects **179,650,176 bytes (~171.33 MiB)**, about 520.35 MB below
the 700 MB target. Current usage is measured; import growth and projected total
are estimates. No Olist migration/import was run.

Before public deployment, still verify account quotas and plans for Neon, Groq,
Langfuse, and Render; target-runtime memory/cold start/network/readiness; live
staff/customer workflows; Langfuse export and redaction; and deployment secrets.
The `ops/otel-collector.yaml` file is optional and not wired into `render.yaml`.
The local Render YAML parse is syntax validation only, not a deployment test.

## Render native-Python deployment checklist

`render.yaml` configures `runtime: python`, a Python dependency build command,
Uvicorn start command, one worker, bounded concurrency, and `/healthz`. The
container-only deployment files were removed; Render uses its native Python
runtime.

Before creating a staging service, verify the Render plan's memory/runtime
limits and the Neon/Groq/Langfuse quotas. In Render, confirm the service is
using the Blueprint's native Python runtime and that the configured build and
start commands match `render.yaml`. Keep production and staging secrets separate;
configure the staging service with a dedicated Neon staging database URL and
staging-only staff/service credentials. Do not copy production data into a test
branch unless the data is approved for that environment.

After explicit approval for the relevant cloud writes, create a staging service
and staging database, apply schema changes only to staging, and verify startup,
`/healthz`, login/logout and revocation, customer isolation, staff inbox/reply,
conversation/ticket persistence, RAG citations and both KB profiles, error
handling, and tracing redaction/export. Measure cold start, peak memory, and
latency on the actual Render plan. The existing browser tests mock every API;
live browser-to-backend/database workflows, Render runtime limits, Neon
connectivity/pooling, hosted provider behavior/quotas, and Langfuse delivery can
only be verified after a staging deployment. They remain unverified here.

For production release, confirm the staging evidence, plans/quotas, secret
rotation review, backups/rollback path, and final migration/import scope; then
perform production changes only under separate explicit approval. No staging
service, cloud migration, data import, or deployment was created in this phase.

No migration, Olist import, hosted model call, or deployment was performed. The
Git history was scanned but not rewritten. GitHub commit and push status is
reported in the release-session result.
