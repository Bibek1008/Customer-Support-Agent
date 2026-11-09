# Olist data dictionary and coverage

Measured locally on 2026-11-09. All nine source CSVs were inspected. No database import ran.

All source columns are mapped to relational tables. Review comments are stored separately from review scores. Geolocation raw rows remain auditable and the ZIP-prefix table is deduplicated. SQL facts and reviews never enter the policy vector store. Customer tools remain account-scoped. No current prices, names, live inventory, tracking numbers, official company terms or support transcripts are present.

| Dataset | Rows | Source bytes | Exact duplicate rows | Selected columns |
|---|---:|---:|---:|---:|
| categories | 71 | 2,613 | 0 | 2/2 |
| customers | 99,441 | 9,033,957 | 0 | 5/5 |
| products | 32,951 | 2,379,446 | 0 | 9/9 |
| sellers | 3,095 | 174,703 | 0 | 4/4 |
| orders | 99,441 | 17,654,914 | 0 | 8/8 |
| items | 112,650 | 15,438,671 | 0 | 7/7 |
| payments | 103,886 | 5,777,138 | 0 | 5/5 |
| reviews | 99,224 | 14,451,670 | 0 | 7/7 |
| geolocation | 1,000,163 | 61,273,883 | 261,831 | 5/5 |

Validation errors: []

Products without category translation: 13

All source fields map to the explicit version-3 import; this local report does not mean rows are already in Neon. Internal IDs are retained only for joins and authorization. Original CSV spelling `lenght` is preserved. Review comments use separate untrusted storage; geolocation raw rows and ZIP-prefix aggregates are retained.

## categories

Source: `product_category_name_translation.csv`. SHA-256: `a81f0d1f27b27e7293f761bc79e3ce8f348ee39c4b3ed3e49bde38f478586278`.

| Field | Value type | Empty rows | Coverage and meaning |
|---|---|---:|---|
| `product_category_name` | text | 0 | Prepared SQL column. Original Portuguese category code; untranslated values retained. |
| `product_category_name_english` | text | 0 | Prepared SQL column. Readable English category translation; incomplete source coverage. |

## customers

Source: `olist_customers_dataset.csv`. SHA-256: `983a422239e1712ded753b3bf9ecf47dc73f144d306029dcfa99e70a226883d2`.

| Field | Value type | Empty rows | Coverage and meaning |
|---|---|---:|---|
| `customer_id` | text | 0 | Prepared SQL column. Internal per-order customer join key; never displayed. |
| `customer_unique_id` | text | 0 | Prepared SQL column. Internal customer identity across purchases; mapped to curated demo accounts. |
| `customer_zip_code_prefix` | numeric | 0 | Prepared SQL column. Source postal prefix retained as text to preserve leading zeroes; not shown in customer output. |
| `customer_city` | text | 0 | Prepared SQL column. Source customer city retained for authorized regional analytics; not shown in customer output. |
| `customer_state` | text | 0 | Prepared SQL column. Source customer state retained for authorized regional analytics; not shown in customer output. |

## products

Source: `olist_products_dataset.csv`. SHA-256: `3e6569628a17fbc75fd206ee357b59e20364b9afa90f5b6cd5b4d624c58aa9cc`.

| Field | Value type | Empty rows | Coverage and meaning |
|---|---|---:|---|
| `product_id` | text | 0 | Prepared SQL column. Internal product join key; replaced by opaque demo-product reference. |
| `product_category_name` | text | 610 | Prepared SQL column. Original Portuguese category code; untranslated values retained. |
| `product_name_lenght` | numeric | 610 | Prepared SQL column. Source-spelled name-length statistic; actual product names are unavailable. |
| `product_description_lenght` | numeric | 610 | Prepared SQL column. Source-spelled description-length statistic; no actual description text. |
| `product_photos_qty` | numeric | 610 | Prepared SQL column. Recorded count of product photos; no images or image URLs. |
| `product_weight_g` | numeric | 2 | Prepared SQL column. Recorded product weight in grams; nullable. |
| `product_length_cm` | numeric | 2 | Prepared SQL column. Recorded product length in centimeters; nullable. |
| `product_height_cm` | numeric | 2 | Prepared SQL column. Recorded product height in centimeters; nullable. |
| `product_width_cm` | numeric | 2 | Prepared SQL column. Recorded product width in centimeters; nullable. |

## sellers

Source: `olist_sellers_dataset.csv`. SHA-256: `1f643d2b950373b85735e7794b20986f528d7a000432e7c6f9bcbb44d0846a0e`.

| Field | Value type | Empty rows | Coverage and meaning |
|---|---|---:|---|
| `seller_id` | text | 0 | Prepared SQL column. Internal seller join key; replaced by opaque demo-seller reference. |
| `seller_zip_code_prefix` | numeric | 0 | Prepared SQL column. Source postal prefix retained as text to preserve leading zeroes; not shown in public output. |
| `seller_city` | text | 0 | Prepared SQL column. Source seller city retained for authorized regional analytics; not shown in public output. |
| `seller_state` | text | 0 | Prepared SQL column. Seller Brazilian state code; broad region only, no contact information. |

## orders

Source: `olist_orders_dataset.csv`. SHA-256: `8df58ef3d2d7e9944010f7beecd9b75367f5588ec6e3c91cec19ae3345ef9ecf`.

| Field | Value type | Empty rows | Coverage and meaning |
|---|---|---:|---|
| `order_id` | text | 0 | Prepared SQL column. Internal order join key; replaced by opaque demo-order reference in output. |
| `customer_id` | text | 0 | Prepared SQL column. Internal per-order customer join key; never displayed. |
| `order_status` | text | 0 | Prepared SQL column. Recorded historical lifecycle status, including delivered/canceled/unavailable; never live tracking. |
| `order_purchase_timestamp` | timestamp without timezone | 0 | Prepared SQL column. Recorded purchase time; also used for order history and purchase frequency. |
| `order_approved_at` | timestamp without timezone | 160 | Prepared SQL column. Recorded payment approval time; nullable. |
| `order_delivered_carrier_date` | timestamp without timezone | 1,783 | Prepared SQL column. Recorded carrier handover time; nullable. |
| `order_delivered_customer_date` | timestamp without timezone | 2,965 | Prepared SQL column. Recorded customer delivery time; nullable; used for date difference. |
| `order_estimated_delivery_date` | timestamp without timezone | 0 | Prepared SQL column. Historical estimated delivery time; nullable; not a current promise. |

## items

Source: `olist_order_items_dataset.csv`. SHA-256: `0bc4d068c4fe38cbb01bd90e8746e3c613fe7b4baef75fab7b0e329701c3e279`.

| Field | Value type | Empty rows | Coverage and meaning |
|---|---|---:|---|
| `order_id` | text | 0 | Prepared SQL column. Internal order join key; replaced by opaque demo-order reference in output. |
| `order_item_id` | numeric | 0 | Prepared SQL column. Item sequence within an order; composite key permits multiple item lines. |
| `product_id` | text | 0 | Prepared SQL column. Internal product join key; replaced by opaque demo-product reference. |
| `seller_id` | text | 0 | Prepared SQL column. Internal seller join key; replaced by opaque demo-seller reference. |
| `shipping_limit_date` | timestamp without timezone | 0 | Prepared SQL column. Recorded seller shipping deadline; not a current shipping promise. |
| `price` | numeric | 0 | Prepared SQL column. Historical item price in BRL; multiple lines preserved; no live catalog price. |
| `freight_value` | numeric | 0 | Prepared SQL column. Historical freight charge per item in BRL; separate from item price. |

## payments

Source: `olist_order_payments_dataset.csv`. SHA-256: `4f713964f2815dbbaa40b9488268c55aac3627bfce5aa96cf58d1f3616de3cc0`.

| Field | Value type | Empty rows | Coverage and meaning |
|---|---|---:|---|
| `order_id` | text | 0 | Prepared SQL column. Internal order join key; replaced by opaque demo-order reference in output. |
| `payment_sequential` | numeric | 0 | Prepared SQL column. Payment-entry sequence; multiple entries remain separate. |
| `payment_type` | text | 0 | Prepared SQL column. Recorded payment method, including credit card, boleto and voucher. |
| `payment_installments` | numeric | 0 | Prepared SQL column. Recorded installment count; no installment due-date schedule exists. |
| `payment_value` | numeric | 0 | Prepared SQL column. Recorded payment-entry amount in BRL; not a live charge or refund ledger. |

## reviews

Source: `olist_order_reviews_dataset.csv`. SHA-256: `012b61c7593e34f51fa614efdf802b9c7056ce6aae5307ddb93236e7cfc797d7`.

| Field | Value type | Empty rows | Coverage and meaning |
|---|---|---:|---|
| `review_id` | text | 0 | Prepared SQL column. Source review identifier; not unique per source row; never displayed. |
| `order_id` | text | 0 | Prepared SQL column. Internal order join key; replaced by opaque demo-order reference in output. |
| `review_score` | numeric | 0 | Prepared SQL column. Historical post-purchase score from 1 to 5; feedback, not policy. |
| `review_comment_title` | text | 87,656 | Prepared SQL column. Untrusted comment title stored separately from review facts; unavailable to customer tools pending validated Portuguese PII redaction. |
| `review_comment_message` | text | 58,247 | Prepared SQL column. Untrusted Portuguese feedback stored separately; never embedded or exposed before validated redaction and injection quarantine. |
| `review_creation_date` | timestamp without timezone | 0 | Prepared SQL column. Recorded review creation date/time; nullable. |
| `review_answer_timestamp` | timestamp without timezone | 0 | Prepared SQL column. Recorded review response timestamp; not a support-agent reply. |

## geolocation

Source: `olist_geolocation_dataset.csv`. SHA-256: `b514f6fc991b9566aeba02aa5d67e2c3630f034b60a0e05aa0d082a3b66d88d6`.

| Field | Value type | Empty rows | Coverage and meaning |
|---|---|---:|---|
| `geolocation_zip_code_prefix` | numeric | 0 | Prepared SQL column. Source postal prefix retained as text, including leading zeroes; groups the aggregate lookup. |
| `geolocation_lat` | numeric | 0 | Prepared SQL column. Source latitude preserved in the auditable raw table; ZIP-prefix centroid averages unique coordinate pairs. |
| `geolocation_lng` | numeric | 0 | Prepared SQL column. Source longitude preserved in the auditable raw table; ZIP-prefix centroid averages unique coordinate pairs. |
| `geolocation_city` | text | 0 | Prepared SQL column. Source city label preserved in the auditable raw table; not exposed through customer tools. |
| `geolocation_state` | text | 0 | Prepared SQL column. Source state label preserved in the auditable raw table and aggregate state list. |

## Derived coverage and limits

- Order history counts purchases by internal unique-customer identity; displayed orders use opaque references.
- Product price ranges, sales and seller statistics use only selected-account observations; these are not marketplace totals.
- Delivery difference uses actual minus estimated calendar date. Positive means late; delay is max(0, difference). Missing dates remain null. No timezone is invented.
- Aggregate denominators include comparable orders and missing comparisons separately. Cancellation/unavailable counts use recorded statuses.
- Multiple items and payment entries are queried separately to prevent item/payment join multiplication.
- Reviews preserve source-row identity because review IDs and order IDs can recur; review timestamps are not support conversations.
- Customer support chat history belongs exclusively to this application, outside the Olist schema.
- Review comments remain untrusted, separate from review scores and unavailable to tools until Portuguese PII redaction is validated. The bounded first-200 risk sample is not representative.
- Geolocation retains every source row for audit. Its internal ZIP-prefix lookup averages unique coordinate pairs; it is not a household address or delivery route and is not exposed to customers.
