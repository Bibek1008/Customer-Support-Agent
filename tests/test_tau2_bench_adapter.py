"""The tau2 adapter only previews or delegates official scoring; no API calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.tau2_bench_adapter import build_command, load_test_split

_DATA_DIR = (
    Path(__file__).resolve().parents[1]
    / "external"
    / "benchmarks"
    / "tau2-bench"
    / "data"
    / "tau2"
)


@pytest.mark.parametrize(
    ("domain", "expected_count"),
    (("airline", 20), ("retail", 40), ("telecom", 40)),
)
def test_loads_only_official_test_split(domain, expected_count):
    test_ids = load_test_split(_DATA_DIR, domain)

    assert len(test_ids) == expected_count
    assert len(test_ids) == len(set(test_ids))


def test_command_uses_tau2_test_split_and_native_runner(tmp_path):
    command = build_command(
        domain="retail",
        data_dir=_DATA_DIR,
        save_to=tmp_path / "results",
        agent_llm="openai/example-agent",
        user_llm="openai/example-user",
    )

    assert command[:4] == ["tau2", "run", "--benchmark", "none"]
    assert "--task-split-name" in command
    assert command[command.index("--task-split-name") + 1] == "test"
    assert "--agent-llm" in command
    assert "--user-llm" in command
    assert "--save-to" in command


def test_banking_knowledge_refuses_implicit_test_split():
    with pytest.raises(ValueError, match="no official train/test split"):
        load_test_split(_DATA_DIR, "banking_knowledge")
