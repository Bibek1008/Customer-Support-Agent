# Second-stage release review — 2026-11-09

**Decision: blocked by missing runnable PostgreSQL integration infrastructure.** The local implementation is a staging candidate, but it is not cleared for controlled staging until the database tests pass. No deployment, commit, or push was performed.

## Scope and actual findings

Reviewed the complete working diff, its modified source/tests, the previously untracked workflow regressions, and `FINAL_RELEASE_READINESS.md`. The prior report's three main corrections remain present: input safety precedes routing, a committed ticket ID survives finalization, and verified existing tickets produce consistent handoff metadata. No rewrite of these working paths was needed. The separate user edit in `ARCHITECTURE.md` remains intact.

Additional defects reproduced before correction:

1. Persistent ticket backend reads/updates passed `conversation_id=None` to the repository if request context was missing, removing the conversation filter. Creation could also write an orphan ticket without request/conversation context. These backend methods now reject missing context with the existing not-found boundary before accessing storage. Staff routes retain their independent admin authentication.
2. The server-format safety parser called `.strip()` on unvalidated provider content. Non-string content caused HTTP 500. Malformed strings were reported as ordinary unsafe verdicts rather than retryable invalid results. The parser now validates the verdict grammar and returns `INVALID_VERDICT`, producing a controlled 503. It validates ASCII hazard codes without unsafe numeric conversion.
3. An unconfigured production classifier returned `checked=True` despite performing no classification, causing a refusal instead of the unavailable-service path. It now reports unchecked consistently; the existing production guard rejects it. Deliberately unconfigured local development remains explicitly unchecked and is tested separately.
4. The integration fixture had no independent target preflight before migrations. It now requires `SUPPORT_TEST_DATABASE_URL`, rejects nonloopback/ambiguous hosts and non-test database names, pins `hostaddr` to prevent inherited environment redirection, and verifies server database/user/address/port before migrations. The existing CI test job supplies this separate variable.

The independent new tests initially reproduced 11 failing cases for the authorization/parser defects, and a later production-unconfigured test reproduced the checked-state issue. These were corrected rather than removed or weakened.

## Ticket scenarios A–E

| Scenario | Verified local result | Real PostgreSQL status |
| --- | --- | --- |
| A: Explicit ticket request | One successful write, actual ID in API response, saved response/history/inbox/trace; confirmation cannot be replaced by confidence abstention. | Blocked; isolated fake repository only. |
| B: Damaged product | Informational damage question returns cited guidance directing the customer to support without a ticket. A subsequent request for someone to arrange a replacement creates a handoff without requiring the word “ticket.” | Blocked; intent/provider responses are mocked, not evidence of hosted semantic accuracy. |
| C: Missing/low-confidence knowledge | Safe abstention, no automatic ticket, distinguishable offer of staff review. | Blocked; isolated repository/tool tests only. |
| D: Repeated human request | Existing active conversation ticket reused; handoff=true and identical actual ID; no duplicate in isolated state. Forged history references from another conversation cannot cause foreign-ticket reuse. | Blocked; actual SQL isolation remains unverified. |
| E: Retry/recovery | Repeated completed request replays saved result; a committed ticket is recovered after simulated worker failure before response persistence. | Blocked; real concurrent locking/lease/idempotency tests did not run. No concurrency guarantee is inferred from fake repositories. |

Ticket tools require authenticated request context when persistence is enabled. Standalone jobs that attempt customer-ticket writes without that context now fail closed instead of creating unowned records.

## Safety and observability

- A new processed agent turn redacts PII, calls dedicated input safety once, then routes intent before tools/generation. Cached HTTP replay intentionally reuses its already persisted result; committed-ticket recovery runs after input safety without another intent/generation call.
- Controlled routes now have safety-order coverage for social, off-topic, clarification, contact, unsafe-intent and handoff-follow-up responses. Unsafe input cannot reach intent generation/tools. Grounded generated answers retain output safety checks; unavailable/malformed/unchecked output results do not release drafts.
- Authorization tests verify missing-context rejection, conversation-scoped arguments for untrusted ticket IDs, mismatched-context recovery rejection, forged history-reference isolation, and admin endpoint denial for service credentials. Real database ownership enforcement remains pending.
- Local Langfuse SDK tests inspect an in-memory exporter for generation, PII, safety/refusal, tools, ticket creation/reuse and final metadata while checking masking. Existing retrieval/confidence/output-safety coverage remains passing.
- A deliberately failing exporter test proves that a trace ID can exist even when export fails. The trace ID is a correlation identifier, not a delivery acknowledgment. Three levels must be kept distinct: local observation generation; successful exporter processing; actual Langfuse receipt/persistence. Only the first two were exercised locally with successful and failing exporters. **Hosted Langfuse delivery was not tested in this review.**

## PostgreSQL attempts and exact blocker

The original three groups are gated by `SUPPORT_TEST_DATABASE=1`; they were skipped previously because integration was not opted in. No installed PostgreSQL/Docker/Podman executable or configured WSL distribution was available.

Downloaded portable PostgreSQL 17.11 and pgvector 0.8.2 from CYBERTEC's repository into ignored `.cache/review-postgres/`. Windows application-control policy blocks `initdb.exe` and `pg_ctl.exe` even outside the sandbox (Windows error 4551). `pg_config.exe --version` could run, but this does not establish a running database. No cluster was initialized, no test role/database was created, and no security policy was changed or bypassed.

Explicitly attempted all three groups against a generated test-only loopback DSN on port 55439 with integration enabled. The guarded preflight returned `ConnectionTimeout` and stopped before migrations. Result: **0 passed, 0 assertion failures, 3 setup errors, 0 skipped**. The blocked groups are durable chat/isolation/replay/history/staff replies; leases/stale completion; and persisted rate limits/evaluations. JUnit evidence is in ignored `.cache/review-postgres-blocked.xml`.

## Safe integration commands on a suitable test host

Prerequisites: a running local PostgreSQL instance with pgvector available, a newly provisioned database named `support_review_test`, a dedicated test login that owns that database/schema, and `vector` already enabled by its test administrator. Never point this command at Neon or a shared application database. The fixture verifies identity before its additive test migrations.

```powershell
# Use only separate LOCAL test credentials. The values below are placeholders.
$env:SUPPORT_TEST_DATABASE = '1'
$env:SUPPORT_TEST_DATABASE_URL = 'host=127.0.0.1 port=5432 dbname=support_review_test user=TEST_USER password=TEST_PASSWORD'
$env:APP_ENV = 'test'
$env:TRACING_ENABLED = '0'
$env:SAFETY_MODEL_URL = ''
.venv/Scripts/python.exe -m pytest tests/test_database_integration.py -p no:cacheprovider -ra
# Once the three groups pass, run the complete suite against that same target:
.venv/Scripts/python.exe -m pytest tests -p no:cacheprovider -ra
```

The existing GitHub `database-tests` job provisions its own disposable pgvector/PostgreSQL 16 service. Only its separate test-URL variable was added; no Docker files, Render changes, CI runs, or paid resources were introduced. The portable binary attempt was version 17, not proof of PostgreSQL 16 or Neon compatibility.

## Final local validation

- Complete suite with integration opt-in disabled: **249 passed, 0 failed, 0 errors, 3 skipped** in 19.27 seconds. All three skips are the original PostgreSQL groups. Compared with 218 passed/3 skipped, added 31 passing cases: 28 independent review cases, two added early-return parameters, and one exporter-failure case. No tests were removed. JUnit: ignored `.cache/review-full-suite.xml`.
- Separate integration-enabled attempt: **0 passed, 0 failed, 3 setup errors, 0 skipped** due to the unavailable isolated server. These errors are not counted as passes or hidden by the unit run's skips.
- Ruff clean; all **87** Python files pass formatting; compilation and `git diff --check` pass.
- The existing pytest-asyncio default-fixture-loop-scope deprecation warning remains nonfatal and unrelated to these changes.

## Files changed in this review

| Files | Reason |
| --- | --- |
| `src/support_agent/tools/ticketing.py` | Fail closed when persistent ticket operations lack authenticated request context. |
| `src/support_agent/guardrails/safety.py` | Strict server-verdict validation and truthful unchecked production-unconfigured state. |
| `tests/test_release_review.py` (new) | Independent negative-path, ownership, damaged-product route, production/local safety and integration-target regressions. |
| `tests/database_safety.py` (new), `tests/test_database_integration.py` | Explicit isolated target validation/identity preflight and reliable pool cleanup. |
| `.github/workflows/checks.yml` | Supply the isolated URL to the existing database-test job. |
| `tests/test_workflow_regressions.py` | Add contact and handoff-follow-up input-safety ordering cases. |
| `tests/test_tracing.py` | Test failed-export semantics without claiming hosted delivery. |
| `docs/SECOND_STAGE_REVIEW.md`, `docs/FINAL_RELEASE_READINESS.md` | Record findings, exact results, safe commands and the release blocker. |

No production Neon connection or modification, `.env` modification, production secret exposure, paid inference, KB ingestion, migrations against production, Render change, deployment, commit or push occurred. `.env` remains ignored and untracked. Existing user changes were preserved.
