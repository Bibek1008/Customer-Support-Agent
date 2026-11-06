# Demo Office Store deployment and operations

The local conversation guardrail redirects recognized insult-only and clearly
unrelated turns without opening tickets or spending model quota. Profanity in
a genuine support request continues through the safety and support gates.
Recognized follow-ups to the latest saved handoff explain the existing reference
without creating another ticket or promising a staff response time. These are
conservative routing rules, not a universal semantic classifier; unknown wording
continues through the existing safety and support flow. The `conversation_scope`
guardrail records the routing category in request traces and database audit events.

`ANSWER_MODE=extractive` is the default: the model routes requests and retrieves
context, then factual answers quote an approved document or authorized order
record. Identity-recovery requests require a saved staff ticket. Static greetings,
thanks, and clarification templates do not call a model. Generated prose remains
an explicit optional mode and is not the mode validated for this demonstration.
An extractive grounding score of 1 means a source was quoted exactly; it is not
a calibrated probability of relevance or resolution.
Pricing and promotional requests route to staff while `PRICING_REQUIRES_REVIEW=1`.
Keep that setting until approved pricing/promotion policies are connected. Code
generation is outside this retail support service's scope. Source quotations alone
do not establish relevance; routing is evaluated separately from grounding.

For the current free safety quota, run evaluations with `--delay-seconds 40`.
Safety quota exhaustion returns a retryable error, not an unsafe-content label.
For a no-new-calls threshold view, use `python -m eval.threshold --report
eval_report.json --hallucination-target 0.02`. It evaluates only cutoffs at or
above the report's active threshold and is labelled retrospective, not production
calibration. Earlier runs remain in PostgreSQL for comparison.

Re-ingesting an updated source archives its previous chunks using the `active`
flag; prior versions remain in the database. Retrieval filters active chunks by
embedding provider and model, so incompatible models cannot silently mix. Remove
a source from retrieval through an explicit reviewed archive operation; deleting
a Markdown file alone does not withdraw its existing database chunks.

In the staff inbox, “Recent activity & guardrails” shows saved request results,
tool/model traces, and guardrail events; “View evaluations” shows checkpointed and
completed reports. The prepared GitHub Actions workflow includes unit tests,
PostgreSQL integration tests, and a Docker image build. It must execute before
its Docker build can be considered verified.

This is a fictional retail-support demonstration. Its five approved policy files
are exact copies of the Markdown files in `eval/datasets/kb_docs/`. Held-out
tickets remain separate and must never be ingested. Sample orders are explicitly
demonstration records, seeded into PostgreSQL without overwriting existing rows.
Changing `BUSINESS_MODE=live` disables those order records. Real customer order
lookups require an authenticated account integration and are deliberately disabled
in live mode until one is implemented.

## What persists

PostgreSQL stores sessions (token hashes only), conversations, redacted messages,
request IDs and responses, per-turn traces including model/tool activity and
guardrail decisions, tickets, staff replies, staff actions, rate counters, demo
orders, and evaluation reports. Knowledge documents and vectors remain in
`kb_chunks`. Messages and result records are committed before the API confirms
success. Storage errors return 503; there is no silent memory fallback when
persistence is enabled. Only isolated unit tests use in-memory implementations.

The server serializes turns per conversation using expiring database leases.
Retries with the same request UUID and message return the saved result. Reusing
that UUID with different content returns 409. A crashed worker's lease expires
after five minutes; request deadlines normally expire after three minutes.
The frontend retains only the conversation ID in local storage; its session token
is an HttpOnly cookie, while staff credentials remain in the staff tab's memory.
Browser sessions expire after `SESSION_DAYS`; clearing cookies removes the
visitor's access to those conversations, while the records remain available to
authorized staff. This is guest support, not verified customer account login.

API keys, raw session tokens, passwords, and unredacted sensitive identifiers are
not application records. Keys belong in environment secrets, not database rows.
Redaction reduces exposure; it is not a guarantee that all possible personal data
will be detected. Review the redaction policy before using real customer data.

## Local startup

Keep credentials in the git-ignored `.env`. The current local configuration uses
Groq reasoning, Gemini embeddings, hosted Groq Safeguard moderation, and Langfuse.
Run from the repository root:

```powershell
.venv/Scripts/python.exe -m support_agent.db
.venv/Scripts/python.exe -m support_agent.kb.ingest --docs knowledge_base/approved
.venv/Scripts/python.exe -m support_agent.doctor --providers
.venv/Scripts/python.exe -m uvicorn support_agent.server:app --host 127.0.0.1 --port 8001 --no-access-log
```

Open `http://127.0.0.1:8001/`. The staff inbox is `/admin/inbox`; unlock it with
`ADMIN_API_KEY` from your private `.env`. Staff can inspect saved conversations,
send replies visible in the customer's chat, update ticket status, and inspect
recorded evaluations. The initial guest conversation reloads after a refresh.
“New chat” starts another conversation; it does not delete the previous one.

## Docker and HTTPS

Use a Linux host with Docker Engine and Compose v2, a DNS hostname pointing at it,
and inbound ports 80/443. Use managed PostgreSQL/Neon with TLS, backups, and a
database user restricted to this application. Preserve `.env` outside Git and
restrict it to the deployment operator. Do not reuse staff and service keys.
The image excludes `.env`, local caches, Git metadata, and benchmark payloads.

Set `DOMAIN`, `ACME_EMAIL`, the provider/database credentials, and both random
access keys in `.env`. `APP_ENV=production` is set by the deployment file.
Keep `BUSINESS_MODE=demo` for this fictional business and `ALLOW_FIXTURE_ORDERS=1`
for its public demonstration orders. The displayed demo notice must remain.

```sh
docker compose --env-file .env -f compose.production.yaml config --quiet
docker compose --env-file .env -f compose.production.yaml build
docker compose --env-file .env -f compose.production.yaml up -d
docker compose --env-file .env -f compose.production.yaml ps
```

The migration service applies additive schema updates before the gateway starts.
Caddy terminates TLS and redirects HTTP to HTTPS. The gateway is not published
directly, runs as a non-root user with a read-only filesystem, dropped capabilities,
bounded concurrency, and a health check. PostgreSQL request limits work across
workers. Tune upstream IP rate limits for a larger public deployment; the app
does not trust arbitrary client-supplied forwarding headers as identity.
The Python dependency lock records tested versions and hashes. The large spaCy
model is pinned to release 3.8.0. Rebuild and test intentionally when updating it.

Startup refuses production mode without persistent storage, separate staff and
service keys, HTTPS configuration, a working Presidio installation, an ingested
database knowledge base, and an available safety classifier. Production API docs
are disabled. The readiness endpoint checks the database; the liveness endpoint
is `/healthz`. The safety model is currently a provider preview model: monitor
deprecations and availability. Safety service failures block answering and return
a retryable error; they never silently bypass classification.

## Verification and measured quality

```powershell
.venv/Scripts/python.exe -m pytest tests -p no:cacheprovider
.venv/Scripts/python.exe -m eval.validate_datasets
.venv/Scripts/python.exe -m eval.run --suite heldout
.venv/Scripts/python.exe -m eval.threshold --hallucination-target 0.02 --k 1
```

The model-based commands consume provider quota. They use the selected provider,
including Groq; no Anthropic key is needed in Groq mode. Results go to
`eval_report.json`, `eval_report.md`, `threshold_curve.json`, and PostgreSQL's
`support_eval_runs`. The staff inbox can retrieve the stored reports. Failures or
unscored answers are recorded explicitly instead of being counted as clean
hallucination results. These 12 fictional tickets are a smoke evaluation, not
evidence of a production hallucination rate below 2%. LLM judges use the same
provider/model as the agent and require human spot checks. Threshold selection
maximizes observed coverage under the target; it does not update `.env` by itself.

Real PostgreSQL integration tests are opt-in. Set `DATABASE_URL` to a dedicated
test database, migrate it, then run:

```powershell
$env:SUPPORT_TEST_DATABASE='1'
.venv/Scripts/python.exe -m pytest tests/test_database_integration.py -p no:cacheprovider
```

The tests create synthetic records and do not truncate existing tables. They test
visitor isolation, history persistence across pool restarts, idempotent retries,
concurrent/stale leases, staff replies, redaction, rate limits and evaluation
persistence. Preserve schema and embedding-model compatibility between releases.
Changing embedding models requires re-embedding approved documents; equal vector
dimensions do not mean the models are compatible.

## Backup, restore and release checks

Enable managed database backups/PITR before deployment and verify a restore into a
separate staging database. An encrypted PostgreSQL custom-format dump can also be
taken with `pg_dump`; pass its connection via a protected service file or secret
environment, never a credential-bearing command argument. Restore into an empty
staging database using `pg_restore`, then run migrations, doctor, and the integration
tests there. Confirm that an existing chat and ticket can be retrieved after an
application restart. No automatic destructive retention job is enabled; establish
retention and deletion requirements before storing real customer data.

Keep previous image tags and database backups for rollback. Migrations here are
additive; do not roll back by deleting customer records. Check provider quotas,
safety availability, database capacity, logs, and the evaluation report before
releasing a new model or document set. Staff key rotation invalidates staff tabs;
guest session access remains independent. Persist operational logs in your host's
log system; secrets and request bodies must not be added to access logs.

Docker image execution, TLS issuance and restore drills must be verified on the
deployment host. A local test pass alone is not a claim that these operational
checks have already happened.
