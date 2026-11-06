"""Audit a demo trace via the official Langfuse CLI without printing credentials."""

import json
import os
import subprocess
import sys
from pathlib import Path

from support_agent.config import get_settings


def main():
    settings = get_settings()
    trace_id = sys.argv[1]
    if trace_id == "--latest-report":
        report = json.loads(Path("eval_report.json").read_text(encoding="utf-8"))
        trace_id = next(
            t["trace"]["langfuse_trace_id"]
            for t in report["per_ticket"]
            if t.get("trace", {}).get("langfuse_trace_id")
        )
    environment = dict(os.environ)
    environment.update(
        LANGFUSE_PUBLIC_KEY=settings.langfuse_public_key,
        LANGFUSE_SECRET_KEY=settings.langfuse_secret_key,
        LANGFUSE_BASE_URL=settings.langfuse_base_url,
        LANGFUSE_HOST=settings.langfuse_base_url,
    )
    result = subprocess.run(
        [
            "npx.cmd" if os.name == "nt" else "npx",
            "--yes",
            "langfuse-cli",
            "api",
            "observations",
            "list",
            "--trace-id",
            trace_id,
            "--fields",
            "core,basic,io,model,usage,metadata",
            "--limit",
            "100",
            "--json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    if result.returncode:
        print("Langfuse observation query failed. Check project credentials and availability.")
        raise SystemExit(1)
    payload = json.loads(result.stdout)
    observations = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("traceId") == trace_id and value.get("name"):
                observations.append(value)
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if not observations:
        print("No observations returned for this trace.")
        raise SystemExit(1)
    summary = [
        {
            "name": o["name"],
            "type": o.get("type"),
            "has_input": o.get("input") is not None,
            "has_output": o.get("output") is not None,
            "model": o.get("model"),
            "has_usage": bool(o.get("usageDetails")),
        }
        for o in observations
    ]
    project = observations[0].get("projectId")
    print(
        json.dumps(
            {
                "trace_id": trace_id,
                "observations": summary,
                "url": settings.langfuse_base_url.rstrip("/")
                + "/project/"
                + str(project)
                + "/traces/"
                + trace_id,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
