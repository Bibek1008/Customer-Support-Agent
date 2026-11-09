# Security and privacy controls

The application uses an HTTP-only, same-site browser session cookie. Session tokens are stored as hashes, can be revoked, and conversation access is checked against the session owner. Chat requests carry UUID request IDs for idempotent retries. The staff inbox and staff ticket APIs require `ADMIN_API_KEY`; failed staff authentication is throttled.

Before storage, model use, or tracing, user content passes through PII redaction. Safety checks fail closed when required configuration is unavailable. Tool calls are schema-validated and allowlisted. Retrieved text is treated as untrusted input and passed through prompt-injection quarantine. Customer-facing answers are checked for evidence and relevance before release; insufficient evidence produces an abstention or staff handoff.

Logs contain route templates, status, timing, and error classes rather than request bodies or credentials. Langfuse tracing is enabled through environment configuration and uses the project's redaction path. Keep API keys, database URLs, and local `.env` values out of source control. Production configuration must use HTTPS, separate staff and service credentials, and bounded database/model concurrency.

Tickets request only a subject and issue description. Staff replies and ticket status changes remain behind staff authentication. A ticket indicates saved staff review; it does not promise a response time or resolution.
