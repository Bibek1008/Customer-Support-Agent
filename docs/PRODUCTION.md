# Demo Office Store deployment and operations

> Current deployment settings are in [FREE_TIER_DEPLOYMENT.md](FREE_TIER_DEPLOYMENT.md)
> and `render.yaml`. Olist is a separate optional historical-data demo. Provider
> account quotas remain unverified; a read-only storage preflight measured the
> database before Olist import. Hosted inference and database writes require
> verified quotas and explicit approval.

The conversation guardrail uses the configured classifier model with a strict
JSON schema to interpret the latest message and eight recent messages. It has
no greeting, insult, or scope keyword lists. PII is redacted before classification.
It separates real support issues, social messages, unrelated requests, unclear
intent, human/contact requests, existing-handoff follow-ups, identity recovery,
pricing, and unsafe requests. Real support issues with profanity continue through
the safety and support gates. Classification failure returns a retryable provider
error; it never defaults to ticket creation or phrase matching.

Routing categories map to controlled responses/actions. These response templates
are intentional; intent detection itself is model-based. Human requests create a
staff ticket, or refer to an existing saved reference in this conversation. No
verified support phone number is configured for this demo, so the assistant says
so rather than inventing one. It does not promise a live transfer or reply time.
`classify-intent` records model input/output, usage and cost; `conversation_scope`
records the validated category in traces and database audit events. Every turn
now uses classifier quota, including greetings. Models can still misclassify;
run `python ops/verify_intent.py` to measure the included live routing cases.

`ANSWER_MODE=extractive` is the default: the model routes requests and retrieves
context, then factual answers quote an approved document or authorized order
record. Identity-recovery requests require a saved staff ticket. Greetings and
clarifications use controlled replies after semantic classification. Generated prose remains
an explicit optional mode and is not the mode validated for this demonstration.
Extractive responses now undergo the same model-based question-relevance and
evidence-support check as generated responses. An exact quotation is no longer
automatically scored 1. Unsupported or irrelevant answers return "I don't know"
with no citations or automatic staff ticket. Vague requests ask for clarification.
The score and threshold are not calibrated probabilities of correctness. Explicit
human requests and required identity/pricing reviews still use the staff inbox.
Run `python ops/verify_answer_relevance.py` to check relevance and the HTTP flow.
Pricing and promotional requests route to staff while `PRICING_REQUIRES_REVIEW=1`.
Keep that setting until approved pricing/promotion policies are connected. Code
generation is outside this retail support service's scope. Source quotations alone
do not establish relevance; routing is evaluated separately from grounding.

The current deployment configuration uses Groq for generation and safety checks;
Gemini generation fallback is disabled. Provider quota exhaustion returns a
retryable error. Do not assume any provider is unlimited or available on a free
plan; check account quotas before live inference. Langfuse tracing is sampled and
uses an application-side monthly cap. The development embedding configuration
may use Gemini, while `render.yaml` selects FastEmbed BGE Small. Those vector
spaces are incompatible despite both using 384 dimensions; re-embed the approved
documents for both profiles before changing the serving configuration.

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
completed reports. The GitHub Actions workflow includes unit and PostgreSQL integration jobs. Its
PostgreSQL service is ephemeral CI infrastructure, isolated from production.

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

## Render native Python deployment

This project targets the Render native Python Web Service defined in
`render.yaml`. Create the service from that Blueprint and configure its unsynced
secrets in Render: `DATABASE_URL`, `GROQ_API_KEY`, `ADMIN_API_KEY`,
`SERVICE_API_KEY`, and the Langfuse keys when tracing is enabled. Keep `.env`
local and out of Git. The Blueprint sets one Uvicorn worker, bounded concurrency,
FastEmbed BGE Small embeddings, Groq generation/safety, and `/healthz` as the
health check. It does not run migrations or import data on startup.

Use Neon PostgreSQL with pgvector and verify the database plan, storage, and
connection limits before deployment. Run reviewed migrations and approved KB
ingestion against a separate staging database first. Do not point tests or
staging at production. Verify Render's current plan limits, cold start, memory,
provider quotas, database readiness, staff/customer flows, and Langfuse export
on a staging service before considering public use. Free services can sleep and
have cold starts; do not treat them as production-critical support. See
[`FREE_TIER_DEPLOYMENT.md`](FREE_TIER_DEPLOYMENT.md) and
[`FINAL_RELEASE_READINESS.md`](FINAL_RELEASE_READINESS.md) for current limits.

Production API docs are disabled. `/healthz` is the liveness check and `/readyz`
checks PostgreSQL readiness. Safety service failures block answering and return
a retryable error; they never silently bypass classification. Deploy rollback is
performed by restoring the previous Render revision/configuration and following
the database backup plan, not by deleting customer records.

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

Keep previous Render revisions and database backups for rollback. Migrations here are
additive; do not roll back by deleting customer records. Check provider quotas,
safety availability, database capacity, logs, and the evaluation report before
releasing a new model or document set. Staff key rotation invalidates staff tabs;
guest session access remains independent. Persist operational logs in your host's
log system; secrets and request bodies must not be added to access logs.

Render runtime behavior and restore drills must be verified in staging. A local
test pass alone is not a claim that these operational checks have already happened.
