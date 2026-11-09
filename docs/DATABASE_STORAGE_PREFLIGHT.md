# Olist database storage preflight

Updated 2026-11-09 after the explicitly approved version-3 Neon import. A fresh
read-only database measurement is **291,995,648 bytes** (278.47 MiB). The
importer report measured `olist_demo` at 281,616,384 bytes and growth from the
pre-import baseline at 281,247,744 bytes. The importer's in-transaction database
measurement was 291,799,040 bytes; the subsequent `pg_database_size` varied by
196,608 bytes. The full local estimate was 399,568,402 bytes; measured growth
was below that estimate and the 700,000,000-byte cap.

## Source measurements

All nine locally available CSVs passed schema, value, key and foreign-key
validation. Together they contain 1,547,871 rows and 126,186,995 bytes.
The field-by-field row counts, null counts and source checksums are in
[olist_preflight.json](olist_preflight.json); [OLIST_DATA_DICTIONARY.md](OLIST_DATA_DICTIONARY.md)
maps every source field to the version-3 import.

| CSV | Rows | Bytes |
|---|---:|---:|
| Categories | 71 | 2,613 |
| Customers | 99,441 | 9,033,957 |
| Products | 32,951 | 2,379,446 |
| Sellers | 3,095 | 174,703 |
| Orders | 99,441 | 17,654,914 |
| Items | 112,650 | 15,438,671 |
| Payments | 103,886 | 5,777,138 |
| Reviews | 99,224 | 14,451,670 |
| Geolocation | 1,000,163 | 61,273,883 |

## Complete import projection

The local model estimated **399,568,402 bytes (399.57 MB)** of growth,
including a 50% margin on the base relational tables and conservative allowances
for comment storage, all raw geolocation rows and the ZIP-prefix aggregate.
This estimate is below the 700 MB target by itself. It does not establish current
Neon headroom because the database size after KB ingestion and other account
usage are unknown. The importer requires a fresh baseline and aborts if projected
total exceeds 700 MB. An in-transaction actual-size check also aborts and rolls
back an overshoot; physical/WAL reclamation may lag.

| Component | Estimated bytes | Method |
|---|---:|---|
| Base tables, indexes and aliases, with 50% margin | 225,019,980 | Field-count and row-count estimate |
| Review comments, separate table | 11,479,942 | Twice UTF-8 payload plus 128 bytes per nonempty row |
| Raw geolocation | 160,026,080 | 160 bytes per source row, including row key and index allowance |
| ZIP-prefix aggregate | 3,042,400 | 160 bytes for each of 19,015 prefixes |
| **Total modeled growth** | **399,568,402** | Not measured PostgreSQL allocation |

The estimate includes 3,006,787 UTF-8 comment bytes across 42,706 nonempty rows.
Comments are imported only into `olist_demo.review_comments`, separate from
scores and dates; the customer tools, RAG and citations cannot read them. The
first-200 risk scan had no useful PII assurance: Presidio failed to initialize
under Windows application control and the regex fallback is not Portuguese
privacy validation. Any comment search, sentiment analysis or customer-facing
use remains disabled until Portuguese PII redaction and injection quarantine
are validated.

The geolocation source has 1,000,163 rows and 261,831 exact duplicate rows.
Numeric coordinate deduplication produces 720,154 unique points across 19,015
ZIP prefixes. The import preserves all raw rows with source row number and
original fields, then builds an internal aggregate from unique coordinate pairs.
ZIP prefixes are text to preserve leading zeroes. Coordinates are not exposed by
customer tools; a centroid does not identify a delivery route or address.

## Required review before import

The exact cloud effects are additive support-table migration (if needed),
additive `olist_demo` tables/columns/indexes, upserts for all nine validated
source files, separate review-comment rows, all raw geolocation rows and
aggregates, opaque historical aliases, and a version-3 completion marker. The
import completed as one transaction and did not delete support conversations,
messages, tickets or existing KB vectors. It did not re-ingest the KB or call a
hosted model. No part of the import or migration runs at app startup.

The completed migration/import used the command sequence in [OLIST_IMPLEMENTATION.md](OLIST_IMPLEMENTATION.md). Re-run it only for a separately reviewed target or replacement source snapshot.
