# FACTS.md — Production Customer-Support Agent

The single source of truth for this capstone. The repo, the website, the slide deck, and the
companion book all draw their numbers, names, and claims from this file and must not contradict
it. If a value is not here, it does not get stated as fact downstream.

---

## Grounding rule (read first)

This project cannot run GPU or production infrastructure inside the build environment, so it
cannot produce its own benchmark numbers here. Every number in this file is one of two kinds, and
each kind is labelled:

1. **Published reference** — a real figure from a paper, model card, datasheet, or leaderboard,
   with a source URL. These describe other systems, not our agent. They are cited so a reader can
   check them.
2. **You will measure** — a metric our agent produces only when the eval harness runs on real
   hardware against the held-out ticket set. These carry the exact reproduce command instead of a
   number. Never fill one in with a guessed value.

If a precise number for our own agent is not in a "you will measure" row backed by a run, write
the trend in words or leave the placeholder. A paying student will check the arithmetic and the
citations, so correct-and-modest beats plausible-and-wrong. Results tables may mix cited reference
rows and clearly-labelled "you will measure" rows in the same table, as long as the two are never
confused.

---

## 1. Models

The reasoning model is API-hosted (Anthropic Claude), so no GPU runs on our side for the main
agent loop. Model IDs and prices are the exact strings and rates as of the Anthropic models
reference cached 2026-06-24; confirm against the live models page before a launch.

| Role in the system | Model | Model ID | Context | Max output | Price in / out per 1M tok |
|---|---|---|---|---|---|
| Primary agent reasoner (tool use, resolution) | Claude Opus 4.8 | `claude-opus-4-8` | 1M | 128K | $5.00 / $25.00 |
| Cost-efficient tier (high-volume routing) | Claude Sonnet 5 | `claude-sonnet-5` | 1M | 128K | $3.00 / $15.00 ($2.00 / $10.00 intro through 2026-08-31) |
| Cheap classifier (tone score, confidence gate, PII pre-scan) | Claude Haiku 4.5 | `claude-haiku-4-5` | 200K | 64K | $1.00 / $5.00 |

Fixed API facts we build against (not model-specific guesses):

- Thinking on Opus 4.8 / Sonnet 5 is adaptive only: `thinking={"type":"adaptive"}`. `budget_tokens`
  and `temperature`/`top_p`/`top_k` return HTTP 400 on these models. Depth is controlled with
  `output_config={"effort": "low|medium|high|xhigh|max"}`.
- Assistant-turn prefill returns 400 on Opus 4.8 / Sonnet 5. Force JSON with
  `output_config.format` (structured outputs), not a prefill.
- Tool-call `input` is parsed with `json.loads`, never string-matched.
- Per-call cost = `usage.input_tokens`, `usage.output_tokens`, `usage.cache_read_input_tokens`,
  `usage.cache_creation_input_tokens` multiplied by the rates above. Cost is arithmetic on real
  usage fields, so the tracing layer reports it exactly; it is not a benchmark.
- Source: Anthropic models overview and pricing, https://platform.claude.com/docs/en/about-claude/models/overview and https://platform.claude.com/docs/en/about-claude/pricing

---

## 2. Published benchmark references (cited; these are other systems, not ours)

These frame the problem and give a sanity ceiling. They are not our agent's scores. Our agent's
resolution and hallucination numbers come from Section 5 ("you will measure").

### 2.1 τ-bench (tool-agent-user customer service)

- Name: τ-bench (tau-bench). Authors: Shunyu Yao, Noah Shinn, Pedram Razavi, Karthik Narasimhan (Sierra).
- Domains: **retail** and **airline**. Task type: a language agent uses tools against a database
  while a user simulator supplies goals over multiple turns.
- Reliability metric: **pass^k** — the fraction of tasks solved on *all* k independent trials
  (not "at least one"). It measures consistency, which is what a support deployment cares about.
- Reported baseline: even a state-of-the-art function-calling agent (GPT-4o) succeeds on **under
  50%** of tasks at pass^1, and is inconsistent, with **pass^8 under 25% in retail**.
- Source: arXiv 2406.12045, https://arxiv.org/abs/2406.12045 ; code https://github.com/sierra-research/tau-bench

### 2.2 τ²-bench (dual-control)

- Name: τ²-bench (tau2-bench). Authors: Victor Barres, Honghua Dong, Soham Ray, Xujie Si, Karthik Narasimhan.
- Adds a **telecom** domain modelled as a Dec-POMDP where *both* the agent and the user can call
  tools (dual control), reflecting collaborative troubleshooting.
- Headline finding: agents show a **significant performance drop** moving from single-control
  (only the agent acts) to dual-control (the agent must also guide the user). Coordination and
  communication failures are separated from pure reasoning errors.
- Source: arXiv 2506.07982, https://arxiv.org/abs/2506.07982 ; code https://github.com/sierra-research/tau2-bench

### 2.3 Live leaderboard figures (third-party aggregator, move over time)

Used only as a rough external ceiling, not as our result. Treat as current-at-time-of-writing and
re-check the live board.

- A recent Claude Sonnet-class model is reported near **0.70 (70%) on τ-bench airline** on a public
  aggregator leaderboard.
- Source (aggregator, verify live): https://llm-stats.com/benchmarks/tau-bench-airline and the
  official board at https://www.taubench.com

### 2.4 Prompt-injection / jailbreak resistance reference

- Name: AgentDojo (NeurIPS 2024). 97 realistic user tasks and 629 security test cases across
  banking, Slack, travel, and workspace tools. Metrics: benign utility, utility under attack,
  attack success rate.
- Reported baseline: GPT-4o reaches **69% benign utility**, falling to **45% under attack**; the
  "Important message" indirect-injection attack reaches up to **53.1%** attack success rate.
- Why it is here: it is the reference for our injection-resistance test in Section 5.
- Source: OpenReview m1YYAQjO3w, https://openreview.net/forum?id=m1YYAQjO3w ; code https://github.com/ethz-spylab/agentdojo

### 2.5 Hallucination-measurement methodology reference

- Name: RAGTruth (ACL 2024). A corpus of ~**18,000** RAG responses with **word-level** hallucination
  annotations under a four-class taxonomy, with **over 91%** response-level annotator agreement.
- Why it is here: our hallucination metric copies its unit of analysis (a claim not supported by
  the retrieved context), so our judge and human audit are calibrated against a published protocol.
- Source: arXiv 2401.00396, https://arxiv.org/abs/2401.00396 ; code https://github.com/ParticleMedia/RAGTruth

---

## 3. Tooling and versions (names are load-bearing; pin them)

| Layer | Tool | Fact we rely on | Source |
|---|---|---|---|
| PII redaction | Microsoft Presidio | Detect + anonymize PII in text (Analyzer, Anonymizer, Image Redactor, Structured); MIT license; latest release line 2.2.x (2.2.362, Mar 2026) | https://github.com/microsoft/presidio |
| Safety / refusal classifier (self-hosted) | Llama Guard 4 | 12B dense params, pruned from Llama 4 Scout, multimodal; classifies both the input prompt and the model response against the MLCommons hazards taxonomy | https://huggingface.co/meta-llama/Llama-Guard-4-12B and https://github.com/meta-llama/PurpleLlama/blob/main/Llama-Guard4/12B/MODEL_CARD.md |
| Embeddings (hosted default) | OpenAI text-embedding-3-large | 3072-dim vectors, MTEB average 64.6, released 2024-01-25, Matryoshka truncation (shorten via `dimensions`) | https://openai.com/index/new-embedding-models-and-api-updates/ |
| Embeddings (self-host option) | BAAI BGE-M3 | Hybrid dense + sparse + multi-vector retrieval, 1024-dim dense output, 8192-token input | https://huggingface.co/BAAI/bge-m3 |
| Vector store | pgvector (Postgres extension) | HNSW and IVFFlat indexes; cosine / L2 / inner-product distance; runs inside Postgres so KB and tickets share one database | https://github.com/pgvector/pgvector |
| Tracing standard | OpenTelemetry GenAI semantic conventions | Standard span attributes `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons`; status experimental as of 2026, already usable | https://opentelemetry.io/blog/2026/genai-observability/ and https://opentelemetry.io/docs/specs/semconv/gen-ai/ |
| Trace backend | Langfuse (OTLP-compatible) | Stores per-step traces + token/cost; open source; alt: Arize Phoenix | https://langfuse.com |

Runtime baseline: Python 3.12, `anthropic` SDK (Messages API + beta tool runner), FastAPI for the
service, `pydantic-settings` for env-only config, Postgres 16 + pgvector for storage. All secrets
(API keys, DB URL, model-server URL) are read from environment variables. No key is committed.

---

## 4. Hardware (only the self-hosted guardrail and optional local embedder use a GPU)

The Claude reasoner runs on Anthropic's infrastructure, so the only GPU on our side serves the
Llama Guard 4 safety classifier and, optionally, a local embedding model.

### 4.1 Reference accelerator — NVIDIA H100 SXM5

Published datasheet figures (a `*` means "with sparsity"; dense throughput is half the starred
number):

- Memory: **80 GB HBM3**, bandwidth **3.35 TB/s**.
- Tensor Core throughput: **TF32 989 TFLOPS\***, **BF16 1,979 TFLOPS\*** (~989.5 dense),
  **FP16 1,979 TFLOPS\***, **FP8 3,958 TFLOPS\*** (~1,979 dense), **INT8 3,958 TOPS\***.
- Power: up to **700 W** (SXM). NVLink: **900 GB/s**.
- Source: NVIDIA H100 datasheet, https://www.nvidia.com/en-us/data-center/h100/

### 4.2 Practical serving cards for the 12B guardrail

Weight footprint is deterministic arithmetic, not a benchmark: 12B parameters is **~24 GB** at
BF16 (2 bytes/param) and **~12 GB** at FP8/INT8 (1 byte/param), before KV cache and activations.

- A 24 GB card (e.g. NVIDIA L4 24 GB GDDR6, or A10G 24 GB) runs Llama Guard 4 **only quantized**
  to FP8/INT8.
- A 48 GB card (e.g. NVIDIA L40S 48 GB GDDR6, or A6000 48 GB) runs it in BF16 with headroom, and
  can co-host a local embedding model.
- Throughput and latency on a given card are **you will measure** (Section 5), not stated here.

---

## 5. The metrics that matter (you will measure — reproduce commands, not numbers)

These four are the point of the project. None has a number in this file, because none has been
run. Each row states exactly what to run and what a real run reports.

| Metric | Definition | How it is computed | Reproduce |
|---|---|---|---|
| **Resolution rate** | Fraction of held-out tickets that reach the golden outcome; a handoff counts as resolved when handoff is the expected outcome | Agent transcript vs golden resolution on the held-out set | `make eval` → `python -m eval.run --suite heldout` |
| **Hallucination rate** | Fraction of answered responses containing a claim not supported by retrieved KB text or a tool result | RAGTruth-style claim grounding: every factual claim must cite a retrieved chunk or tool output; unsupported claims are flagged by an LLM judge and human-audited | `python -m eval.run --suite heldout --check hallucination` |
| **Tone** | Fraction of answered responses meeting the brand tone rubric | LLM-as-judge scored against the rubric in `agent/prompts.py`, spot-audited by a human | `python -m eval.run --suite heldout --check tone` |
| **Handoff threshold τ\*** | The confidence cutoff that keeps hallucination rate under target | Sweep the confidence score; for each τ, plot resolution coverage vs hallucination rate; pick the largest τ where hallucination ≤ target; below τ the agent escalates to a human | `python -m eval.threshold --hallucination-target 0.02 --k 8` |

Supporting checks:

- **Guardrail unit tests** (deterministic, run anywhere): PII redaction, refusal policy,
  injection quarantine. `pytest tests/`
- **External benchmark** (optional, needs API budget to execute): the legacy
  `eval.tau_bench_adapter` uses the older `tau_bench` interface and is distinct from the current
  official `tau2` package. `eval.tau2_bench_adapter` previews/runs tau2's native runner on its
  official test split; it does **not** evaluate this repository's policy. Preview with
  `python -m eval.tau2_bench_adapter --domain retail`; add `--execute` only when intentionally
  making paid model/judge calls. See `docs/BENCHMARK_SETUP.md`.

Honest framing for every downstream surface: the headline is **resolution rate and hallucination
rate on the held-out ticket set, plus the τ\* that holds hallucination under the target**. The
τ-bench numbers in Section 2 are context, not our result. Any "you will measure" cell shown before
a run is displayed as a reproduce command, never as a filled-in figure.

---

## 6. Global editorial constraints

- No fabricated agent scores anywhere. A results table shows either a cited reference (Section 2)
  or a "you will measure" reproduce command (Section 5).
- Model IDs are the exact strings in Section 1. Never append date suffixes to Opus/Sonnet/Haiku
  aliases.
- Secrets are environment-only. No API key, token, or DB URL appears in any committed file, figure,
  slide, or page.
- Prose across all four surfaces follows the Vizuara writing voice: plain words, complete
  sentences, no performed sincerity, no drama dashes, concrete over grand.
