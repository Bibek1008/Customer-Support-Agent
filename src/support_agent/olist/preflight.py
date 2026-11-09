"""Offline measurements only. Never opens a database or an inference provider."""

import argparse
import json
from pathlib import Path

from support_agent.olist.dataset import FILES, rows, validate


def base_estimates(report: dict) -> tuple[int, int, list[dict]]:
    tables = []
    for name, table in report["tables"].items():
        if name == "geolocation":
            continue
        per_row = 48 + sum(
            8 if c.endswith(("_date", "_timestamp", "_at")) else 36 if c.endswith("_id") else 12
            for c in table["import_columns"]
        )
        tables.append(
            {
                "table": name,
                "estimated_heap_bytes": table["rows"] * per_row,
                "estimated_indexes_aliases_bytes": table["rows"] * 100,
            }
        )
    return (
        sum(t["estimated_heap_bytes"] for t in tables),
        sum(t["estimated_indexes_aliases_bytes"] for t in tables),
        tables,
    )


def measure(root: Path) -> dict:
    report = validate(root)
    comments = sum(
        len((r["review_comment_title"] + r["review_comment_message"]).encode("utf-8"))
        for r in rows(root, "reviews")
    )
    comment_rows = sum(
        bool(r["review_comment_title"] or r["review_comment_message"])
        for r in rows(root, "reviews")
    )
    # Unique numeric points per ZIP prefix avoid overweighting exact duplicates.
    points = {}
    for r in rows(root, "geolocation"):
        try:
            lat, lng = float(r["geolocation_lat"]), float(r["geolocation_lng"])
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            points.setdefault(r["geolocation_zip_code_prefix"], set()).add((lat, lng))
        except ValueError:
            continue
    compact = [
        (
            z,
            round(sum(p[0] for p in ps) / len(ps), 5),
            round(sum(p[1] for p in ps) / len(ps), 5),
            len(ps),
        )
        for z, ps in points.items()
    ]
    compact_bytes = sum(len(json.dumps(r).encode()) for r in compact)
    # Planning estimates explicitly distinguish payload measurements from PG allocation.
    base, indexes, table_estimates = base_estimates(report)
    # Assess a bounded local sample without ever persisting comment text.
    from support_agent.olist.review_safety import assess_comment

    risks = []
    for r in rows(root, "reviews"):
        text = (r["review_comment_title"] + "\n" + r["review_comment_message"]).strip()
        if text:
            risks.append(assess_comment(text))
        if len(risks) >= 200:
            break
    report["review_safety_sample"] = {
        "rows": len(risks),
        "pii_flagged_rows": sum(r["pii_detected"] for r in risks),
        "instruction_flagged_rows": sum(r["instruction_attempt"] for r in risks),
        "presidio_available": all(r["presidio_available"] for r in risks),
        "publishable": False,
        "method": "First 200 nonempty comments; local redaction and quarantine, aggregate counts only. Not a Portuguese privacy validation or representative sample.",
    }
    report["storage"] = {
        "source_csv_bytes": sum((root / f).stat().st_size for f in FILES.values()),
        "review_comment_utf8_bytes": comments,
        "review_comment_rows": comment_rows,
        "review_comment_pg_estimate_bytes": comments * 2 + comment_rows * 128,
        "geolocation_zip_prefixes": len(compact),
        "geolocation_unique_points": sum(map(len, points.values())),
        "geolocation_compact_json_bytes": compact_bytes,
        "geolocation_pg_heap_estimate_bytes": len(compact) * 96,
        "geolocation_pg_index_estimate_bytes": len(compact) * 48,
        "geolocation_raw_pg_estimate_bytes": report["tables"]["geolocation"]["rows"] * 160,
        "base_heap_estimate_bytes": base,
        "base_indexes_aliases_estimate_bytes": indexes,
        "table_estimates": table_estimates,
        "planning_growth_bytes": int((base + indexes) * 1.5),
        "all_options_growth_bytes": int((base + indexes) * 1.5)
        + comments * 2
        + comment_rows * 128
        + report["tables"]["geolocation"]["rows"] * 160
        + len(compact) * 160,
        "target_bytes": 700_000_000,
        "hard_limit_bytes": 1_000_000_000,
        "method": "CSV byte/count measurements; PG heap/index estimates include tuple and alignment allowances plus 50% base margin. Actual PostgreSQL allocation, WAL and Neon usage remain unmeasured. No database contacted.",
        "decision": "Import raw comments into a separate restricted table and geolocation into auditable raw plus ZIP-prefix aggregate tables; do not expose comment text or coordinates through customer tools.",
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/raw/olist"))
    parser.add_argument("--report", type=Path, default=Path("docs/olist_preflight.json"))
    args = parser.parse_args()
    result = measure(args.data)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"errors": result["errors"], "storage": result["storage"]}, indent=2))


if __name__ == "__main__":
    main()
