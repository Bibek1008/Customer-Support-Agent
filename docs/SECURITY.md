# Security notes

- Browser sessions use an HTTP-only cookie and ownership checks for every
  conversation. Staff APIs use a distinct bearer key.
- Selecting an Olist account is an explicit, authenticated demo action. The
  selection is attached to an empty owned conversation; existing history cannot
  be moved between data profiles.
- Customer/order/product/seller source IDs, postal codes, locations and review
  comments are excluded from customer-facing responses. Public aliases are
  opaque and are not credentials.
- Olist SQL is fixed and parameterized. The model cannot run SQL. Olist tools
  are read-only; refunds, cancellations, shipping changes and seller contact
  are not implemented.
- Safety checks fail closed. Rate limiting and deadlines bound the public API.
- PII is redacted before model requests, persistence and traces. Presidio is
  configured with its regex recognizers and a no-op NLP engine to avoid loading
  the large spaCy NER model; a small set of local regexes remains as fallback.
- `.env`, raw data, Kaggle credentials, model cache and logs are ignored by Git.
  Never place secrets in tracked configuration.
- Public Olist data is pseudonymous, not anonymous authentication data. It is
  used only in the controlled research demo described in the UI.

Review any provider's data handling terms and rotate credentials that have been
exposed. This public demo is not intended for production-critical customer
support.
