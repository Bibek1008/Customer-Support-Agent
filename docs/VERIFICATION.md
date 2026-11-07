# Demo verification — 6 November 2026

The local demonstration is running at http://127.0.0.1:8001/.
Staff can open http://127.0.0.1:8001/admin/inbox and use the private
`ADMIN_API_KEY` from `.env`. Never commit that file or put this key in chat.

## Checks completed

- Gemini quota fallback: 160 automated tests passed, 3 database opt-in tests
  skipped. Tests cover quota-only switching, separate credentials, bounded
  attempts, cooldown, actual-model cost/tracing, thinking tokens, cross-provider
  tool metadata, no replay of completed actions, and fail-closed safety.
- Live fallback regression: 8/8 completed cases passed with Groq 429 simulated
  only inside the verification process and real Gemini responses. Two intent
  cases, five safe/unsafe policy cases, and a full cited return-policy turn passed.
  One initial full-turn attempt stopped on unavailable safety; it failed closed.
  The completed cases were retained and the full turn passed on resume. This small
  regression is not production safety calibration. Database report:
  `9932607b-434f-4182-8093-2ebd5bc9513d`; full-turn trace:
  `dd73a4b962ad3bfa6b6fc33eecdbefef`.
  That trace was audited through the Langfuse CLI: intent, reasoning, relevance,
  and safety generations show the actual Gemini model and token usage; retrieval
  and fallback guardrail observations are present.

- Current answer-relevance update: 135 automated tests passed, with 3 opt-in
  database tests skipped. Extractive mode now judges relevance and evidence
  support instead of automatically scoring a quotation as 1. Missing evidence,
  irrelevant sources, and low confidence return an unknown response without
  citations or automatic ticket creation. Vague questions request clarification.
  The web UI labels unknown responses "Information unavailable". The earlier
  complete 12-ticket evaluation below predates this change and has not been rerun.
- Real relevance-judge regression: 5/5 passed. Three product-information questions
  with an unrelated returns source scored 0; two return/refund timing questions
  supported by that source scored 1. These are small regression cases, not score
  calibration or a production-quality guarantee.
- Live HTTP regression: 3/3 passed. The reported vague product question requested
  clarification; an unavailable chair material returned "I don't know" with no
  sources; a known return-window question retained the correct cited answer.
  Six messages were persisted and no tickets created. A temporary database DNS
  error interrupted the initial staff-inbox check; `--recover-http` rechecked the
  saved results and ticket count without repeating model calls. Database report:
  `b82ba86c-debb-4d48-9453-e309cc1a0375`. Frontend JavaScript syntax and the served
  page's script security hash also passed.

- Current routing implementation supersedes the phrase/grammar-based versions
  below: customer intent is classified by the configured model using structured
  JSON and recent conversation history. No customer keyword matcher remains in
  the conversation router. Replies and tool permissions remain controlled by code.
  The revised automated suite passed 131 tests, with 3 opt-in database tests
  skipped. Provider translation tests also passed separately after adding the
  intent call to the mocked Groq round trip. Mocked tests validate parsing and
  action boundaries; they do not measure semantic accuracy.
- Real semantic evaluation: 15/15 cases passed, including paraphrases, profanity
  within a real delivery problem, the reported human-plus-phone request, a
  handoff follow-up, unrelated knowledge requests, and prompt injection.
  Database report: `fb54c1f4-555c-48bd-b37c-fbab28f19ee0`. This is a small
  regression set, not evidence that all future messages will be classified correctly.
- Live HTTP human/phone regression passed: the exact reported request created
  one staff ticket, explicitly stated that no verified phone number was
  available, and its follow-up reused the same reference. Saved history contained
  both turns and staff inbox contained exactly one ticket for that conversation.
  Database report: `d7e2c5a3-dd0d-4da4-a1c9-9d9307795c26`.

- Greeting regression update: 150 automated tests passed, with 3 opt-in
  database tests skipped. Greeting routing now accepts casual word order,
  punctuation, and forms of address using a full-turn grammar rather than an
  exact phrase list. Tests include the reported `hey bro what you are doing/`
  and ensure mixed support or unsafe requests still reach their normal gates.

- Conversation-scope update: 122 automated tests passed, with the same 3
  opt-in database integration tests skipped. The new regression cases cover
  insult-only redirects, unrelated questions, profanity within genuine support
  issues, and repeated follow-ups that preserve an existing ticket reference
  without creating another ticket. The earlier PostgreSQL integration result
  below predates this update.
- Live conversation-scope check: 4/4 passed through HTTP with saved history,
  recorded guardrail traces, and zero tickets created. Database report:
  `d109ec73-8f3f-43ff-8b08-557f4ce3863f`. Existing-handoff follow-ups were
  verified separately by the automated conversation-history regression tests.

- Automated suite: 103 passed; 3 database integration tests skipped in the
  default run. Those 3 integration tests also passed in a separate real
  PostgreSQL run.
- Live HTTP smoke: frontend HTML and security policy served, HttpOnly guest
  session established, history saved, repeated request deduplicated,
  conversation isolation enforced, and staff authentication enforced.
- Live model smoke: the return-policy answer matched the cited approved
  document exactly. Trace: `542279b7d3db9d12dbc15fa46e1e3bd1`.
- Five approved knowledge documents copied without modifying their dataset
  originals. Held-out evaluation tickets were not ingested. Database schema
  version 3 and compatible active retrieval were verified.
- Actual Langfuse records were inspected for moderation, generation, retrieval,
  embeddings, and guardrails. Example trace:
  https://cloud.langfuse.com/project/cmvzd80v703c2ad0ewbm2yk33/traces/8828aa9d59e20821cbf9cb1316550c51
- Both frontend scripts passed JavaScript syntax checks.

## Evaluation evidence

The latest complete 12-ticket extractive evaluation is saved in
`eval_report.json` and PostgreSQL as
`1ca7cc88-61b3-4c22-a75d-04524fb4e758`:

| Measure | Observed result |
| --- | --- |
| Resolution | 10/12 (83.3%) |
| Accuracy on answer tickets | 8/8 (100%) |
| Hallucination among judged responses | 0/10 |
| Tone | 9/10 (90%) |
| Failed or incomplete requests | 0 |

The two resolution failures involved discount and code-writing questions.
Routing was subsequently corrected and both cases passed a separate live
regression run, saved as `8fbb1c9d-7095-4faf-87d3-d4c0a164bf5b` and
`eval/out/routing_regression.json`. The complete 12-ticket evaluation has not
been rerun since these two corrections. These small demonstration results do
not establish production quality or a calibrated confidence threshold.

## Remaining deployment checks

The deployment target is Render's native Python runtime. Current deployment
checks and outstanding staging requirements are tracked in
`docs/FINAL_RELEASE_READINESS.md`; a local verification pass is not proof of
Render runtime capacity, live provider behavior, or a production deployment.

The current safety-provider quota supports a paced demonstration. Public
concurrent traffic needs adequate provider capacity. Guest sessions and demo
orders must be replaced with verified customer identity and authorized order
access for a real store. No public deployment has been performed.
