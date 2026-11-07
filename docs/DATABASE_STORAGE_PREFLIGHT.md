# Olist database storage preflight

Date: 2026-11-07. Source and Olist growth figures are local measurements and
estimates. Current Neon usage was measured on 2026-11-07 after explicit
approval to execute only the read-only sizing query below. No records were
selected or changed.

## Source report and included CSV sizes

Read `data/reports/olist-validation.json`. It reports no validation errors and
the requested row counts. The importer includes these eight CSV files and
550,759 source rows; it excludes the 1,000,163-row geolocation file (61,273,883
bytes). CSV sizes below are measured file sizes from the validation report.
They include original columns that the importer later discards, including
review comment text and customer/seller location fields.

| Table | Rows | CSV file | Source bytes |
|---|---:|---|---:|
| categories | 71 | `product_category_name_translation.csv` | 2,613 |
| customers | 99,441 | `olist_customers_dataset.csv` | 9,033,957 |
| products | 32,951 | `olist_products_dataset.csv` | 2,379,446 |
| sellers | 3,095 | `olist_sellers_dataset.csv` | 174,703 |
| orders | 99,441 | `olist_orders_dataset.csv` | 17,654,914 |
| items | 112,650 | `olist_order_items_dataset.csv` | 15,438,671 |
| payments | 103,886 | `olist_order_payments_dataset.csv` | 5,777,138 |
| reviews | 99,224 | `olist_order_reviews_dataset.csv` | 14,451,670 |
| **Included CSV total** | **550,759** |  | **64,913,112 (64.91 MB / 61.91 MiB)** |

I also summed UTF-8 bytes of just the selected field values while reading the
local CSVs: **54,484,223 bytes (54.48 MB / 51.96 MiB)**. This is a measured
input-value total, not a PostgreSQL storage measurement. It excludes CSV
delimiters/headers and excludes the importer-omitted fields. It still includes
selected values that PostgreSQL converts to compact timestamps/numeric types.

## Importer selection and proposed schema

`src/support_agent/olist/importer.py` currently selects exactly these fields:

| Table | Imported fields |
|---|---|
| categories | `product_category_name`, `product_category_name_english` |
| customers | `customer_id`, `customer_unique_id` |
| products | `product_id`, `product_category_name`, `product_weight_g`, `product_length_cm`, `product_height_cm`, `product_width_cm` |
| sellers | `seller_id` |
| orders | `order_id`, `customer_id`, `order_status`, `order_purchase_timestamp`, `order_approved_at`, `order_delivered_carrier_date`, `order_delivered_customer_date`, `order_estimated_delivery_date` |
| items | `order_id`, `order_item_id`, `product_id`, `seller_id`, `shipping_limit_date`, `price`, `freight_value` |
| payments | `order_id`, `payment_sequential`, `payment_type`, `payment_installments`, `payment_value` |
| reviews | importer-generated `source_row`, `review_id`, `order_id`, `review_score`, `review_creation_date`, `review_answer_timestamp` |

Review comment title/message, geolocation, postal prefixes, cities, states,
product name/description lengths, and photo counts are not inserted. The
13 products without an English category translation are retained. Current
`product_lookup` display fallback is translated English category, then the
original category code, then `not recorded`; no product row is dropped.

`src/support_agent/olist/schema.py` uses `TEXT` identifiers, `INTEGER` sequence
values, `SMALLINT` review score, `NUMERIC(12,2)` money, `NUMERIC` product
measurements, and `TIMESTAMP` source dates. Primary keys, foreign keys,
non-null constraints and checks protect IDs, prices, item sequence, and review
score. PostgreSQL automatically makes primary-key/unique columns non-null. The
explicit supporting indexes are:

- `customers(customer_unique_id)` for selected-account membership filtering;
- `orders(customer_id)` for account/order joins;
- `reviews(order_id)` for the review lookup.

Primary-key and unique constraints also create B-tree indexes: table keys,
account alias/customer uniqueness, and order/product alias-to-source-ID
uniqueness. The proposed schema additionally creates the currently unused
`olist_demo.conversation_accounts` table and its primary-key index; the live
conversation selection is already stored in `support_conversations` and this
side table has no writer/caller in the application.

## PostgreSQL storage estimate (not measured)

The 54.48 MB selected-value total is not an estimate of final database size by
itself. PostgreSQL stores tuple headers, null maps, alignment, text varlena
headers, typed numeric/timestamp values, page free space, and B-tree indexes.
The importer also creates opaque aliases for up to 99,441 orders and 32,951
products (plus 10 curated accounts). Those alias rows and their primary/unique
indexes are included in the estimate below.

| Component | Estimated storage |
|---|---:|
| Imported table heaps, including PostgreSQL row/column overhead | 75–90 MB |
| Primary, unique, and explicit supporting B-tree indexes | 35–60 MB |
| Alias tables, import metadata, and small schema overhead | 10–15 MB |
| **Estimated Olist addition** | **120–165 MB** |
| **Planning allowance used for capacity decision** | **170 MB** |

These are engineering estimates from row counts, selected value bytes, column
types and proposed indexes—not a benchmark, Neon measurement, or guarantee.
They exclude ongoing WAL/backup/branch accounting, future application growth,
and provider-specific billing/storage accounting. After `ANALYZE` and real
insertion, use `pg_database_size` and relation-size functions to replace this
range with measurements.

Let `C` be current Neon database size in decimal MB. The estimated final size is
`C + 120–165 MB`; budget using `C + 170 MB`. The importer's hard stop is
700,000,000 bytes total database size, leaving a nominal 300 MB margin under a
1,000,000,000-byte limit. Measured current usage is 9,650,176 bytes (9.65 MB /
9.20 MiB). Adding the 170,000,000-byte planning allowance gives a projected
total of **179,650,176 bytes (179.65 MB / 171.33 MiB)**. That is approximately
**520.35 MB below** the 700 MB target and **820.35 MB below** the nominal 1 GB
limit. This is a measured current database total plus an estimated Olist
increment; it does not authorize an import or guarantee exact post-import size.

## Exact read-only Neon sizing query (executed 2026-11-07)

This single `SELECT` reports total database usage and per-existing-table heap,
index, other/TOAST, and total relation sizes. It was executed after user
approval with the connection's `default_transaction_read_only` option enabled.

```sql
WITH relation_sizes AS (
    SELECT
        n.nspname AS schema_name,
        c.relname AS relation_name,
        pg_relation_size(c.oid) AS heap_bytes,
        pg_table_size(c.oid) AS table_bytes,
        pg_indexes_size(c.oid) AS index_bytes,
        pg_total_relation_size(c.oid) AS total_bytes
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'm')
      AND n.nspname <> 'information_schema'
      AND n.nspname !~ '^pg_'
)
SELECT
    'DATABASE'::text AS scope,
    current_database() AS database_name,
    NULL::text AS schema_name,
    NULL::text AS relation_name,
    pg_database_size(current_database()) AS database_bytes,
    NULL::bigint AS heap_bytes,
    NULL::bigint AS table_bytes,
    NULL::bigint AS index_bytes,
    NULL::bigint AS other_table_bytes,
    NULL::bigint AS total_relation_bytes
UNION ALL
SELECT
    'RELATION'::text,
    current_database(),
    schema_name,
    relation_name,
    NULL::bigint,
    heap_bytes,
    table_bytes,
    index_bytes,
    GREATEST(table_bytes - heap_bytes, 0),
    total_bytes
FROM relation_sizes
ORDER BY scope DESC, schema_name NULLS FIRST, relation_name NULLS FIRST;
```

`heap_bytes` is the main heap fork. `table_bytes` includes the heap and
auxiliary table storage such as TOAST/FSM/VM. `other_table_bytes` is the
difference between those values. The database total is the authoritative
comparison against the importer's 700,000,000-byte guard; relation rows are a
breakdown, not additive to the database-total row.

### Measured result

| Measurement | Bytes | Decimal MB | MiB |
|---|---:|---:|---:|
| Total database (`pg_database_size`) | 9,650,176 | 9.65 | 9.20 |
| Listed relation totals (sum of relation rows) | 1,466,368 | 1.47 | 1.40 |
| Olist planning allowance (estimate) | 170,000,000 | 170.00 | 162.12 |
| **Projected total (current measured + estimate)** | **179,650,176** | **179.65** | **171.33** |
| Headroom to 700 MB target | 520,349,824 | 520.35 | 496.15 |
| Headroom to 1 GB nominal limit | 820,349,824 | 820.35 | 782.39 |

The `neondb` relation rows returned were in `public`: `kb_chunks` (212,992
bytes), `playing_with_neon` (32,768), `support_audit` (32,768),
`support_conversations` (49,152), `support_demo_orders` (32,768),
`support_eval_runs` (499,712), `support_messages` (106,496),
`support_rate_limits` (81,920), `support_schema_versions` (24,576),
`support_sessions` (32,768), `support_ticket_replies` (32,768),
`support_tickets` (65,536), and `support_turns` (262,144). No `olist_demo`
relations were returned. The database total includes catalog and other
database-level storage not represented by this relation list.

## Columns and indexes to review for possible removal

These columns are selected and stored today but do not appear in the current
Olist tool query outputs in `src/support_agent/olist/queries.py`:

- `products.product_weight_g`, `product_length_cm`, `product_height_cm`,
  `product_width_cm` (about 0.30 MB of selected source values combined);
- `orders.order_approved_at`, `order_delivered_carrier_date` (about 3.74 MB in
  the source's text representation; PostgreSQL timestamps are smaller);
- `items.shipping_limit_date` (about 2.14 MB source text; stored as a timestamp);
- `payments.payment_installments` (about 0.11 MB source value bytes);
- `reviews.review_id` (about 3.18 MB source value bytes; `source_row` is the
  current primary key).

Removing all five groups would save only a few megabytes after type conversion
and tuple/index overhead—small beside a 700 MB cap. Keep them if future support
features need package dimensions, approval/carrier dates, shipping limit,
installments, or original review IDs; otherwise they are candidates for a
reviewed importer/schema revision. Do not alter the live schema ad hoc.

No current Olist B-tree index is clearly redundant: each explicit index supports
an account/order/review query, and each PK/unique index enforces an identifier
or alias relationship. `items(product_id)` has no index even though product
lookup joins on it; adding one may improve lookup latency at a modest storage
cost, but 112,650 rows may be acceptable for this demo. Measure query plans
before adding it. The unused `conversation_accounts` table/index can likely be
removed together after confirming compatibility; it contains no useful current
application data and is not part of the Olist row import.

## Next step and restrictions

The approved `SELECT` above was the only Neon operation performed. No migration,
import, row read, model call, paid resource creation, credential disclosure,
commit, or push occurred. Re-measure post-import usage only after separate
approval; this estimate is not a substitute for the actual post-import size.
