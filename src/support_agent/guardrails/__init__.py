"""The guardrail stack: PII redaction, safety and refusal, injection quarantine.

These run on every step, not just at the edges. Input is redacted before the
model or the logs see it; tool output is treated as untrusted and sanitized
before the model reads it; the safety classifier scores both the input prompt
and the model response; the refusal policy decides out-of-scope, disallowed, and
low-confidence paths.
"""
