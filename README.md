# Production customer-support agent

The current application is a database-backed **Demo Office Store** demonstration
with fictional policies and sample orders. It includes saved conversations,
an authenticated staff inbox, hosted safety checks, guardrail activity, and stored
evaluation reports. Start with [deployment and operations](docs/PRODUCTION.md).
The configured demo uses Groq GPT-OSS 20B, Gemini embeddings, PostgreSQL/pgvector,
Groq GPT-OSS Safeguard, and Langfuse. Factual answers quote source excerpts by
default, after model-based question-relevance and evidence checks. Vague requests
ask for clarification; missing knowledge produces an honest "I don't know"
without automatically opening a ticket. Staff review remains available on request.
The older setup sections below describe the original tutorial and optional
development alternatives; current behavior is documented in `docs/PRODUCTION.md`.

```powershell
.venv/Scripts/python.exe -m support_agent.db
.venv/Scripts/python.exe -m support_agent.kb.ingest --docs knowledge_base/approved
.venv/Scripts/python.exe -m uvicorn support_agent.server:app --host 127.0.0.1 --port 8001 --no-access-log
```

Customer chat: http://127.0.0.1:8001/ · Staff inbox:
http://127.0.0.1:8001/admin/inbox (use the private `ADMIN_API_KEY` from `.env`).
Keep `PERSISTENCE_ENABLED=1`. Credentials are environment secrets; chat history,
tickets, replies, traces, demo orders, and eval results are database records.
Docker preparation is in `compose.production.yaml`; building and TLS verification
require Docker and a deployment hostname. The free hosted safety quota limits
this demonstration's traffic; it is not a public-traffic capacity guarantee.

## Free local development with Groq and Neon

Use a Groq account on its Free plan for chat and confidence scoring, FastEmbed
for CPU embeddings, and a Neon Free project for PostgreSQL. Groq and Neon usage
limits still apply; this is not unlimited hosted inference. No Anthropic or
OpenAI API key is needed for this configuration. Gemini quota fallback is opt-in;
enable `GEMINI_FALLBACK_ENABLED=1` with `GEMINI_API_KEY` to use it. Gemini requests
consume that project's quota and may incur charges according to its billing tier.

Install the additional local embedding dependency:

```powershell
uv pip install --python .venv/Scripts/python.exe -e ".[dev,pii,free]"
```

Set these values in your git-ignored `.env`. Create a replacement Groq key if
you have shared your previous key publicly or in chat; never commit credentials.

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=your-replacement-key
GROQ_MODEL=openai/gpt-oss-20b
EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIM=384
DATABASE_URL=postgresql://USER:PASSWORD@HOST/neondb?sslmode=require
SAFETY_MODEL_URL=
TRACING_ENABLED=0
```

Run `CREATE EXTENSION IF NOT EXISTS vector;` in Neon's SQL Editor first.
Use a fresh database if you previously created `kb_chunks` with a different
embedding dimension: changing this setting does not migrate existing vectors.
The first embedding call downloads the model to `.cache/fastembed`; subsequent
embedding calls run locally without an API key or a GPU.

Add your support documents under `knowledge_base/approved`, then run:

```powershell
.venv/Scripts/python.exe -m support_agent.kb.ingest
.venv/Scripts/python.exe -m uvicorn support_agent.server:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs to send a `POST /chat` request. For a local test,
you can explicitly ingest `--docs eval/datasets/kb_docs` instead of production
documents. Check `get_store()._use_db` before relying on persistence: the existing
store falls back to memory if its database setup fails, and CLI ingestion into
memory does not survive the command exiting. Local ticketing is also in memory.

This development setup skips the optional Llama Guard safety classifier and span
export; PII redaction and injection filtering still run. Groq token usage is
recorded with its published list-price equivalent in `cost_usd`; it is not a bill
for your Free plan. Keep your Groq account on the Free plan for free-tier usage.
See [Groq limits](https://console.groq.com/docs/rate-limits) and
[model details](https://console.groq.com/docs/model/openai/gpt-oss-20b).

## Optional Gemini embeddings

Gemini is also available for hosted embeddings. Set `EMBEDDING_PROVIDER=gemini`,
`EMBEDDING_MODEL=gemini-embedding-001`, `EMBEDDING_DIM=384`, and `GEMINI_API_KEY`
in `.env`. This works with the existing 384-dimension local-development table.
Re-embed every document before serving requests with a new embedding model;
matching dimensions alone do not make embeddings compatible. Gemini uses
`RETRIEVAL_DOCUMENT` for ingestion and `RETRIEVAL_QUERY` for searches, with
L2 normalization. Free-tier quotas apply; see
[Google's pricing](https://ai.google.dev/gemini-api/docs/pricing).

## Langfuse tracing

The application uses Langfuse Python SDK **5.1.0**. Put your project keys and
regional URL in the git-ignored `.env`, then restart the API:

```dotenv
TRACING_ENABLED=1
LANGFUSE_PUBLIC_KEY=your-project-public-key
LANGFUSE_SECRET_KEY=your-project-secret-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
```

Use your project's actual regional URL (for example `https://us.cloud.langfuse.com`
for a US project). With these settings, traces go directly to Langfuse without
Docker or an OpenTelemetry collector. The generic OTLP endpoint is only used
when Langfuse is not configured. `TRACING_ENABLED=0` disables all exports.

Each support turn creates a `handle-support-request` agent observation, with
`generate-response` and `score-confidence` generations, `retrieve-context`
retrieval, Gemini `embed-text` embeddings, tool calls, and guardrail decisions.
Model prompts, tool definitions, responses, reasoning, and provider token usage
are captured explicitly. Gemini token usage is recorded when its response
provides it; vector values and API keys are never logged. Repeated PII checks
are summarized on the root to keep traces readable. Model costs are published
list-price equivalents, not invoices for your free-tier accounts.

Inputs and outputs use the app's PII redaction plus an export-stage masking
hook for common identifiers and configured secrets. Exception traces record
the exception type, not raw exception messages or stack events. Conversation
and customer IDs are SHA-256 hashes, so related turns group into Sessions
without sending those identifiers verbatim. Extend the masking policy for any
additional confidential fields used in your own support documents.

`POST /chat` returns a `langfuse_trace_id` for correlation. The SDK batches
exports in the background and flushes on server shutdown. Scripts that call
`run_turn` should call `flush_tracing()` before exit. SDK-export tests use an
in-memory exporter; the rest of the unit suite disables tracing.

The integration follows the official
[Langfuse skill](https://github.com/langfuse/skills/tree/main/skills/langfuse) and
[tracing best practices](https://langfuse.com/docs/observability/best-practices).

## What you'll build

A customer-support agent with tool use over a knowledge base and a ticketing
system. It reasons with Claude Opus 4.8, retrieves answers that cite their
source, runs a guardrail stack on every step (PII redaction, safety and refusal,
injection quarantine), and decides whether to answer or escalate based on how
well its draft is supported. The point is reliability, not a demo: the agent
answers grounded questions with citations, escalates the rest, and proves its
reliability with numbers you measured yourself.

## How to finish this capstone

You are done when the harness has measured it. The single graded artifact is the
eval report the harness writes on your own held-out tickets: `eval_report.json`
(with its companion `eval_report.md`). You are done when:

- `make test` passes (guardrails, retrieval-to-citation, confidence gate, and the
  loop, all without an API key or a GPU).
- `make eval` has run on your held-out set and written `eval_report.json` with a
  measured resolution rate and hallucination rate.
- The threshold sweep has picked a `τ*` that holds the hallucination rate at or
  below your target (`--hallucination-target 0.02`), and `HANDOFF_THRESHOLD` is
  set to it.
- Every number you report came from a run. Cited references keep their source
  URL, nothing is fabricated, and no "you will measure" value is filled in without
  a run behind it.

---

A customer-support agent you can put in front of real users. It answers from a
real knowledge base and a ticketing system, runs a guardrail on every step,
escalates to a human before it guesses, and traces the token and dollar cost of
each call. The point of the project is reliability, not a demo: a support agent
is only useful if it is right most of the time and says so when it is not.

The numbers that describe this agent (resolution rate, hallucination rate, tone,
and the handoff threshold) are produced by the eval suite in `eval/`, on your
own held-out tickets, on your own hardware. This repository ships the code and
the harness; it does not ship a benchmark score for the agent, because a score
is only real once you have run the harness. Where a metric has not been measured,
the results table below shows the exact command that measures it.

The pinned facts (model IDs, prices, cited benchmarks, tool versions, hardware)
live in [`FACTS.md`](FACTS.md). The blueprint for the four surfaces (this repo,
the website, the deck, the book) lives in [`SPEC.md`](SPEC.md).

---

## Architecture

One customer turn flows through the system like this:

```
  customer message
        │
        ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  gateway (FastAPI): POST /chat                                │
  └───────────────┬──────────────────────────────────────────────┘
                  ▼
  PII redaction (Presidio)  ─── raw PII never reaches the model or the logs
                  ▼
  input gate (Llama Guard 4 + refusal policy)  ─── disallowed / out of scope → refuse
                  ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  agent loop (Claude Opus 4.8, tool use)                       │
  │    ├─ knowledge_base   → retrieval over pgvector, cited chunks│
  │    ├─ order_lookup     → order / account status by ID         │
  │    ├─ read/create/update ticket → the ticketing system        │
  │    └─ escalate_to_human → the handoff queue                   │
  │  every tool result is quarantined before the model reads it   │
  └───────────────┬──────────────────────────────────────────────┘
                  ▼
  confidence score (Claude Haiku 4.5)  ─── how well is the answer supported?
                  ▼
  handoff decision vs τ*   ─── below τ*, escalate instead of answering
                  ▼
  response gate (Llama Guard 4)         ─── unsafe draft → escalate
                  ▼
  answer + citations, or a human handoff, plus per-step traces and cost
```

Two levers make the agent safe to deploy. The first is the guardrail stack that
runs on every step: PII is redacted on the way in, tool output is treated as
untrusted and sanitized before the model reads it, and a safety classifier scores
both the input and the drafted response. The second is the confidence threshold
τ\*: the agent answers when its confidence in a grounded answer is at or above
τ\*, and it escalates to a human below it. τ\* is not a guess; it is the value
the threshold sweep picks to hold the hallucination rate under a target.

The reasoning model runs on Anthropic's API, so no GPU runs on our side for the
agent loop. The only accelerator on our side serves the self-hosted Llama Guard 4
safety classifier and, optionally, a local embedding model (see `FACTS.md`
Section 4).

---

## What you build

- **An agent loop with tool use** over a knowledge base and a ticketing system
  (`src/support_agent/agent/`, `src/support_agent/tools/`). It uses Claude Opus
  4.8 with adaptive thinking and strict tool schemas, so a tool call's input is
  parsed as JSON rather than string-matched.
- **A knowledge base that cites its sources** (`src/support_agent/kb/`).
  Documents are chunked, embedded (hosted `text-embedding-3-large` by default,
  or a local `bge-m3`), and stored in pgvector with an HNSW index. Retrieval
  returns the chunk text and its source, and the agent may cite only chunks it
  retrieved.
- **A guardrail stack** (`src/support_agent/guardrails/`): PII redaction with
  Presidio, safety and refusal with Llama Guard 4, and an injection quarantine
  that defangs instructions hidden inside tool output.
- **Confidence-based handoff** (`src/support_agent/agent/confidence.py`): a
  per-turn score of how well the answer is supported by its sources, and the
  decision to escalate below τ\*.
- **Tracing and cost accounting** (`src/support_agent/observability/`):
  OpenTelemetry GenAI spans for every step, and a per-call dollar cost computed
  from the real usage fields, exported to Langfuse or any OTLP backend.
- **An offline eval suite** (`eval/`) that measures resolution rate,
  hallucination rate (RAGTruth-style claim grounding), tone, accuracy, and the
  τ\* that holds hallucination under target.

---

## Step by step

1. **Install.** `make install` installs the package with its dev and PII extras
   and downloads the spaCy model Presidio uses. Copy `.env.example` to `.env` and
   fill in your keys.
2. **Bring up the stack.** `make db-up` starts Postgres with pgvector, a Llama
   Guard 4 model server, an OpenTelemetry collector, and Langfuse.
3. **Ingest the knowledge base.** Add approved production documents to
   `knowledge_base/approved` (or set `KB_DOCS_PATH`) and run `make ingest`.
   The held-out ticket dataset is never an ingestion source. The Markdown files
   in `eval/datasets/kb_docs` are the evaluation corpus; use them explicitly for
   local tests, not as the production corpus.
4. **Serve the agent.** `make serve` runs the FastAPI gateway. `POST /chat` takes
   a conversation ID and a message and returns the decision, the answer, the
   citations, the confidence, and the cost. `GET /healthz` reports the model IDs
   the service is configured with.
5. **Run the eval.** `make eval` runs the agent over the held-out ticket set and
   writes `eval_report.json` and `eval_report.md`. Each metric is measured on the
   run; nothing is filled in from memory.
6. **Choose τ\*.** `make threshold` sweeps the confidence cutoff and prints the
   largest τ that holds the hallucination rate under the target. Set
   `HANDOFF_THRESHOLD` to that value.
7. **External benchmark (optional).** `make tau2-bench` previews the current
   official tau2 test split; it does not run this repository's agent and does
   not make API calls unless `--execute` is added. `make tau-bench` retains the
   legacy `tau_bench` interface. See `docs/BENCHMARK_SETUP.md` for the
   compatibility decision and setup. `make validate-datasets` checks local and
   acquired external dataset files.

---

## Reproduce

```bash
# install and configure
make install
cp .env.example .env        # fill in ANTHROPIC_API_KEY and the rest

# stack: Postgres+pgvector, Llama Guard 4, OTel, Langfuse
make db-up

# ingest the knowledge base into pgvector
make ingest

# run the service (POST /chat, GET /healthz)
make serve

# offline eval over the held-out ticket set
make eval
python -m eval.run --suite heldout --check hallucination
python -m eval.run --suite heldout --check tone

# pick the handoff threshold that holds hallucination under target
python -m eval.threshold --hallucination-target 0.02 --k 8

# deterministic guardrail + loop unit tests (no API key, no GPU)
make test

# preview the official tau2 test split (not this repository's agent)
python -m eval.tau2_bench_adapter --domain retail
```

The unit tests (`make test`) run without an API key or a GPU: they use a fake
model client and a deterministic embedder, so they check the guardrails, the
retrieval-to-citation path, the confidence gate, and the loop control flow on
their own. The eval and threshold commands call the live model on real hardware;
they exit early with an instruction if `ANTHROPIC_API_KEY` is unset, rather than
producing a number.

---

## Results

The table mixes two kinds of rows, and keeps them apart. Cited reference rows
come from published papers and leaderboards; they describe other systems and set
a rough ceiling for the problem. The "you will measure" rows are this agent's
metrics, shown as the command that produces them. A cited number is never
presented as this agent's score, and a "you will measure" row is never filled in
before a run.

### Cited references (other systems, not this agent)

| Reference | Figure | Source |
|---|---|---|
| τ-bench, GPT-4o, retail/airline | under 50% at pass^1; pass^8 under 25% in retail | [arXiv 2406.12045](https://arxiv.org/abs/2406.12045) |
| AgentDojo, GPT-4o | 69% benign utility, 45% under attack; "Important message" injection up to 53.1% attack success | [OpenReview m1YYAQjO3w](https://openreview.net/forum?id=m1YYAQjO3w) |
| τ-bench airline, recent Sonnet-class model | near 0.70 on a public aggregator (verify live) | [llm-stats](https://llm-stats.com/benchmarks/tau-bench-airline), [taubench.com](https://www.taubench.com) |
| RAGTruth | ~18,000 annotated RAG responses; over 91% response-level annotator agreement | [arXiv 2401.00396](https://arxiv.org/abs/2401.00396) |

τ-bench measures reliability with pass^k, the fraction of tasks solved on all k
independent trials, which is what a support deployment cares about. These figures
are context. They are not our result.

### You will measure (this agent, on your held-out set)

| Metric | Definition | Reproduce |
|---|---|---|
| Resolution rate | fraction of tickets that reach the golden answer or correctly perform a golden handoff | `make eval` |
| Hallucination rate | fraction of answered responses with a claim not supported by a retrieved chunk or a tool result | `python -m eval.run --suite heldout --check hallucination` |
| Tone | fraction of answered responses meeting the brand tone rubric | `python -m eval.run --suite heldout --check tone` |
| Handoff threshold τ\* | the confidence cutoff that holds hallucination under target | `python -m eval.threshold --hallucination-target 0.02 --k 8` |

The headline for this agent is the resolution rate and the hallucination rate on
the held-out set, together with the τ\* that holds the hallucination rate under
target. Run the harness to fill these in.

### Cost

Cost is arithmetic on the real usage fields the API returns, multiplied by the
rates in `FACTS.md` Section 1. The tracing layer reports the dollar cost of a run
exactly; it is not an estimate and not a benchmark. `POST /chat` returns
`cost_usd` for the turn, and each span carries its token counts and cost.

---

## Guardrails and safety

| Guardrail | What it blocks | Where |
|---|---|---|
| PII redaction (Presidio) | emails, cards, SSNs, phone numbers reaching the model or the logs | `guardrails/pii.py` |
| Safety and refusal (Llama Guard 4) | disallowed input and unsafe drafted responses | `guardrails/safety.py`, `guardrails/refusal.py` |
| Injection quarantine | instructions hidden inside tool output steering the agent | `guardrails/injection.py` |
| Confidence handoff | answering below τ\* instead of escalating | `agent/confidence.py` |

The injection test (`tests/test_injection.py`) asserts that an instruction
embedded in a tool result reaches the model only as annotated, untrusted content,
and does not trigger an unsanctioned tool call. This is the local counterpart to
the AgentDojo reference above.

---

## Repository layout

```
src/support_agent/
  config.py            env-only settings
  schemas.py           Ticket, Message, Citation, Decision, Trace
  server.py            FastAPI gateway
  agent/               loop, prompts, model routing, confidence
  tools/               registry, knowledge_base, ticketing, order_lookup, handoff
  kb/                  ingest, embed, pgvector store
  guardrails/          pii, safety, refusal, injection
  observability/       tracing, cost
eval/
  run.py               offline eval over held-out tickets
  threshold.py         sweep confidence, pick τ*
  report.py            emit eval_report.{json,md} + figures
  judges.py            LLM-as-judge: grounding, tone
  metrics/             resolution, hallucination, tone, accuracy
  tau_bench_adapter.py legacy tau_bench-interface adapter
  tau2_bench_adapter.py standalone official tau2 test-split runner
  validate_datasets.py validate local and official benchmark datasets
  datasets/            sample held-out tickets + KB docs
docs/                   dataset, benchmark, and evaluation guides
tests/                 deterministic guardrail + loop tests
```

---

## Citations

- Yao, Shinn, Razavi, Narasimhan. τ-bench: A Benchmark for Tool-Agent-User
  Interaction in Real-World Domains. arXiv 2406.12045.
  <https://arxiv.org/abs/2406.12045> · code <https://github.com/sierra-research/tau-bench>
- Barres, Dong, Ray, Si, Narasimhan. τ²-bench: Evaluating Conversational Agents
  in a Dual-Control Environment. arXiv 2506.07982.
  <https://arxiv.org/abs/2506.07982> · code <https://github.com/sierra-research/tau2-bench>
- Debenedetti et al. AgentDojo: A Dynamic Environment to Evaluate Attacks and
  Defenses for LLM Agents. NeurIPS 2024. <https://openreview.net/forum?id=m1YYAQjO3w>
  · code <https://github.com/ethz-spylab/agentdojo>
- Niu et al. RAGTruth: A Hallucination Corpus for Developing Trustworthy
  Retrieval-Augmented Language Models. ACL 2024. arXiv 2401.00396.
  <https://arxiv.org/abs/2401.00396> · code <https://github.com/ParticleMedia/RAGTruth>
- Microsoft Presidio. <https://github.com/microsoft/presidio>
- Meta Llama Guard 4 (12B). <https://huggingface.co/meta-llama/Llama-Guard-4-12B>
- OpenAI text-embedding-3-large.
  <https://openai.com/index/new-embedding-models-and-api-updates/>
- BAAI BGE-M3. <https://huggingface.co/BAAI/bge-m3>
- pgvector. <https://github.com/pgvector/pgvector>
- OpenTelemetry GenAI semantic conventions.
  <https://opentelemetry.io/docs/specs/semconv/gen-ai/> · Langfuse <https://langfuse.com>
- NVIDIA H100 datasheet. <https://www.nvidia.com/en-us/data-center/h100/>

```bibtex
@article{yao2024taubench,
  title={{$\tau$-bench}: A Benchmark for Tool-Agent-User Interaction in Real-World Domains},
  author={Yao, Shunyu and Shinn, Noah and Razavi, Pedram and Narasimhan, Karthik},
  journal={arXiv preprint arXiv:2406.12045},
  year={2024}
}

@article{barres2025tau2bench,
  title={{$\tau^2$-bench}: Evaluating Conversational Agents in a Dual-Control Environment},
  author={Barres, Victor and Dong, Honghua and Ray, Soham and Si, Xujie and Narasimhan, Karthik},
  journal={arXiv preprint arXiv:2506.07982},
  year={2025}
}

@inproceedings{debenedetti2024agentdojo,
  title={{AgentDojo}: A Dynamic Environment to Evaluate Attacks and Defenses for {LLM} Agents},
  author={Debenedetti, Edoardo and Zhang, Jie and Balunovi{\'c}, Mislav and Beurer-Kellner, Luca and Fischer, Marc and Tram{\`e}r, Florian},
  booktitle={Advances in Neural Information Processing Systems (NeurIPS)},
  year={2024}
}

@article{niu2024ragtruth,
  title={{RAGTruth}: A Hallucination Corpus for Developing Trustworthy Retrieval-Augmented Language Models},
  author={Niu, Cheng and Wu, Yuanhao and Zhu, Juno and Xu, Siliang and Shum, KaShun and Zhong, Randy and Song, Juntong and Zhang, Tong},
  journal={arXiv preprint arXiv:2401.00396},
  year={2024}
}
```

---

## License

MIT. See [LICENSE](LICENSE).
