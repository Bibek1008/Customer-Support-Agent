# Key commands, one line each. Every target reads secrets from the environment
# (or a local .env loaded by your shell); none are baked into this file.

.PHONY: help install ingest serve eval threshold test lint tau-bench tau2-bench validate-datasets clean

help:
	@echo "Targets:"
	@echo "  install    Install the package and dev extras (pip install -e '.[dev,pii]')"
	@echo "  ingest     Chunk + embed approved KB documents into pgvector"
	@echo "  serve      Run the FastAPI service (POST /chat, GET /healthz)"
	@echo "  eval       Run the offline eval over the held-out ticket set"
	@echo "  threshold  Sweep confidence and pick tau* holding hallucination under target"
	@echo "  test       Run the deterministic guardrail + loop unit tests"
	@echo "  lint       ruff check"
	@echo "  tau-bench  Run the legacy tau_bench-interface adapter (needs API budget)"
	@echo "  tau2-bench Preview official tau2 test-split run (execution requires --execute)"
	@echo "  validate-datasets Check local and external dataset files"

install:
	pip install -e ".[dev,pii]"
	python -m spacy download en_core_web_lg

ingest:
	python -m support_agent.kb.ingest

serve:
	uvicorn support_agent.server:app --host 0.0.0.0 --port 8000 --reload

eval:
	python -m eval.run --suite heldout

threshold:
	python -m eval.threshold --hallucination-target 0.02 --k 8

test:
	pytest tests/

lint:
	ruff check src eval tests

tau-bench:
	python -m eval.tau_bench_adapter --domain retail

tau2-bench:
	python -m eval.tau2_bench_adapter --domain retail

validate-datasets:
	python -m eval.validate_datasets

clean:
	rm -rf eval/out eval_report.json eval_report.md threshold_curve.json
