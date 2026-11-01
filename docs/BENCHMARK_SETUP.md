# Official tau2-bench setup

## Compatibility decision

The existing [`eval/tau_bench_adapter.py`](../eval/tau_bench_adapter.py) imports
the legacy `tau_bench` API (`tau_bench.envs.get_env` and
`tau_bench.run.run_pass_k`). The official repository currently declares package
`tau2` version `2.0.0`, requires Python `>=3.12,<3.14`, and uses the `tau2 run`
CLI, benchmark manifests, task split loaders, and its own reward evaluator.
These interfaces are not compatible.

The local `SupportAgentPolicy.act(conversation_id, user_message)` also cannot
implement tau2's stateful domain tool protocol without a significant agent and
environment rewrite. The separate adapter is therefore a **standalone native
tau2 runner**, not an adapter that claims to run this repository's agent. It
preserves the official task definitions and reward computation and restricts
text runs to upstream's official test split.

## Acquired data and provenance

- Official repository: <https://github.com/sierra-research/tau2-bench>
- Pinned commit: `da0835f6c67baef58bdda18f2a3b037dfb3a1754`
- Declared package version at the pinned commit: `2.0.0`
- License: MIT
- Download date: 2026-11-01
- Domains: retail, airline, telecom, and banking knowledge
- Destination: `external/benchmarks/tau2-bench/data/tau2/`
- File-level byte sizes and SHA-256 digests: `external/benchmarks/tau2-bench/download_manifest.json`

Only task, split, benchmark-manifest, policy/database, and related domain
reference data were selected. Voice task files, audio payloads and model weights
were not acquired. The full upstream `text-v1` benchmark includes 6 languages
and 50 frozen tasks per retail/airline/telecom domain. This project also
acquires those pinned task-subset manifests, but the standalone runner below
uses the explicitly defined train/test splits instead of claiming an official
multilingual leaderboard score.

Telecom has 2,285 unique records in `domains/telecom/tasks.json` (`full`), a
standard `base` set of 114 split into 74 train and 40 test, and a separate
20-task `small` set. `small` is disjoint from `base` but is already included
in `full`; these counts are alternative views and must not be added together.
The frozen `telecom_50` task subset overlaps the standard split (27 train, 23
test) and is not the runner's 40-task test set. See
[`DATASET_DOCUMENTATION.md`](./DATASET_DOCUMENTATION.md) for all domains'
task-set relationships and validation results.

The banking manifest (`banking.json`) defines the released
`voice-v2-banking` benchmark. It has 97 tasks and no train/test split. Its data
is available for validation and inspection, but this text-only runner refuses
to treat the entire banking set as a held-out test set.

## Download or reproduce the checkout

From the project root, run this Windows PowerShell command. It uses a temporary
sparse Git checkout at the pinned upstream commit, preserves upstream line
endings (needed for the frozen subset hashes), and writes a file-level manifest.
It does not change the machine-wide PowerShell execution policy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\eval\download_tau2_bench.ps1
```

To download into a separate verification directory:

```powershell
$destination = Join-Path $env:TEMP 'tau2-data-check'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\eval\download_tau2_bench.ps1 -Destination $destination
```

The benchmark payload under `external/benchmarks/tau2-bench/data/` is
git-ignored. Do not commit the downloaded data unless separately authorized.

## Install the official text runner

The data checkout intentionally does not vendor the official source or its
dependencies. Install the pinned official package in its own virtual
environment; this does not install voice extras or download models:

```powershell
uv venv --python 3.12 .\external\benchmarks\tau2-bench\.venv
.\external\benchmarks\tau2-bench\.venv\Scripts\Activate.ps1
uv pip install "git+https://github.com/sierra-research/tau2-bench.git@da0835f6c67baef58bdda18f2a3b037dfb3a1754"
```

The current official package's core dependencies include LiteLLM and standard
Python/data libraries. The optional `knowledge` extra is required for the
banking retrieval domain; voice extras are deliberately not installed for these
text test-split runs. Confirm the CLI is available:

```powershell
tau2 --help
```

No model API call is made by installation, validation, or a dry run. The
official text benchmark execution does require provider credentials; the
official runner documentation identifies `OPENAI_API_KEY` for the user
simulator and communication judge. Do not put keys in command history or
reports.

## Preview and run the test split

From the project root, with the tau2 environment activated:

```powershell
python -m eval.tau2_bench_adapter --domain retail
python -m eval.tau2_bench_adapter --domain airline
python -m eval.tau2_bench_adapter --domain telecom
```

These are dry runs by default. To execute one domain and write tau2's native
result files:

```powershell
python -m eval.tau2_bench_adapter --domain retail --execute
```

The command selects `--benchmark none` and `--task-split-name test`; tau2
executes and scores the tasks itself. Current official test split counts are
retail 40, airline 20, and telecom 40. Runs are written below
`eval/out/tau2/<domain>/test/`. Inspect results with the official viewer:

```powershell
tau2 view --file .\eval\out\tau2\retail\test
```

The default test runner does not use any train IDs. It does not expose a
training mode. Banking knowledge is accepted as a domain name only so the
adapter can provide the specific blocker: upstream provides no train/test split
and the released banking evaluation is voice-only. This checkout lacks the
voice assets, and the runner will not create a split or silently evaluate all
97 tasks as test data.

The stored τ²-bench task rewards are the original rewards from each task's
`evaluation_criteria.reward_basis`. τ²-bench computes the official task result
(including database-state, communication, and other configured criteria).
Post-hoc judges do not replace the task reward. Do not interpret these custom
English test-split runs as the released frozen `text-v1` multi-language score.

## Remaining integration work

Running this project's own policy against τ²-bench requires implementing
tau2's environment/tool-call contract for each domain and proving equivalent
database-state transitions. The current agent's tools and service model do not
implement those contracts. Until that work is designed and tested, the
standalone runner is the safe compatible integration; it must not be described
as a score for this support agent.
