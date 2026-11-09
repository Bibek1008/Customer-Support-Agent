"""Additive migrations, run explicitly; never run by the web service."""

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS olist_demo;
CREATE TABLE IF NOT EXISTS olist_demo.categories (
 product_category_name TEXT PRIMARY KEY, product_category_name_english TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS olist_demo.customers (
 customer_id TEXT PRIMARY KEY CHECK(length(customer_id)=32), customer_unique_id TEXT NOT NULL,
 customer_zip_code_prefix TEXT, customer_city TEXT, customer_state TEXT
);
CREATE INDEX IF NOT EXISTS customers_unique_id ON olist_demo.customers(customer_unique_id);
CREATE TABLE IF NOT EXISTS olist_demo.products (
 product_id TEXT PRIMARY KEY CHECK(length(product_id)=32), product_category_name TEXT,
 product_weight_g NUMERIC, product_length_cm NUMERIC, product_height_cm NUMERIC,
 product_width_cm NUMERIC
);
CREATE TABLE IF NOT EXISTS olist_demo.sellers (
 seller_id TEXT PRIMARY KEY CHECK(length(seller_id)=32), seller_zip_code_prefix TEXT,
 seller_city TEXT, seller_state TEXT
);
CREATE TABLE IF NOT EXISTS olist_demo.orders (
 order_id TEXT PRIMARY KEY CHECK(length(order_id)=32),
 customer_id TEXT NOT NULL REFERENCES olist_demo.customers(customer_id),
 order_status TEXT NOT NULL, order_purchase_timestamp TIMESTAMP NOT NULL,
 order_approved_at TIMESTAMP, order_delivered_carrier_date TIMESTAMP,
 order_delivered_customer_date TIMESTAMP, order_estimated_delivery_date TIMESTAMP
);
CREATE INDEX IF NOT EXISTS orders_customer ON olist_demo.orders(customer_id);
CREATE TABLE IF NOT EXISTS olist_demo.items (
 order_id TEXT REFERENCES olist_demo.orders(order_id), order_item_id INTEGER CHECK(order_item_id>0),
 product_id TEXT NOT NULL REFERENCES olist_demo.products(product_id),
 seller_id TEXT NOT NULL REFERENCES olist_demo.sellers(seller_id), shipping_limit_date TIMESTAMP,
 price NUMERIC(12,2) NOT NULL CHECK(price>=0),
 freight_value NUMERIC(12,2) NOT NULL CHECK(freight_value>=0),
 PRIMARY KEY(order_id,order_item_id)
);
CREATE TABLE IF NOT EXISTS olist_demo.payments (
 order_id TEXT REFERENCES olist_demo.orders(order_id), payment_sequential INTEGER,
 payment_type TEXT NOT NULL, payment_installments INTEGER CHECK(payment_installments>=0),
 payment_value NUMERIC(12,2) NOT NULL CHECK(payment_value>=0),
 PRIMARY KEY(order_id,payment_sequential)
);
CREATE TABLE IF NOT EXISTS olist_demo.reviews (
 source_row INTEGER PRIMARY KEY, review_id TEXT NOT NULL,
 order_id TEXT NOT NULL REFERENCES olist_demo.orders(order_id),
 review_score SMALLINT NOT NULL CHECK(review_score BETWEEN 1 AND 5),
 review_creation_date TIMESTAMP, review_answer_timestamp TIMESTAMP
);
CREATE INDEX IF NOT EXISTS reviews_order ON olist_demo.reviews(order_id);
CREATE TABLE IF NOT EXISTS olist_demo.review_comments (
 source_row INTEGER PRIMARY KEY REFERENCES olist_demo.reviews(source_row) ON DELETE CASCADE,
 review_comment_title TEXT, review_comment_message TEXT
);
COMMENT ON TABLE olist_demo.review_comments IS
 'Untrusted source comments; do not expose until Portuguese PII redaction is validated.';
CREATE TABLE IF NOT EXISTS olist_demo.geolocation_raw (
 source_row BIGINT PRIMARY KEY, geolocation_zip_code_prefix TEXT NOT NULL,
 geolocation_lat DOUBLE PRECISION NOT NULL, geolocation_lng DOUBLE PRECISION NOT NULL,
 geolocation_city TEXT NOT NULL, geolocation_state TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS geolocation_raw_zip ON olist_demo.geolocation_raw(geolocation_zip_code_prefix);
CREATE TABLE IF NOT EXISTS olist_demo.geolocation_prefixes (
 geolocation_zip_code_prefix TEXT PRIMARY KEY, point_count BIGINT NOT NULL,
 unique_point_count BIGINT NOT NULL, centroid_lat DOUBLE PRECISION NOT NULL,
 centroid_lng DOUBLE PRECISION NOT NULL, source_states TEXT[] NOT NULL
);
CREATE TABLE IF NOT EXISTS olist_demo.accounts (
 alias TEXT PRIMARY KEY, label TEXT NOT NULL, customer_unique_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS olist_demo.order_aliases (
 alias TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE REFERENCES olist_demo.orders(order_id)
);
CREATE TABLE IF NOT EXISTS olist_demo.product_aliases (
 alias TEXT PRIMARY KEY, product_id TEXT NOT NULL UNIQUE REFERENCES olist_demo.products(product_id)
);
CREATE TABLE IF NOT EXISTS olist_demo.conversation_accounts (
 conversation_id TEXT PRIMARY KEY REFERENCES public.support_conversations(id),
 account_alias TEXT NOT NULL REFERENCES olist_demo.accounts(alias)
);
CREATE TABLE IF NOT EXISTS olist_demo.imports (
 fingerprint TEXT PRIMARY KEY, completed_at TIMESTAMPTZ NOT NULL DEFAULT now(), report JSONB NOT NULL
);
ALTER TABLE olist_demo.products ADD COLUMN IF NOT EXISTS product_photos_qty INTEGER;
ALTER TABLE olist_demo.products ADD COLUMN IF NOT EXISTS product_name_lenght INTEGER;
ALTER TABLE olist_demo.products ADD COLUMN IF NOT EXISTS product_description_lenght INTEGER;
ALTER TABLE olist_demo.sellers ADD COLUMN IF NOT EXISTS seller_state TEXT;
ALTER TABLE olist_demo.customers ADD COLUMN IF NOT EXISTS customer_zip_code_prefix TEXT;
ALTER TABLE olist_demo.customers ADD COLUMN IF NOT EXISTS customer_city TEXT;
ALTER TABLE olist_demo.customers ADD COLUMN IF NOT EXISTS customer_state TEXT;
ALTER TABLE olist_demo.sellers ADD COLUMN IF NOT EXISTS seller_zip_code_prefix TEXT;
ALTER TABLE olist_demo.sellers ADD COLUMN IF NOT EXISTS seller_city TEXT;
CREATE INDEX IF NOT EXISTS items_product ON olist_demo.items(product_id);
CREATE INDEX IF NOT EXISTS items_seller ON olist_demo.items(seller_id);
CREATE TABLE IF NOT EXISTS olist_demo.seller_aliases (
 alias TEXT PRIMARY KEY, seller_id TEXT NOT NULL UNIQUE REFERENCES olist_demo.sellers(seller_id)
);
CREATE TABLE IF NOT EXISTS olist_demo.release_versions (
 version INTEGER PRIMARY KEY, completed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def migrate(conn):
    conn.execute("SELECT pg_advisory_xact_lock(391087422)")
    conn.execute(SCHEMA)
