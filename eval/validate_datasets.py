"""Validate local evaluation datasets and the downloaded official tau2 data."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from support_agent.config import get_settings

_ROOT = Path(__file__).resolve().parents[1]
_SAMPLE_KB = _ROOT / "eval" / "datasets" / "kb_docs"
_TAU2_DATA = _ROOT / "external" / "benchmarks" / "tau2-bench" / "data" / "tau2"
_REPORT_JSON = _ROOT / "eval" / "dataset_validation_report.json"
_REPORT_MD = _ROOT / "eval" / "dataset_validation_report.md"
_DOMAINS = ("retail", "airline", "telecom", "banking_knowledge")


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    return resolved if resolved.is_absolute() else root / resolved


def _check_json_files(paths: list[Path], errors: list[str]) -> int:
    valid = 0
    for path in paths:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"Invalid JSON file {path}: {exc}")
        else:
            valid += 1
    return valid


def _validate_tickets(path: Path, errors: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "format": "jsonl",
        "records": 0,
        "duplicate_ids": [],
        "missing_values": [],
        "invalid_lines": [],
        "golden_kind_counts": {},
        "size_bytes": path.stat().st_size if path.is_file() else 0,
    }
    if not path.is_file():
        errors.append(f"Missing held-out ticket dataset: {path}")
        return result

    required = ("id", "message", "golden_kind", "expected_substrings", "golden_answer_spans")
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    missing_values: list[str] = []
    kinds: dict[str, int] = {}
    with path.open(encoding="utf-8") as fh:
        for line_number, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                result["invalid_lines"].append(
                    {"line": line_number, "error": exc.msg}
                )
                continue
            if not isinstance(record, dict):
                result["invalid_lines"].append(
                    {"line": line_number, "error": "record must be a JSON object"}
                )
                continue

            result["records"] += 1
            absent = [key for key in required if key not in record]
            if absent:
                missing_values.append(f"line {line_number}: missing fields {absent}")
                continue

            ticket_id = record["id"]
            if not isinstance(ticket_id, str) or not ticket_id.strip():
                missing_values.append(f"line {line_number}: id is empty or not a string")
            elif ticket_id in seen_ids:
                duplicate_ids.add(ticket_id)
            else:
                seen_ids.add(ticket_id)

            if not isinstance(record["message"], str) or not record["message"].strip():
                missing_values.append(f"line {line_number}: message is empty or not a string")
            kind = record["golden_kind"]
            if kind not in {"answer", "handoff"}:
                missing_values.append(f"line {line_number}: golden_kind is invalid")
            else:
                kinds[kind] = kinds.get(kind, 0) + 1

            for key in ("expected_substrings", "golden_answer_spans"):
                value = record[key]
                if not isinstance(value, list) or any(
                    not isinstance(item, str) or not item.strip() for item in value
                ):
                    missing_values.append(f"line {line_number}: {key} must be a list of nonempty strings")

    result["duplicate_ids"] = sorted(duplicate_ids)
    result["missing_values"] = missing_values
    result["golden_kind_counts"] = kinds
    if result["invalid_lines"]:
        errors.append(f"{path} has {len(result['invalid_lines'])} invalid JSONL records.")
    if duplicate_ids:
        errors.append(f"{path} has duplicate task IDs: {', '.join(sorted(duplicate_ids))}")
    if missing_values:
        errors.append(f"{path} has {len(missing_values)} missing or invalid required values.")
    return result


def _validate_kb_docs(path: Path, errors: list[str]) -> dict[str, Any]:
    files = sorted([*path.rglob("*.md"), *path.rglob("*.txt")]) if path.is_dir() else []
    empty_files = [str(file) for file in files if not file.read_text(encoding="utf-8").strip()]
    if not files:
        errors.append(f"No Markdown/text knowledge-base documents found under {path}.")
    if empty_files:
        errors.append(f"Knowledge-base documents are empty: {empty_files}")
    return {
        "path": str(path),
        "exists": path.is_dir(),
        "document_count": len(files),
        "empty_files": empty_files,
        "files": [
            {"path": str(file), "size_bytes": file.stat().st_size}
            for file in files
        ],
    }


def _task_ids(tasks: Any, domain: str, errors: list[str]) -> list[str]:
    if not isinstance(tasks, list):
        errors.append(f"{domain}: tasks.json must contain a JSON array.")
        return []
    ids: list[str] = []
    required_fields = {
        "id",
        "description",
        "user_scenario",
        "initial_state",
        "evaluation_criteria",
    }
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"{domain}: task at index {index} is not an object.")
            continue
        absent = required_fields - task.keys()
        if absent:
            errors.append(
                f"{domain}: task at index {index} is missing fields {sorted(absent)}."
            )
        task_id = task.get("id")
        if task_id is None or not str(task_id).strip():
            errors.append(f"{domain}: task at index {index} has no nonempty id.")
        else:
            ids.append(str(task_id))
        if not isinstance(task.get("evaluation_criteria"), dict):
            errors.append(
                f"{domain}: task at index {index} has invalid evaluation_criteria."
            )
    if len(ids) != len(set(ids)):
        errors.append(f"{domain}: tasks.json contains duplicate task identifiers.")
    return ids


def _validate_domain(
    domain: str,
    data_root: Path,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    folder = data_root / "domains" / domain
    tasks_path = folder / "tasks.json"
    result: dict[str, Any] = {
        "domain": domain,
        "exists": folder.is_dir(),
        "tasks_file": str(tasks_path),
        "task_count": 0,
        "splits": {},
        "task_sets": {},
        "split_integrity": None,
    }
    if not folder.is_dir() or not tasks_path.is_file():
        errors.append(f"{domain}: required domain directory or tasks.json is missing.")
        return result
    required_files = (
        ("db.json", "documents")
        if domain == "banking_knowledge"
        else ("db.toml", "user_db.toml", "main_policy.md")
        if domain == "telecom"
        else ("db.json", "policy.md")
    )
    for required_file in required_files:
        if not (folder / required_file).exists():
            errors.append(f"{domain}: required official file {required_file} is missing.")
    if domain == "banking_knowledge":
        documents_dir = folder / "documents"
        document_count = (
            sum(1 for path in documents_dir.rglob("*.json") if path.is_file())
            if documents_dir.is_dir()
            else 0
        )
        result["knowledge_documents"] = document_count
        if document_count == 0:
            errors.append("banking_knowledge: required document corpus is unavailable.")
    if domain != "banking_knowledge" and not (folder / "split_tasks.json").is_file():
        errors.append(f"{domain}: required official split_tasks.json is missing.")

    try:
        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{domain}: invalid tasks.json: {exc}")
        return result

    ids = _task_ids(tasks, domain, errors)
    result["task_count"] = len(ids)
    id_set = set(ids)
    split_path = folder / "split_tasks.json"
    if not split_path.is_file():
        result["split_integrity"] = "no official train/test split file"
        warnings.append(
            f"{domain}: no split_tasks.json; the available task set must not be described as a test split."
        )
        return result

    try:
        splits = json.loads(split_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{domain}: invalid split_tasks.json: {exc}")
        result["split_integrity"] = "invalid"
        return result
    if not isinstance(splits, dict):
        errors.append(f"{domain}: split_tasks.json must contain a JSON object.")
        result["split_integrity"] = "invalid"
        return result

    normalized: dict[str, list[str]] = {}
    for name, split_ids in splits.items():
        if not isinstance(split_ids, list):
            errors.append(f"{domain}: split {name!r} is not a JSON array.")
            continue
        split_ids = [str(item) for item in split_ids]
        normalized[name] = split_ids
        duplicates = len(split_ids) - len(set(split_ids))
        missing_ids = sorted(set(split_ids) - id_set)
        result["splits"][name] = {
            "task_count": len(split_ids),
            "duplicate_count": duplicates,
            "unknown_task_ids": missing_ids,
        }
        if duplicates:
            errors.append(f"{domain}: split {name!r} contains duplicate task identifiers.")
        if missing_ids:
            errors.append(f"{domain}: split {name!r} references unknown tasks.")

    if "train" in normalized and "test" in normalized:
        overlap = sorted(set(normalized["train"]) & set(normalized["test"]))
        result["train_test_overlap"] = overlap
        if overlap:
            errors.append(f"{domain}: train/test splits overlap on {len(overlap)} task IDs.")
        result["split_integrity"] = "valid" if not overlap else "overlap"
        if "base" in normalized:
            matches_base = (
                set(normalized["train"]) | set(normalized["test"])
            ) == set(normalized["base"])
            result["train_test_union_matches_base"] = matches_base
            if not matches_base:
                errors.append(
                    f"{domain}: train/test IDs do not exactly partition the base task set."
                )
    else:
        result["split_integrity"] = "train/test split unavailable"
        warnings.append(f"{domain}: split file does not define both train and test.")

    variant_names = ("base", "small", "full")
    result["task_sets"] = {
        name: len(normalized[name]) for name in variant_names if name in normalized
    }
    if "full" in normalized and set(normalized["full"]) != id_set:
        errors.append(f"{domain}: full task set does not match tasks.json.")
        result["full_task_set_matches_tasks_file"] = False
    elif "full" in normalized:
        result["full_task_set_matches_tasks_file"] = True

    if domain == "telecom" and "small" in normalized:
        small_path = folder / "tasks_small.json"
        if not small_path.is_file():
            errors.append("telecom: tasks_small.json is missing.")
            result["small_task_file_matches_split"] = False
        else:
            try:
                small_tasks = json.loads(small_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"telecom: invalid tasks_small.json: {exc}")
                result["small_task_file_matches_split"] = False
            else:
                small_ids = _task_ids(small_tasks, "telecom tasks_small.json", errors)
                result["small_task_file_matches_split"] = (
                    len(small_ids) == len(normalized["small"])
                    and set(small_ids) == set(normalized["small"])
                )
                if not result["small_task_file_matches_split"]:
                    errors.append(
                        "telecom: tasks_small.json does not match the official small task set."
                    )
                result["small_task_set_overlap_with_base"] = len(
                    set(normalized["small"]) & set(normalized.get("base", []))
                )
    return result


def _validate_download_manifest(
    benchmark_data: Path,
    errors: list[str],
) -> dict[str, Any]:
    """Verify every downloaded payload file against the downloader's manifest."""
    benchmark_root = benchmark_data.parent.parent
    manifest_path = benchmark_root / "download_manifest.json"
    result: dict[str, Any] = {
        "path": str(manifest_path),
        "exists": manifest_path.is_file(),
        "entry_count": 0,
        "verified_count": 0,
        "missing_files": [],
        "unexpected_files": [],
        "invalid_entries": [],
        "size_mismatches": [],
        "sha256_mismatches": [],
        "provenance": {},
    }
    if not manifest_path.is_file():
        errors.append(f"Missing tau2 download manifest: {manifest_path}")
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"Invalid tau2 download manifest {manifest_path}: {exc}")
        return result
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        errors.append(f"Invalid files list in tau2 download manifest {manifest_path}.")
        return result

    provenance_path = benchmark_root / "PROVENANCE.json"
    if not provenance_path.is_file():
        errors.append(f"Missing tau2 provenance file: {provenance_path}")
    else:
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"Invalid tau2 provenance file {provenance_path}: {exc}")
        else:
            if not isinstance(provenance, dict):
                errors.append(f"Invalid tau2 provenance format in {provenance_path}.")
            else:
                result["provenance"] = {
                    key: provenance.get(key)
                    for key in ("repository", "commit", "license", "domains_acquired")
                }
                comparisons = (
                    ("repository", "repository"),
                    ("commit", "commit"),
                    ("license", "license"),
                )
                for provenance_key, manifest_key in comparisons:
                    if provenance.get(provenance_key) != manifest.get(manifest_key):
                        errors.append(
                            f"Tau2 provenance {provenance_key} does not match the download manifest."
                        )
                provenance_domains = provenance.get("domains_acquired")
                manifest_domains = manifest.get("domains")
                if not isinstance(provenance_domains, list) or not isinstance(
                    manifest_domains, list
                ):
                    errors.append("Tau2 provenance or manifest domains are invalid.")
                elif sorted(provenance_domains) != sorted(manifest_domains):
                    errors.append(
                        "Tau2 provenance domains do not match the download manifest."
                    )

    result["entry_count"] = len(entries)
    declared_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            result["invalid_entries"].append(str(entry))
            continue
        relative_name = entry.get("path")
        size = entry.get("size_bytes")
        expected_hash = entry.get("sha256")
        if (
            not isinstance(relative_name, str)
            or not relative_name
            or not isinstance(size, int)
            or not isinstance(expected_hash, str)
        ):
            result["invalid_entries"].append(str(relative_name))
            continue
        relative_path = Path(*relative_name.replace("\\", "/").split("/"))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            result["invalid_entries"].append(relative_name)
            continue
        normalized_name = relative_path.as_posix()
        if normalized_name in declared_paths:
            result["invalid_entries"].append(relative_name)
            continue
        declared_paths.add(normalized_name)
        payload_path = benchmark_data / relative_path
        if not payload_path.is_file():
            result["missing_files"].append(normalized_name)
            continue
        payload_size = payload_path.stat().st_size
        if payload_size != size:
            result["size_mismatches"].append(normalized_name)
            continue
        digest = hashlib.sha256(payload_path.read_bytes()).hexdigest()
        if digest != expected_hash.lower():
            result["sha256_mismatches"].append(normalized_name)
            continue
        result["verified_count"] += 1

    actual_paths = {
        path.relative_to(benchmark_data).as_posix()
        for path in benchmark_data.rglob("*")
        if path.is_file()
    }
    result["unexpected_files"] = sorted(actual_paths - declared_paths)
    if result["invalid_entries"]:
        errors.append(
            f"Tau2 download manifest contains {len(result['invalid_entries'])} invalid entries."
        )
    for field, label in (
        ("missing_files", "missing"),
        ("unexpected_files", "unexpected"),
        ("size_mismatches", "size-mismatched"),
        ("sha256_mismatches", "SHA-256-mismatched"),
    ):
        if result[field]:
            errors.append(
                f"Tau2 download manifest has {len(result[field])} {label} payload files."
            )
    return result


def validate_datasets(
    root: str | Path = _ROOT,
    heldout_path: str | Path | None = None,
    kb_docs_path: str | Path | None = None,
    tau2_data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return a machine-readable validation result without changing source data."""
    project_root = Path(root).resolve()
    settings = get_settings()
    heldout = _resolve_path(
        heldout_path or settings.heldout_dataset_path,
        project_root,
    )
    kb_docs = _resolve_path(kb_docs_path or _SAMPLE_KB, project_root)
    benchmark_data = _resolve_path(tau2_data_dir or _TAU2_DATA, project_root)
    errors: list[str] = []
    warnings: list[str] = []
    ticket_data = _validate_tickets(heldout, errors)
    kb_data = _validate_kb_docs(kb_docs, errors)

    json_files = sorted(benchmark_data.rglob("*.json")) if benchmark_data.is_dir() else []
    valid_json_count = _check_json_files(json_files, errors)
    download_manifest = _validate_download_manifest(benchmark_data, errors)
    domains = [
        _validate_domain(domain, benchmark_data, errors, warnings)
        for domain in _DOMAINS
    ]
    manifest_paths = [
        benchmark_data / "benchmarks" / "text.json",
        benchmark_data / "benchmarks" / "banking.json",
    ]
    manifest_results = []
    for path in manifest_paths:
        exists = path.is_file()
        if not exists:
            errors.append(f"Missing official benchmark manifest: {path}")
            manifest_results.append({"path": str(path), "exists": False})
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"Invalid benchmark manifest {path}: {exc}")
            manifest_results.append({"path": str(path), "exists": True, "valid": False})
            continue
        manifest_results.append(
            {
                "path": str(path),
                "exists": True,
                "valid": isinstance(manifest, dict),
                "benchmark_version": manifest.get("benchmark_version")
                if isinstance(manifest, dict)
                else None,
                "domains": sorted(manifest.get("task_subsets", {}))
                if isinstance(manifest, dict)
                else [],
                "task_subsets": [],
            }
        )
        task_subsets = manifest.get("task_subsets", {})
        if not isinstance(task_subsets, dict):
            errors.append(f"Invalid task_subsets field in manifest {path}.")
            continue
        for domain, subset_info in task_subsets.items():
            if not isinstance(subset_info, dict):
                errors.append(f"Invalid task subset entry for {domain} in {path}.")
                continue
            subset_name = subset_info.get("name")
            expected_hash = subset_info.get("sha256")
            subset_path = (
                benchmark_data / "task_subsets" / f"{subset_name}.json"
                if isinstance(subset_name, str)
                else benchmark_data / "task_subsets" / "invalid.json"
            )
            subset_result: dict[str, Any] = {
                "domain": domain,
                "name": subset_name,
                "path": str(subset_path),
                "task_count": 0,
                "sha256_valid": False,
            }
            if not subset_path.is_file():
                errors.append(f"Missing official task subset: {subset_path}")
            else:
                payload = subset_path.read_bytes()
                actual_hash = hashlib.sha256(payload).hexdigest()
                subset_result["sha256_valid"] = actual_hash == expected_hash
                if not subset_result["sha256_valid"]:
                    errors.append(f"Official task subset hash mismatch: {subset_path}")
                try:
                    subset = json.loads(payload)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    errors.append(f"Invalid task subset JSON {subset_path}: {exc}")
                else:
                    task_ids = subset.get("task_ids") if isinstance(subset, dict) else None
                    if not isinstance(task_ids, list) or not all(
                        isinstance(task_id, str) and task_id for task_id in task_ids
                    ):
                        errors.append(f"Invalid task_ids in official subset {subset_path}.")
                    else:
                        subset_result["task_count"] = len(task_ids)
                        if len(task_ids) != len(set(task_ids)):
                            errors.append(f"Duplicate task IDs in official subset {subset_path}.")
                        domain_tasks_path = benchmark_data / "domains" / domain / "tasks.json"
                        if domain_tasks_path.is_file():
                            domain_tasks = json.loads(
                                domain_tasks_path.read_text(encoding="utf-8")
                            )
                            domain_ids = {
                                str(task.get("id"))
                                for task in domain_tasks
                                if isinstance(task, dict)
                            }
                            if set(task_ids) - domain_ids:
                                errors.append(
                                    f"Official subset {subset_path} references unknown domain task IDs."
                                )
                            split_path = benchmark_data / "domains" / domain / "split_tasks.json"
                            if split_path.is_file():
                                split_data = json.loads(
                                    split_path.read_text(encoding="utf-8")
                                )
                                subset_result["overlap_with_splits"] = {
                                    split_name: len(set(task_ids) & set(split_ids))
                                    for split_name, split_ids in split_data.items()
                                    if isinstance(split_ids, list)
                                    and split_name in {"train", "test", "base"}
                                }
            manifest_results[-1]["task_subsets"].append(subset_result)

    all_files = (
        [file for file in benchmark_data.rglob("*") if file.is_file()]
        if benchmark_data.is_dir()
        else []
    )
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if not errors else "failed",
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "heldout_records": ticket_data["records"],
            "knowledge_base_documents": kb_data["document_count"],
            "external_data_files": len(all_files),
            "external_data_bytes": sum(file.stat().st_size for file in all_files),
            "external_json_files_valid": valid_json_count,
            "external_json_files_total": len(json_files),
            "download_manifest_files_verified": download_manifest["verified_count"],
        },
        "heldout_dataset": ticket_data,
        "knowledge_base_documents": kb_data,
        "external_benchmark": {
            "data_dir": str(benchmark_data),
            "available": benchmark_data.is_dir(),
            "files": [
                {"path": str(file.relative_to(benchmark_data)), "size_bytes": file.stat().st_size}
                for file in all_files
            ],
            "manifests": manifest_results,
            "domains": domains,
            "download_manifest": download_manifest,
        },
        "errors": errors,
        "warnings": warnings,
    }
    return report


def write_reports(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Dataset validation report",
        "",
        f"- **Status:** {report['status']}",
        f"- **Generated:** {report['generated_at']}",
        f"- **Held-out records:** {report['summary']['heldout_records']}",
        f"- **Knowledge-base documents:** {report['summary']['knowledge_base_documents']}",
        (
            f"- **External files:** {report['summary']['external_data_files']} "
            f"({report['summary']['external_data_bytes']:,} bytes)"
        ),
        (
            f"- **Valid external JSON files:** "
            f"{report['summary']['external_json_files_valid']}/"
            f"{report['summary']['external_json_files_total']}"
        ),
        (
            f"- **Verified downloaded files:** "
            f"{report['external_benchmark']['download_manifest']['verified_count']}/"
            f"{report['external_benchmark']['download_manifest']['entry_count']} "
            "(size and SHA-256)"
        ),
        "",
        "## Domain task and split counts",
        "",
        "| Domain | Root task records | Train | Test | Other official sets | Split integrity |",
        "|---|---:|---:|---:|---|---|",
    ]
    for domain in report["external_benchmark"]["domains"]:
        splits = domain["splits"]
        train = splits.get("train", {}).get("task_count", "n/a")
        test = splits.get("test", {}).get("task_count", "n/a")
        task_sets = ", ".join(
            f"{name}: {count}"
            for name, count in domain.get("task_sets", {}).items()
        ) or "none"
        lines.append(
            f"| {domain['domain']} | {domain['task_count']} | {train} | {test} "
            f"| {task_sets} | {domain['split_integrity']} |"
        )
    lines.extend(
        [
            "",
            (
                "Root `tasks.json` counts, split IDs, named task sets, and frozen benchmark "
                "subsets are alternate views of task IDs; do not add their counts together."
            ),
            "",
            "## Frozen benchmark task subsets",
            "",
            "| Domain | Subset | IDs | Train overlap | Test overlap |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for manifest in report["external_benchmark"]["manifests"]:
        for subset in manifest.get("task_subsets", []):
            overlap = subset.get("overlap_with_splits", {})
            lines.append(
                f"| {subset['domain']} | {subset['name']} | {subset['task_count']} "
                f"| {overlap.get('train', 'n/a')} | {overlap.get('test', 'n/a')} |"
            )
    lines.extend(["", "## Errors", ""])
    lines.extend([f"- {error}" for error in report["errors"]] or ["- None."])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in report["warnings"]] or ["- None."])
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate local and tau2 benchmark datasets.")
    parser.add_argument("--heldout", default=None, help="Override the held-out JSONL path")
    parser.add_argument("--kb-docs", default=None, help="Knowledge-base document directory")
    parser.add_argument("--tau2-data", default=None, help="Official tau2 data/tau2 directory")
    parser.add_argument("--json-report", default=str(_REPORT_JSON))
    parser.add_argument("--markdown-report", default=str(_REPORT_MD))
    args = parser.parse_args()

    report = validate_datasets(
        heldout_path=args.heldout,
        kb_docs_path=args.kb_docs,
        tau2_data_dir=args.tau2_data,
    )
    write_reports(report, Path(args.json_report), Path(args.markdown_report))
    print(
        f"Dataset validation {report['status']}: "
        f"{report['summary']['errors']} errors, {report['summary']['warnings']} warnings."
    )
    print(f"Reports: {args.json_report} and {args.markdown_report}")
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
