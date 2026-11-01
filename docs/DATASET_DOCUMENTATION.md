# Dataset documentation

This inventory was measured from the files present on 2026-11-01. The shipped
held-out sample and knowledge articles were inspected as-is; neither was
rewritten. The official benchmark inventory is based on the pinned sparse
checkout described in [`BENCHMARK_SETUP.md`](./BENCHMARK_SETUP.md).

## Local instructor project data

| Dataset filename | Type | Records | File size | Format | Purpose | Use |
|---|---|---:|---:|---|---|---|
| `eval/datasets/heldout_tickets.jsonl` | Labeled support tickets | 12 | 2,671 bytes | JSONL | Sample held-out ticket evaluation | Evaluation only |
| `eval/datasets/kb_docs/account-access.md` | Knowledge article | 1 | 831 bytes | Markdown | Password reset and account recovery policy | Evaluation retrieval corpus |
| `eval/datasets/kb_docs/billing.md` | Knowledge article | 1 | 813 bytes | Markdown | Billing, subscription cancellation and refunds | Evaluation retrieval corpus |
| `eval/datasets/kb_docs/returns-policy.md` | Knowledge article | 1 | 862 bytes | Markdown | Returns and refunds policy | Evaluation retrieval corpus |
| `eval/datasets/kb_docs/shipping.md` | Knowledge article | 1 | 779 bytes | Markdown | Shipping times, carriers and duties | Evaluation retrieval corpus |
| `eval/datasets/kb_docs/warranty.md` | Knowledge article | 1 | 797 bytes | Markdown | Product warranty and claims | Evaluation retrieval corpus |

The ticket file has 8 `answer` records and 4 `handoff` records. The record IDs
are `HT-01` through `HT-12`. The tickets are not training data. The five
Markdown articles form the sample retrieval corpus used by deterministic
retrieval tests and the original evaluation runner. None of the held-out ticket
records are passed to knowledge-base ingestion.

### Instructor ticket schema

Each nonblank JSONL line must be one JSON object with:

| Field | Type | Meaning |
|---|---|---|
| `id` | nonempty string | Unique task identifier |
| `message` | nonempty string | Customer's initial message |
| `golden_kind` | `answer` or `handoff` | Expected resolution mode |
| `expected_substrings` | string array | Required answer content for resolution scoring; empty for a handoff |
| `golden_answer_spans` | string array | Key factual spans for deterministic accuracy scoring; empty when no answer is expected |
| `customer_id` | optional string | Customer fixture identifier for local tools |

`eval.run` reads `id`, `message`, optional `customer_id`, and the golden fields.
Resolution compares `golden_kind` and `expected_substrings`; accuracy checks
`golden_answer_spans`. Blank lines are ignored, but invalid JSON, duplicate IDs,
missing required values, and invalid field types are validation errors.

## Official tau2-bench data acquired

The official payload is stored under
`external/benchmarks/tau2-bench/data/tau2/`. Its exact 851-file list, byte
sizes, and SHA-256 hashes are in the generated `download_manifest.json`. That
manifest is reproducible and is more precise than an abbreviated table of
hundreds of individual document files.

| Dataset filename or pattern | Type / records | Size | Format | Purpose | Use |
|---|---|---:|---|---|---|
| `benchmarks/text.json` | Official `text-v1` manifest; 18 language/domain cells | 3,362 bytes | JSON | Pins the released text benchmark cells and 50-task subsets | Evaluation definition |
| `benchmarks/banking.json` | Official `voice-v2-banking` manifest; 6 language cells | 1,299 bytes | JSON | Defines the banking-knowledge voice benchmark | Evaluation definition; voice run not enabled here |
| `task_subsets/airline_50.json` | 50 canonical task IDs | 932 bytes | JSON | Frozen airline subset referenced by `text.json` | Evaluation |
| `task_subsets/retail_50.json` | 50 canonical task IDs | 2,730 bytes | JSON | Frozen retail subset referenced by `text.json` | Evaluation |
| `task_subsets/telecom_50.json` | 50 canonical task IDs | 7,335 bytes | JSON | Frozen telecom subset referenced by `text.json` | Evaluation |
| `task_subsets/banking_knowledge_97.json` | 97 canonical task IDs | 2,062 bytes | JSON | Frozen banking subset referenced by `banking.json` | Evaluation; no text test split |
| `domains/airline/tasks.json` | 50 tasks | 155,528 bytes | JSON | Airline tool-agent-user tasks and reward definitions | Test evaluation only in this project's runner |
| `domains/airline/db.json` | 2,800 rows across flights/users/reservations | 7,042,725 bytes | JSON | Benchmark environment state | Evaluation environment |
| `domains/airline/policy.md` | 1 policy document | 7,676 bytes | Markdown | Airline domain rules | Evaluation environment |
| `domains/airline/split_tasks.json` | Train 30, test 20, base 50 IDs | 1,443 bytes | JSON | Official disjoint task split definitions | Test split only in this project's runner |
| `domains/retail/tasks.json` | 114 tasks | 345,982 bytes | JSON | Retail tool-agent-user tasks and reward definitions | Test evaluation only in this project's runner |
| `domains/retail/db.json` | 1,550 rows across products/users/orders | 2,811,616 bytes | JSON | Benchmark environment state | Evaluation environment |
| `domains/retail/policy.md` | 1 policy document | 6,699 bytes | Markdown | Retail domain rules | Evaluation environment |
| `domains/retail/split_tasks.json` | Train 74, test 40, base 114 IDs | 3,263 bytes | JSON | Official disjoint task split definitions | Test split only in this project's runner |
| `domains/retail/task_issues/*.json` | 3 referenced simulation/issue records | 26,303,418 bytes | JSON | Public issue annotations referenced by retail tasks | Benchmark metadata |
| `domains/telecom/tasks.json` | 2,285 unique task records (`full`) | 13,977,063 bytes | JSON | Canonical telecom task records referenced by the named task sets | Evaluation source; not a 2,285-task test split |
| `domains/telecom/tasks_small.json` | 20 task records (`small`) | 83,833 bytes | JSON | Separate small task set; IDs match `split_tasks.json` `small` | Evaluation set |
| `domains/telecom/split_tasks.json` | train 74, test 40, base 114, small 20, full 2,285 IDs | 356,149 bytes | JSON | Official train/test split and named task-set IDs | Runner selects only `test` |
| `domains/telecom/db.toml`, `user_db.toml` | 53 records across state tables | 10,561 bytes | TOML | Telecom benchmark environment state | Evaluation environment |
| `domains/telecom/*.md` | 5 policy/manual/workflow documents | 60,348 bytes | Markdown | Telecom domain policy and troubleshooting references | Evaluation environment |
| `domains/telecom/workflows/*` | 10 workflow assets | See `download_manifest.json` | DOT, PDF, PNG and Python | Official telecom workflow material | Evaluation support data |
| `domains/banking_knowledge/tasks.json` and `tasks/*.json` | 97 root tasks plus task-specific JSON records | 1,138,204 bytes for root `tasks.json`; all sizes in manifest | JSON | Banking-knowledge task set and task material | Evaluation data |
| `domains/banking_knowledge/db.json` | 34 rows across 17 state tables | 270,542 bytes | JSON | Banking-knowledge benchmark state | Evaluation environment |
| `domains/banking_knowledge/documents/**/*.json` | 698 knowledge documents | 932,122 bytes | JSON | Retrieval documents for the official knowledge domain | Evaluation/retrieval benchmark data |
| `domains/banking_knowledge/prompts/**/*` | 17 prompt/reference files | See `download_manifest.json` | JSON and Markdown | Official retrieval prompts and components | Evaluation support data |

The retail issue-file byte total is the sum of its three JSON files; the file-level
manifest remains authoritative for individual sizes and SHA-256 digests.

The acquired payload contains no `tasks_voice.json`, `audio_difficulty.json`,
voice models, or voice assets. The banking benchmark manifest is retained, but
the current official banking release is voice-only. Its 97 tasks have no
`train`/`test` split, so this project will not treat them as held-out text tasks.

### Official task/split counts

| Domain | Root `tasks.json` records | Train | Test | Other official task sets |
|---|---:|---:|---:|---|
| Airline | 50 | 30 | 20 | `base`: 50 |
| Retail | 114 | 74 | 40 | `base`: 114 |
| Telecom | 2,285 | 74 | 40 | `base`: 114; `small`: 20; `full`: 2,285 |
| Banking knowledge | 97 | Not defined | Not defined | Frozen `banking_knowledge_97` set; official release is voice-only |

Counts in the table are different views of task IDs; **do not sum root task
records, train/test IDs, named sets, or frozen subsets as if they were separate
records**. For telecom specifically:

- The root `tasks.json` has 2,285 unique records, and `full` contains those same
  2,285 task IDs.
- `train` (74) and `test` (40) are disjoint and together exactly equal `base`
  (114). This is the official standard split used by this project's runner.
- `small` has 20 task IDs, mirrored by `tasks_small.json`; it is disjoint from
  `base` but is also contained in `full`. It is not an additional 20 tasks to
  add to the root total.
- The frozen `telecom_50` manifest subset is a separate benchmark selection of
  50 IDs, overlapping the standard split with 27 train IDs and 23 test IDs. It
  is not another 50 unique telecom tasks and is not the runner's 40-task test
  split.

The airline and retail `base` sets are also exactly the union of their
disjoint train/test splits. Frozen subsets are retained and hash-checked
separately; the downloaded manifest verifies all 851 acquired file sizes and
SHA-256 hashes against the payload. The current report records task-set counts
and frozen-subset overlaps to make these distinctions visible.

Banking knowledge has 97 tasks but no official train/test split. Its official
banking manifest is voice-only; the text runner does not treat the full 97
records as a test split.

`eval.tau2_bench_adapter` selects only the official standard `test` split for
airline (20), retail (40), and telecom (40). Those are native tau2 custom text
runs over official test IDs, not the multilingual released `text-v1`
leaderboard frame.

## Evaluation and production separation

- The original `eval.run` pipeline consumes `heldout_tickets.jsonl`; it does not
  use τ²-bench task records.
- `eval.run` and `eval.threshold` accept `--dataset` and the
  `SUPPORT_HELDOUT_DATASET_PATH` setting. Keep instructor-private data outside
  the repository and keep the shipped sample unchanged.
- Production ingestion reads only approved `.md`/`.txt` documents from
  `KB_DOCS_PATH` (default `knowledge_base/approved`). The held-out JSONL is not
  an ingestion input. The sample `eval/datasets/kb_docs/` corpus is used by
  evaluation and tests; to ingest it for a local demonstration, specify it
  explicitly and use a non-production database.
- Never point production `KB_DOCS_PATH` at `eval/datasets/`, the benchmark test
  split, or any held-out/private evaluation location.

For validation commands and report details, see
[`EVALUATION_GUIDE.md`](./EVALUATION_GUIDE.md).
