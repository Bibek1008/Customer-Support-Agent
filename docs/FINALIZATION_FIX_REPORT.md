# Finalization, redaction, and policy fidelity review

Implemented locally on November 10, 2026. No production data, Neon, `.env`, deployment
configuration, retrieval thresholds, safety policy definitions, or architecture
documentation were changed. Nothing was deployed, committed, or pushed. Existing
database identity safeguards and other user changes were preserved.

## Root causes and corrections

| Finding | Cause | Correction |
| --- | --- | --- |
| Generated procedure differs from returned answer | Extractive mode deliberately selects the highest-scoring safe retrieved excerpt before scoring. | Behavior retained. Traces distinguish the redacted original draft, selected answer, mode, and replacement reason, including deterministic retrieval fallback. |
| Public citation URL becomes a placeholder | A generic free-text PII detector was applied to the URL field without source provenance. | Server-side retrieval marks approved KB citations with a private, non-serialized attribute. Only these citations can preserve a validated public HTTP(S) document URL. Invalid or untrusted citation URLs are omitted. |
| Ordinary recurrence wording becomes `<DATE_TIME>` | Presidio treated “the same day each month” as sensitive date information. | A narrow exception applies to this phrase in approved KB content and the resulting supported answer. Absolute dates and customer text receive normal redaction. |
| Evaluated text could differ from delivered text | Answer redaction followed confidence and safety checks; durable API and repository sanitization could transform content again. | Answer and citations are sanitized before a complete canonical response is constructed. Confidence and policy consistency evaluate that answer. Assistant safety checks the exact answer and the displayed citation content. Content snapshots detect later mutations. |
| Generated draft broadens refund policy | Generic support scoring and a completed-action regex did not require preservation of contractual conditions. | The structured evaluator now requires a boolean policy-consistency verdict in addition to confidence. False, absent, or malformed provider verdicts fail closed. Inconsistent answers abstain without creating a ticket. |
| Unknown credentials could appear in strings or structured telemetry | Known-secret masking and PII patterns did not cover every credential label or private URI shape. | Deterministic protection covers configured secrets, bearer/basic credentials, common token formats, labeled and quoted credentials, credential-bearing URIs, private/query URLs, and sensitive structured telemetry fields. |

## Canonical finalization contract

1. Generate a candidate or select the extractive answer using the existing source-selection logic.
2. Sanitize the answer and citations, using server-side provenance for the narrow policy exception and citation URL preservation.
3. Construct the complete `ChatResponse` representation, including its exact answer and citations, before evaluation.
4. Evaluate that answer against its sanitized evidence. Require policy consistency as well as the existing confidence threshold.
5. Check the exact final answer with assistant safety. Separately check all displayed citation identifiers, titles, chunks, and URLs.
6. Seal the validated content. Fill in evaluation results, tracing ID, and final cost accounting without changing answer, citations, decision type, handoff state, or ticket ID.
7. Serialize once to canonical API JSON. The repository verifies and copies this payload; it does not run another redaction pass over canonical responses. The API verifies it again after persistence and returns the same JSON.

Controlled replies, abstentions, and handoff confirmations also pass the final
preparation and assistant-safety gate. They retain their existing route-specific
confidence values; rejected factual drafts do not lend a high confidence score to
an abstention. A replacement response must pass safety before release. Missing
finalization, detected mutations, and failed required release validation fail
closed; finalization errors produce HTTP 503.

The repository retains its existing sanitization behavior for legacy direct callers
that supply plain dictionaries. The live chat path supplies a checked `FinalPayload`.
Observability records are masked independently and cannot mutate the customer payload.

## Public citation trust boundary

The approval marker is assigned only by the KB retrieval implementation. It cannot
be supplied through citation JSON, a source identifier, or a model-generated field.
Order/ticket citations and arbitrary citation objects receive no URL-preservation
privilege. Metadata and policy text still receive PII and secret redaction.

URL checks reject credentials, queries, fragments, ambiguous escaping, IP literals,
local/private host labels, nonstandard ports, traversal paths, and obvious
authentication/token paths. Approved document slugs are preserved only after
deterministic PII and credential checks. User-provided free-text URLs remain subject
to redaction. The billing URL `https://help.example.com/billing` survives as usable
HTTP(S) citation metadata.

This validates source provenance and conservative URL syntax. It does not perform
DNS resolution, check redirects, certify document access permissions, or establish
that a URL is reachable. The approved KB ingestion/storage boundary remains trusted.

## Policy consistency

The existing structured grounding evaluation now separately judges refund eligibility,
verification requirements, processing time and its triggering event, payment method,
cancellation effective dates, continued access, renewal, and future billing. It allows
supported paraphrases and does not require discussion of policies the answer makes no
claim about. An inconsistent verdict forces confidence to zero even if the provider
also emits a score of 1.0. There is no additional provider call for this verdict.

Extractive mode remains the default; no environment or deployment settings changed.
The existing unsupported-action check and all safety checks remain in place.

## Files changed for this work

| Files | Purpose |
| --- | --- |
| `src/support_agent/agent/finalization.py` (new) | Provenance-aware citation preparation, canonical response construction, content checks, and checked API payload serialization. |
| `src/support_agent/agent/loop.py` | Common release gate, evaluation ordering, exact answer and citation safety, and finalization trace records. |
| `src/support_agent/agent/confidence.py` | Focused policy instructions, strict structured verdict parsing, and fail-closed enforcement. |
| `src/support_agent/guardrails/redaction.py` (new) | Public document URL validation and deterministic credential/private-URI protection. |
| `src/support_agent/guardrails/pii.py` | Narrow approved-policy recurrence handling; shared secret and fallback URL protection. |
| `src/support_agent/tools/knowledge_base.py` | Server-only provenance marking at retrieval. |
| `src/support_agent/schemas.py` | Shared `ChatResponse` schema and private provenance/finalization state. |
| `src/support_agent/http_api.py`, `src/support_agent/server.py` | Canonical response serialization, removal of late answer redaction, and validation failure handling. |
| `src/support_agent/repository.py` | Persist canonical API JSON without changing evaluated content. |
| `src/support_agent/observability/tracing.py` | Independent secret/private-URI masking, including sensitive structured fields and exported attributes. |
| `tests/test_finalization.py` (new) | 46 regression cases covering provenance, PII, credentials, policy verdicts, mutation rejection, and exact HTTP/persistence/evaluation equality in both modes. |
| `tests/test_agent_loop.py`, `tests/test_guardrails_pii.py`, `tests/test_injection.py` | Existing confidence fakes explicitly attest policy consistency. |
| `tests/test_groq_client.py`, `tests/test_tracing.py` | Structured provider fixtures include the new verdict. |
| `tests/test_workflow_regressions.py` | Assert safety checks on final controlled replies, citation content, and fallback confirmations. |
| `tests/test_database_integration.py` | Stub generation below the real finalization boundary; preserve existing database identity safeguards. |
| `docs/FINALIZATION_FIX_REPORT.md` (new) | This implementation and validation report. |

## Validation and limitations

- Full pytest suite: **300 passed, 0 failed, 3 skipped**. The three real PostgreSQL integration tests were explicitly disabled; no database was contacted by them.
- Ruff check for `src`, `tests`, `eval`, and `ops`: passed.
- Ruff formatting check for those directories: **90 files passed**.
- Python compilation using in-memory `compile` over tracked Python files plus new modules/tests: **85 passed, 0 failed**.
- `git diff --check`: passed.

The repository-root formatter encountered an inaccessible temporary directory and a
Ruff panic; the successful formatting check explicitly covered the source, test,
evaluation, and operations directories instead. Pytest still reports the existing
async-fixture-scope deprecation warning.

Providers and persistence are mocked/isolated in the new regressions. The actual
repository serializer and FastAPI response serialization are exercised against an
isolated SQL sink. The observed Presidio false positive is reproduced with a mocked
analyzer and anonymizer; local Presidio initialization otherwise falls back to regex.
These tests establish ordering, serialization equality, and fail-closed behavior,
not production detector accuracy or semantic judge accuracy. Live provider
calibration, real Presidio verification, and opt-in isolated PostgreSQL validation
remain separate work. No production correctness claim or deployment is made.

Separate citation safety checks and newly checked controlled replies can increase
safety-provider latency and quota use. Production quota behavior was not exercised.
