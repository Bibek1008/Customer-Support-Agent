# SPEC.md — Production Customer-Support Agent

The blueprint for the four surfaces: the repo, the website, the slide deck, and the companion
book. Every number, model name, and claim comes from `FACTS.md`. Where a metric is not yet
measured, the surface shows the reproduce command from `FACTS.md` Section 5, never a filled-in
figure.

The capstone builds one thing: a customer-support agent safe to put in front of real users. It has
tool use over a real knowledge base and a ticketing system, an offline eval suite (accuracy,
resolution rate, hallucination rate, tone), guardrails (PII redaction, refusal policy, injection
resistance), confidence-based human handoff, and full tracing and cost accounting of every step.

---

## 1. Repository file tree

```
production-support-agent/
  FACTS.md                         Pinned facts: models, cited benchmarks, tools, hardware, metrics.
  SPEC.md                          This blueprint for all four surfaces.
  README.md                        What it is, the honest headline, quickstart, reproduce commands.
  pyproject.toml                   Python 3.12 project; deps: anthropic, fastapi, pgvector, presidio, opentelemetry.
  .env.example                     Every env var the system reads; real secrets never committed.
  Makefile                         ingest / serve / eval / test one-liners.
  src/support_agent/
    __init__.py
    config.py                      Env-only settings via pydantic-settings; no hardcoded secrets.
    schemas.py                     Typed core objects: Ticket, Message, Turn, Citation, Decision, Trace.
    server.py                      FastAPI app: POST /chat, GET /healthz; wires guardrails + agent + tracing.

    agent/
      __init__.py
      loop.py                      The agent loop over the Claude tool runner; halts on resolve or handoff.
      prompts.py                   System prompt, refusal policy, and the brand tone rubric (one place).
      models.py                    Model routing: Opus 4.8 reasoner, Haiku 4.5 classifier (IDs from FACTS.md).
      confidence.py                Per-turn confidence score and the handoff decision against threshold tau*.

    tools/
      __init__.py
      registry.py                  Tool JSON schemas + dispatch; strict tool use; parallel-safe flags.
      knowledge_base.py            Retrieval tool over the pgvector KB; returns cited chunks only.
      ticketing.py                 Create / read / update tickets against the ticketing API client.
      order_lookup.py              Example domain tool: order and account status by ID.
      handoff.py                   escalate_to_human tool; packages transcript + confidence for the queue.

    kb/
      __init__.py
      ingest.py                    Chunk KB docs, embed, upsert into pgvector with source metadata.
      embed.py                     Embedding client: text-embedding-3-large default, BGE-M3 self-host option.
      store.py                     pgvector store (HNSW); retrieval returns text + source for citation.

    guardrails/
      __init__.py
      pii.py                       Presidio analyzer + anonymizer: redact PII on input and before logging.
      safety.py                    Llama Guard 4 client: classify input prompt and model response.
      refusal.py                   Refusal policy: out-of-scope, disallowed, and low-confidence paths.
      injection.py                 Treat tool output as untrusted; quarantine and sanitize before the model reads it.

    observability/
      __init__.py
      tracing.py                   OpenTelemetry GenAI spans for every step; export OTLP to Langfuse.
      cost.py                      Per-step token and dollar accounting from usage fields (arithmetic, exact).

  eval/
    __init__.py
    run.py                         Offline eval runner over the held-out ticket set; --check selects a metric.
    threshold.py                   Sweep confidence; pick tau* holding hallucination <= target; write the curve.
    report.py                      Emit eval_report.json + eval_report.md + figures for the website and deck.
    judges.py                      LLM-as-judge prompts: grounded hallucination check, tone rubric scorer.
    tau_bench_adapter.py           Legacy tau_bench-interface adapter.
    tau2_bench_adapter.py          Standalone official tau2 runner; does not run this agent.
    validate_datasets.py           Validate local datasets and acquired official benchmark files.
    metrics/
      __init__.py
      resolution.py                Resolution rate vs golden outcomes.
      hallucination.py             Claim-grounding check, RAGTruth-style unit of analysis.
      tone.py                      Tone rubric scoring.
      accuracy.py                  Answer correctness against golden answers.
    datasets/
      heldout_tickets.jsonl        Held-out labeled tickets with golden resolutions (sample; real set is private).
      kb_docs/                     Sample knowledge-base corpus for local runs.

  tests/
    test_guardrails_pii.py         PII is redacted on input and never reaches logs.
    test_guardrails_safety.py      Unsafe input and unsafe response are both caught by Llama Guard 4.
    test_injection.py              Injected instruction inside a tool result does not trigger an unsanctioned tool call.
    test_retrieval_citations.py    Every answer claim maps to a retrieved chunk.
    test_confidence_handoff.py     Below tau*, the agent escalates instead of answering.
    test_agent_loop.py             End-to-end resolve path and end-to-end handoff path.

  website/
    index.html                     Single-file deep site (the content spine in Section 2).
    assets/                        Figures from eval/report.py + the architecture diagram.

  deck/
    slides.md                      Slidev deck (the arc in Section 3), reusing the book figures.
    vite.config.ts                 Widen fs.allow so /figures/* resolve in dev.

  book/
    manifest.json                  Sections and chapters (titles in Section 4).
    articles/                      One markdown file per chapter.
    figures/                       Hand-drawn figures shared with the deck.
```

---

## 2. Original website content spine (historical)

The original single-file capstone landing page has been removed. The deployed
customer chat and staff inbox now live in `frontend/` (Next.js on Vercel).
The content outline below records the original specification for reference.

Fixed order, each section led by an eyebrow label, matching the house deep-site pattern.

1. **Hero** — name, one-line tagline ("a support agent safe to put in front of real users"),
   link buttons (code, reproduce, book), one architecture image.
2. **The whole idea** — a support agent is only useful if it is reliable and honest about what it
   does not know. Two levers make that true: guardrails on every step, and a confidence threshold
   that hands off before it guesses.
3. **Method** — the agent loop; tools over the knowledge base and ticketing; retrieval that returns
   cited chunks; the guardrail stack (PII redaction, safety and refusal classifier, injection
   quarantine); confidence-based handoff; tracing and cost on every step.
4. **Worked example** — one real ticket walked end to end: retrieve, cite, answer, and the parallel
   path where confidence is low and the agent escalates instead.
5. **Results, with caveats** — the results table mixes two clearly-labelled row types. Cited
   reference rows come from `FACTS.md` Section 2 (τ-bench GPT-4o pass^1 under 50% and pass^8 under
   25% retail; AgentDojo 69% benign to 45% under attack; the leaderboard airline ceiling near
   0.70). "You will measure" rows (resolution rate, hallucination rate, tone, τ\*) show the exact
   reproduce command from Section 5, not a number. The page states plainly that the τ-bench figures
   are context, and the headline metric is resolution rate and hallucination rate on the held-out
   set plus the τ\* that holds hallucination under target.
6. **Guardrails and safety** — what each guardrail blocks, and the injection test against the
   AgentDojo reference.
7. **Reproduce** — a dark code block with the real commands: `make ingest`, `make serve`,
   `make eval`, `python -m eval.threshold --hallucination-target 0.02 --k 8`, and the optional
   `python -m eval.tau2_bench_adapter --domain retail` to preview the official test split.
   The current runner uses tau2's native agent and does not evaluate this project's policy;
   see `docs/BENCHMARK_SETUP.md` for the compatibility decision.
8. **Citations** — every source URL from `FACTS.md` Sections 2 through 4, plus a BibTeX block for
   τ-bench, τ²-bench, AgentDojo, and RAGTruth.

---

## 3. Slide arc (`deck/slides.md`, Slidev)

Section covers use the paper aesthetic; figures are reused from the book.

1. **Title** — the agent, the one-line claim, the honest headline framing.
2. **Why reliability, not demos** — τ-bench pass^k and the GPT-4o baseline (cited): consistency is
   the hard part.
3. **Architecture** — one diagram: user, guardrails, agent loop, tools, knowledge base, ticketing,
   handoff queue, tracing.
4. **Tool use over a real knowledge base** — retrieval with citations; pgvector; embeddings.
5. **Ticketing and actions** — the tools that change state, and why they are gated.
6. **Guardrails** — PII redaction (Presidio), safety and refusal (Llama Guard 4), injection
   quarantine (AgentDojo reference).
7. **Confidence and handoff** — the τ\* idea: answer above threshold, escalate below it.
8. **The eval suite** — accuracy, resolution rate, hallucination rate, tone; how each is scored.
9. **The honest metric** — resolution rate and hallucination rate on the held-out set, and the
   τ\* that holds hallucination under target; shown as reproduce commands until measured.
10. **Tracing and cost** — OpenTelemetry GenAI spans; per-step token and dollar accounting.
11. **Reproduce** — the commands, with a clearly-labelled standalone tau2 preview rather than
    a claim that the current project agent has been evaluated on τ-bench.
12. **What to build next** — dual-control (τ²-bench), multilingual, live A/B on τ\*.

---

## 4. Companion-book chapter list (titles only)

Section 1 — Foundations
1. What a support agent actually has to do
2. Reliability is the product: pass^1 versus pass^k
3. The shape of a safe agent

Section 2 — Building the agent
4. The agent loop with tool use
5. A knowledge base that cites its sources
6. Tools that read, and tools that act
7. Talking to the ticketing system

Section 3 — Guardrails
8. Redacting PII before anything sees it
9. A refusal policy that holds
10. Jailbreak and injection resistance
11. When the tool output is the attacker

Section 4 — Knowing when to stop
12. Confidence, and what it is not
13. The handoff threshold τ\*
14. Escalating to a human without dropping the ticket

Section 5 — Measuring it
15. Building a held-out ticket set
16. Resolution rate and accuracy
17. Measuring hallucination the RAGTruth way
18. Scoring tone
19. Choosing τ\* to hold hallucination under target

Section 6 — Running it in production
20. Tracing every step with OpenTelemetry
21. Counting tokens and dollars
22. Cross-checking against τ-bench
23. What breaks first, and what to build next
