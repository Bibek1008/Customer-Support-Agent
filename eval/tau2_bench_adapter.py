"""Standalone runner for the current official ``tau2`` CLI.

The local support agent's policy/tool interface is not compatible with tau2.
This runner therefore delegates execution and scoring to tau2 itself, selecting
only the official test split for supported text domains.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DATA_ROOT = _ROOT / "external" / "benchmarks" / "tau2-bench"
_DATA_DIR = _DATA_ROOT / "data" / "tau2"
_RESULTS = _ROOT / "eval" / "out" / "tau2"
_TEXT_DOMAINS = ("retail", "airline", "telecom")
_SUPPORTED_DOMAINS = (*_TEXT_DOMAINS, "banking_knowledge")


def _data_dir(path: str | Path | None = None) -> Path:
    configured = path or os.environ.get("TAU2_DATA_DIR")
    return Path(configured).resolve() if configured else _DATA_DIR


def load_test_split(data_dir: str | Path, domain: str) -> list[str]:
    """Return official test task IDs after checking their split integrity."""
    if domain not in _TEXT_DOMAINS:
        if domain == "banking_knowledge":
            raise ValueError(
                "banking_knowledge has no official train/test split and its released "
                "banking benchmark is voice-only; this text test runner will not "
                "treat the full task set as held out."
            )
        raise ValueError(f"Unsupported text domain: {domain}")

    domain_dir = Path(data_dir) / "domains" / domain
    tasks_path = domain_dir / "tasks.json"
    split_path = domain_dir / "split_tasks.json"
    for path in (tasks_path, split_path):
        if not path.is_file():
            raise FileNotFoundError(f"Missing official tau2 dataset file: {path}")

    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    splits = json.loads(split_path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list) or not isinstance(splits, dict):
        raise TypeError(f"Invalid official tau2 task/split format for {domain}.")

    task_ids = [str(task.get("id", "")) for task in tasks if isinstance(task, dict)]
    if len(task_ids) != len(tasks) or any(not task_id for task_id in task_ids):
        raise ValueError(f"Malformed task identifiers in {tasks_path}.")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError(f"Duplicate task identifiers in {tasks_path}.")

    train_ids = splits.get("train")
    test_ids = splits.get("test")
    if not isinstance(train_ids, list) or not isinstance(test_ids, list) or not test_ids:
        raise ValueError(f"{split_path} must define nonempty train and test splits.")
    train_ids = [str(task_id) for task_id in train_ids]
    test_ids = [str(task_id) for task_id in test_ids]
    if len(train_ids) != len(set(train_ids)) or len(test_ids) != len(set(test_ids)):
        raise ValueError(f"{split_path} contains duplicate train or test task IDs.")
    if set(train_ids) & set(test_ids):
        raise ValueError(f"{split_path} train and test splits overlap.")
    unknown_ids = (set(train_ids) | set(test_ids)) - set(task_ids)
    if unknown_ids:
        raise ValueError(f"{split_path} refers to task IDs absent from tasks.json.")
    return test_ids


def build_command(
    domain: str,
    data_dir: str | Path,
    save_to: str | Path,
    agent_llm: str,
    user_llm: str,
) -> list[str]:
    """Build the official CLI command with the official test split selected."""
    load_test_split(data_dir, domain)
    return [
        "tau2",
        "run",
        "--benchmark",
        "none",
        "--domain",
        domain,
        "--task-split-name",
        "test",
        "--agent-llm",
        agent_llm,
        "--user-llm",
        user_llm,
        "--save-to",
        str(Path(save_to).resolve()),
    ]


def run(
    domain: str,
    execute: bool = False,
    data_dir: str | Path | None = None,
    agent_llm: str | None = None,
    user_llm: str | None = None,
) -> Path:
    selected_data = _data_dir(data_dir)
    test_ids = load_test_split(selected_data, domain)
    agent_model = agent_llm or os.environ.get("TAU2_AGENT_LLM", "openai/gpt-4.1-2025-04-14")
    user_model = user_llm or os.environ.get("TAU2_USER_LLM", "openai/gpt-4.1-2025-04-14")
    result_dir = _RESULTS / domain / "test"
    command = build_command(
        domain=domain,
        data_dir=selected_data,
        save_to=result_dir,
        agent_llm=agent_model,
        user_llm=user_model,
    )

    print(
        f"Official tau2 test split: {domain} ({len(test_ids)} tasks). "
        "The original tau2 task rewards are preserved."
    )
    working_dir = selected_data.parents[1]
    print(f"Working directory: {working_dir}")
    print(f"Results directory: {result_dir}")
    print("Command: " + shlex.join(command))
    if not execute:
        print("Dry run only. Add --execute to make paid model/judge calls.")
        return result_dir

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is missing. The official text runner's user simulator "
            "and communication judge require credentials. No benchmark calls were made."
        )
    executable = os.environ.get("TAU2_EXECUTABLE") or shutil.which("tau2")
    if not executable:
        raise SystemExit(
            "The official tau2 CLI is not installed or not on PATH. Install the "
            "pinned official package as documented in docs/BENCHMARK_SETUP.md. "
            "No benchmark calls were made."
        )

    command[0] = executable
    result_dir.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, cwd=working_dir, check=False)
    if completed.returncode:
        raise SystemExit(f"tau2 exited with status {completed.returncode}.")
    print(f"tau2 completed. Inspect its native result files under {result_dir}.")
    return result_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview or run official tau2 test-split evaluations."
    )
    parser.add_argument("--domain", choices=_SUPPORTED_DOMAINS, default="retail")
    parser.add_argument("--data-dir", default=None, help="Path to official data/tau2")
    parser.add_argument("--agent-llm", default=None)
    parser.add_argument("--user-llm", default=None)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute tau2 and make model/judge API calls; default only previews.",
    )
    args = parser.parse_args()
    try:
        run(
            domain=args.domain,
            execute=args.execute,
            data_dir=args.data_dir,
            agent_llm=args.agent_llm,
            user_llm=args.user_llm,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
