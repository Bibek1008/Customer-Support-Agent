# Production-readiness audit

Date: 2026-11-07. Scope: repository review and local verification only. No
cloud database, hosted model, paid service, import, migration, deployment, or
Git operation was performed for this audit.

## Readiness decision

**NOT READY for public deployment.** The application has meaningful local
security and reliability controls, but key deployment facts are unverified and
there are unresolved operational gaps listed below. Local test success is not
evidence of Neon, Groq, Langfuse, or Render production behavior.

## Area-by-area findings

| Area | Result | Evidence and remaining work |
|---|---|---|
| FastAPI lifecycle and startup | PASS | Verified import path is `support_agent.server:app`; production startup checks config/schema/KB and does not run migrations, imports, or bulk embedding. Uvicorn is configured for one worker. |
| Customer authentication and sessions | PASS | Browser sessions use 256-bit random tokens, SHA-256 hashes at rest, seven-day expiry, and HttpOnly/SameSite Strict cookies (Secure in production). `DELETE /api/session` now revokes the token and clears the cookie; the UI clears the saved conversation ID. No password-based accounts exist. |
| Staff authentication | NEEDS IMPROVEMENT | Staff APIs require a separate bearer key with constant-time comparison and production validation requires distinct strong admin/service keys. Failed attempts now receive an in-process throttle of 10/minute per hashed source IP, reset after a successful key. It is bounded and suited to the configured single worker; use edge throttling before scaling to multiple instances. No staff key is embedded in frontend source. |
| Authorization and tenant isolation | NEEDS IMPROVEMENT | Conversation and ticket reads are owner-scoped; Olist SQL uses the conversation's server-side account binding; model tools cannot issue SQL. Cross-account queries and Neon-backed isolation were not run because DB integration is opt-in and cloud access is prohibited. |
| Request validation and web security | PASS | Pydantic bounds message/conversation identifiers; middleware caps request bodies at 16 KiB including chunked requests. Same-origin checks, `Sec-Fetch-Site`, production Trusted Host, CSP, and security headers are configured. No permissive CORS is configured. |
| SQL and database access | NEEDS IMPROVEMENT | Queries are parameterized, transactions use pooled connections, and query/lock/connect timeouts are bounded. Production migrations are explicit. The approved storage query measured database and relation/index sizes; live grants and transactional isolation behavior were not tested. |
| Olist importer and data separation | PASS | Importer has explicit selected columns, excludes review comment content and geolocation, keeps untranslated products with fallback labels, and uses a separate `olist_demo` schema. Reviews remain optional feedback records, not conversation or policy data. No import was run. |
| RAG and embeddings | NEEDS IMPROVEMENT | Retrieval is profile/model aware, citations are tied to retrieved evidence, unsupported answers can hand off, and Olist transactional questions use SQL. Local settings use Gemini `gemini-embedding-001` (384 dimensions); Render uses FastEmbed `BAAI/bge-small-en-v1.5` (384). The database query measured table sizes only, so stored vector metadata was not read. Search filters by profile/provider/model, avoiding cross-model comparisons but returning no matching evidence until both profiles are ingested with the deployment model. Live retrieval quality was not verified. |
| LLM and safety reliability | NEEDS IMPROVEMENT | Provider timeouts, bounded transient retries, safe error messages, output limits, fail-closed production safety configuration, and a shared bounded concurrency slot for generation and Groq safety calls are present. The shared semaphore change is locally covered by code review but account quota and hosted outage behavior are not verified. Gemini fallback remains disabled. |
| PII and prompt injection | NEEDS IMPROVEMENT | Presidio/regex redaction is applied before persistence, model requests, and traces; production startup requires Presidio. Tool allowlists and server-side authorization do not rely on prompt instructions. Realistic attack and redaction coverage is unit-level; no external model test was run. |
| Observability and logs | NEEDS IMPROVEMENT | Langfuse is enabled at 100% sampling up to the application trace cap; secret/PII masking is implemented and API authentication was verified locally. Account usage and trace export from a real customer request still need monitoring; no independent metrics/alerting or database/LLM/tool counters are configured. |
| Frontend and staff UI | NEEDS IMPROVEMENT | Customer and staff pages use text nodes for model/customer content, same-origin APIs, loading/error states, and a staff key that stays in memory. Three mobile browser tests cover startup, cited answer rendering, service failure retry, and session ending. A full accessibility audit and live API/browser test were not run. |
| Deployment configuration | NEEDS IMPROVEMENT | Render blueprint uses one worker, bounded concurrency and pool, external Neon persistence, local FastEmbed, and liveness endpoint. No deployment was created. Free-plan availability, service memory under full workload, cold start, DNS/network egress, and environment variables have not been verified. |
| Evaluation | NEEDS IMPROVEMENT | Held-out evaluation data and harness remain separate from the approved policy KB. Local suite includes safety, injection, citation, fallback, and Olist behavior tests. No current held-out live-model score was produced because hosted inference was forbidden. |
| Storage capacity | PASS (preflight only) | Approved read-only measurement returned 9,650,176 bytes current DB usage. With 170 MB estimated Olist growth, projected usage is 179,650,176 bytes, below the 700 MB target. Import is still unapproved and has not been run. |

The offline FastEmbed and application probe measured process peak RSS at
**319,889,408 bytes (~305 MiB)** and model-load increment at **165,253,120 bytes
(~158 MiB)**. It includes app import, Presidio, FastAPI TestClient lifespan,
and four concurrent mocked `/chat` requests. It excludes hosted model inference,
a database pool, a separate Uvicorn process, and Render overhead. It improves on
the model-only baseline but does not verify deployed 512 MiB fit.

## Changes in this phase

- Groq generation and Groq safety classification now share the same bounded
  inference semaphore, preventing classifier traffic from exceeding the
  configured provider concurrency budget.
- Provider capacity exhaustion maps to a controlled 503 response.
- HTTP request logs include a generated request ID, route template, status,
  error class, and duration; bodies, query strings, and customer identifiers
  are not logged.
- Added customer session revocation and a UI control that clears the browser's
  saved conversation ID when ending the session.
- Added bounded staff authentication failure throttling: after ten failed
  attempts from the same source IP in a minute, responses are limited with a
  60-second retry hint; successful authentication clears that IP's bucket.
- Added Playwright mobile-browser tests for successful chat with citation,
  service failure with retry text retained, and logout/session clearing. All
  backend API calls are mocked so these tests cannot access Neon or model APIs.
- Fixed repository-wide Ruff findings in the evaluation report, optional
  tau-bench adapter, and injection test imports. These changes are formatting
  or narrower optional-dependency exception handling.

## Security and privacy notes

- Staff keys are bearer secrets, not user accounts; there is no password store
  to audit or password hashing mechanism to claim.
- A valid Olist demo alias is a curated public-data identity, not a credential.
  Order lookup remains bound to the account alias saved on an owned conversation.
- The service does not implement actual refunds, cancellations, or live
  shipping changes. Historical Olist data is 2016–2018 demonstration data.
- Confirm and rotate any credentials ever exposed in prior chat, terminal
  output, or Git history before deployment. This audit did not print or inspect
  secret values.

## Verification

Final local run: **171 passed, 3 skipped**. The skips are PostgreSQL integration
tests without a configured local integration DB. The three Chrome/Playwright
browser tests passed with the production CSP header applied and API requests
mocked. Full Ruff lint, targeted format checks, Python compilation for `src`,
`eval`, `ops`, and `tests`, and `git diff --check` passed. `ruff format --check .`
crashes in the installed Ruff build when it encounters a non-Python repository
file; targeted Python format checks are used instead. Model/API calls were
mocked or omitted; no hosted inference or quota use occurred.

Re-run browser coverage after installing the optional dependency and ensuring
Chrome/Brave is installed (or `CHROME_PATH` is set):

```powershell
uv pip install --python .venv/Scripts/python.exe -e ".[e2e]"
.venv/Scripts/python.exe -m pytest tests/test_chat_browser_e2e.py -p no:cacheprovider
```

## Blockers before a public demo

1. Confirm Neon, Groq, Langfuse, and Render account plans/quotas and set provider
   budgets. Do not infer free quota from application-side limits.
2. Re-ingest both knowledge profiles with the same FastEmbed model configured
   for deployment, then validate retrieval and citations against the actual DB.
3. Run locally configured PostgreSQL authorization/integration tests; the
   three DB-gated cases were skipped. Add a complete accessibility audit and
   exercise the browser against a deployment when deployment is approved.
4. Measure memory inside the target runtime. The local 305 MiB measurement
   included four concurrent mocked requests but excluded a DB pool, separate
   Uvicorn process, hosted inference and Render overhead, so it cannot establish
   Free-plan fit.

After those checks, reassess whether this remains a portfolio demo or is safe
for the intended public audience. It is not currently suitable for
commercially critical customer support.
