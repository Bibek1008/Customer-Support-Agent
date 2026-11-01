"""Dataset integrity tests; they never call model APIs."""

from __future__ import annotations

import json

from eval.validate_datasets import _validate_tickets, validate_datasets


def test_local_and_official_datasets_validate():
    report = validate_datasets()

    assert report["status"] == "passed"
    assert report["summary"]["heldout_records"] == 12
    assert report["summary"]["knowledge_base_documents"] == 5
    assert report["summary"]["external_json_files_valid"] == report["summary"][
        "external_json_files_total"
    ]
    subsets = {
        subset["name"]: subset
        for manifest in report["external_benchmark"]["manifests"]
        for subset in manifest["task_subsets"]
    }
    assert subsets["airline_50"]["task_count"] == 50
    assert subsets["retail_50"]["sha256_valid"]
    assert subsets["telecom_50"]["task_count"] == 50
    assert subsets["banking_knowledge_97"]["task_count"] == 97
    domains = {item["domain"]: item for item in report["external_benchmark"]["domains"]}
    assert domains["airline"]["splits"]["test"]["task_count"] == 20
    assert domains["retail"]["splits"]["test"]["task_count"] == 40
    assert domains["telecom"]["splits"]["test"]["task_count"] == 40
    assert domains["banking_knowledge"]["task_count"] == 97
    assert domains["banking_knowledge"]["split_integrity"] == (
        "no official train/test split file"
    )


def test_ticket_validation_reports_duplicate_ids_and_missing_values(tmp_path):
    path = tmp_path / "duplicate.jsonl"
    row = {
        "id": "ticket-1",
        "message": "Question",
        "golden_kind": "answer",
        "expected_substrings": ["answer"],
        "golden_answer_spans": ["answer"],
    }
    path.write_text(
        json.dumps(row) + "\n" + json.dumps({**row, "message": ""}) + "\n",
        encoding="utf-8",
    )
    errors: list[str] = []

    report = _validate_tickets(path, errors)

    assert report["records"] == 2
    assert report["duplicate_ids"] == ["ticket-1"]
    assert any("message is empty" in value for value in report["missing_values"])
    assert errors
