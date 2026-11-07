# Database storage report

No Olist database import has been run. With explicit approval, the documented
read-only Neon query measured the pre-import database at 9,650,176 bytes
(9.20 MiB). The Olist dataset has been downloaded and locally validated, but
there are no imported Olist row counts or post-import table sizes to report.
The validation counts and estimated storage projection are in
[DATABASE_STORAGE_PREFLIGHT.md](DATABASE_STORAGE_PREFLIGHT.md). Account plan,
remaining quota, and post-import storage remain unverified.

The preflight query and result are recorded in
`DATABASE_STORAGE_PREFLIGHT.md`. Any future read-only measurement, migration,
or import against Neon requires separate approval. The importer stops if the
database exceeds 700 MB and rolls back its transaction; it does not delete
support data.

After an authorized import, record the emitted `storage_before`, per-table
measurements and `storage_after` here. Raw CSV byte size is not used as a proxy
for PostgreSQL size.
