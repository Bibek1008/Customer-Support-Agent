# Dataset validation and evaluation guide

All commands below are Windows PowerShell commands run from the project root.
The deterministic tests and dataset validation do not call Anthropic/OpenAI,
do not download large models, and do not require a GPU.

## Validate datasets

Run the validator and write the requested JSON and Markdown reports:

```powershell
python -m eval.validate_datasets
```

Reports are written to:

- `eval/dataset_validation_report.json`
- `eval/dataset_validation_report.md`

The validator checks local JSONL records, required values and duplicate ticket
IDs; verifies local Markdown knowledge articles; parses every acquired external
JSON file; verifies official benchmark manifests and frozen subset hashes; and
checks that train/test IDs are unique, disjoint, and present in the domain task
files. A banking-knowledge warning is expected because upstream supplies no
train/test split for that domain.

Optional path overrides:

```powershell
python -m eval.validate_datasets --heldout 'C:\secure-data\instructor\heldout.jsonl'
python -m eval.validate_datasets --tau2-data 'D:\benchmarks\tau2\data\tau2'
```

The command exits nonzero when a validation error is detected. It never writes
or repairs dataset contents.

## Configure a private instructor ticket set

Keep the instructor's private evaluation set outside the repository. Do not
overwrite `eval/datasets/heldout_tickets.jsonl`, do not add private records to
the knowledge base, and do not place secrets or customer PII in validation
reports. The expected JSONL schema is documented in
[`DATASET_DOCUMENTATION.md`](./DATASET_DOCUMENTATION.md).

Set a private path for the current PowerShell session, validate it, and select
it explicitly for evaluation:

```powershell
$env:SUPPORT_HELDOUT_DATASET_PATH = 'C:\secure-data\instructor\heldout.jsonl'
python -m eval.validate_datasets --heldout $env:SUPPORT_HELDOUT_DATASET_PATH
python -m eval.run --suite heldout --dataset $env:SUPPORT_HELDOUT_DATASET_PATH
```

`eval.threshold` supports the same path:

```powershell
python -m eval.threshold --hallucination-target 0.02 --k 8 --dataset $env:SUPPORT_HELDOUT_DATASET_PATH
```

The default remains the shipped sample. To persist a path locally, set
`SUPPORT_HELDOUT_DATASET_PATH` in a private, ignored `.env` file. Validate all
IDs are unique and maintain the instructor's intended held-out split before
running. Extending the sample with training or development examples changes the
evaluation population; keep those in separate files.

## Run deterministic tests

```powershell
python -m pytest tests/
```

The suite uses fake model clients, a deterministic embedding fixture, and an
in-memory vector store; it does not connect to PostgreSQL. It covers the
existing guardrail/agent path, dataset validation, official tau2 split
selection, and re-ingestion deduplication. No API credentials are used.

## Run the instructor evaluation

The original pipeline is `eval.run`; it is separate from τ²-bench. Before a
real run, configure `ANTHROPIC_API_KEY`. The default hosted embedder also needs
`OPENAI_API_KEY` if the evaluation knowledge base must be ingested. Evaluation
judges call the configured Anthropic classifier model. These commands make
paid API calls and are intentionally not run by tests:

```powershell
python -m eval.run --suite heldout
python -m eval.run --suite heldout --check resolution
python -m eval.run --suite heldout --check accuracy
python -m eval.run --suite heldout --check hallucination
python -m eval.run --suite heldout --check tone
python -m eval.threshold --hallucination-target 0.02 --k 8
```

The runner writes `eval_report.json` and `eval_report.md` under `eval/out/`.
Its metrics are:

- **Handoff rate:** fraction of tickets the agent hands off.
- **Resolution rate:** fraction reaching the expected answer/handoff outcome.
- **Accuracy:** substring coverage of golden answer spans, for tickets with
  those spans.
- **Hallucination response rate:** answered responses with at least one
  unsupported factual claim, as judged by the configured LLM judge.
- **Hallucination claim rate:** unsupported factual claims divided by all
  claims reported by that judge.
- **Tone pass rate:** answered responses meeting the tone rubric, as judged by
  the configured LLM judge.

The handoff rate and deterministic golden checks are not tau2 rewards. The
hallucination and tone scores are LLM-judge outputs, not official tau2 scores.
Use a dedicated non-production database for evaluation. The evaluation runner
may seed its sample KB when its configured store is empty.

## Run the external benchmark

Install the official `tau2` CLI and preview commands as described in
[`BENCHMARK_SETUP.md`](./BENCHMARK_SETUP.md). Previewing the official test
split does not make API calls:

```powershell
python -m eval.tau2_bench_adapter --domain retail
```

Only `--execute` starts an official tau2 run:

```powershell
python -m eval.tau2_bench_adapter --domain retail --execute
```

The official adapter requires provider credentials and writes tau2-native
results to `eval/out/tau2/<domain>/test/`. It preserves tau2 task rewards; it
does not calculate the instructor metrics or use an LLM-as-judge substitute
for official task rewards. In this integration the agent model is the external
model configured for tau2, **not this repository's policy**. Banking knowledge
is not runnable as a text test split because no split exists and upstream's
released benchmark is voice-only.

## Keep production ingestion isolated

Production ingestion defaults to `KB_DOCS_PATH=knowledge_base/approved` and
reads only `.md` and `.txt` files. Add approved source documents there, or set a
separate production path:

```powershell
$env:KB_DOCS_PATH = 'D:\approved-support-docs'
$env:KB_CHUNK_SIZE = '900'
$env:KB_CHUNK_OVERLAP = '150'
python -m support_agent.kb.ingest
```

The sample evaluation corpus is available explicitly for local development:

```powershell
python -m support_agent.kb.ingest --docs eval/datasets/kb_docs
```

Do not use the latter command against a production database. Ingestion keeps
front-matter fields and relative source references, uses content hashes to
upsert chunks, and stores chunks and metadata in PostgreSQL/pgvector when it is
reachable. Re-ingesting identical documents does not add duplicate chunks.
Select the same embedding provider and dimension for all writes to a vector
index; changing vector dimensions requires a separately managed database
migration/re-index.
