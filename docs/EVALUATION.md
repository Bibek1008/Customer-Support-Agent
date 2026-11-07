# Evaluation

The existing Office Store held-out tickets and evaluation harness remain
unchanged. Olist scenarios are separate at
`eval/datasets/olist_demo_scenarios.jsonl`; they cover successful and missing
orders, unauthorized aliases, cross-customer access, multi-item orders,
payments, products, status, review scores, unsupported refund/cancellation and
live tracking requests, prompt injection, PII, database/provider failures,
ambiguity and missing evidence.

The new scenarios are currently specifications, not a scored Olist benchmark.
No LLM inference, cloud database test, full-dataset validation, Render memory
measurement or public deployment has been run under the current $0-only
authorization. Run unit tests with mocked providers. Report only scores from an
actual named evaluation run; do not infer tau2-bench compatibility from its
adapter or data files.
