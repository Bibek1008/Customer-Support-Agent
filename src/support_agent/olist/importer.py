"""Explicit local-to-Postgres Olist importer. It never runs at app startup."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from support_agent.config import get_settings
from support_agent.olist.dataset import TABLES, validate
from support_agent.olist.schema import migrate

LIMIT_BYTES = 700_000_000
FIELDS = {
    "categories": "product_category_name product_category_name_english",
    "customers": "customer_id customer_unique_id",
    "products": "product_id product_category_name product_weight_g product_length_cm product_height_cm product_width_cm",
    "sellers": "seller_id",
    "orders": "order_id customer_id order_status order_purchase_timestamp order_approved_at order_delivered_carrier_date order_delivered_customer_date order_estimated_delivery_date",
    "items": "order_id order_item_id product_id seller_id shipping_limit_date price freight_value",
    "payments": "order_id payment_sequential payment_type payment_installments payment_value",
    "reviews": "review_id order_id review_score review_creation_date review_answer_timestamp",
}
TARGETS = {
    "categories": "product_category_name,product_category_name_english",
    "customers": "customer_id,customer_unique_id",
    "products": "product_id,product_category_name,product_weight_g,product_length_cm,product_height_cm,product_width_cm",
    "sellers": "seller_id",
    "orders": "order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at,order_delivered_carrier_date,order_delivered_customer_date,order_estimated_delivery_date",
    "items": "order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value",
    "payments": "order_id,payment_sequential,payment_type,payment_installments,payment_value",
    "reviews": "source_row,review_id,order_id,review_score,review_creation_date,review_answer_timestamp",
}


def _convert(column: str, value: str):
    if value == "":
        return None
    if column.endswith("timestamp") or column == "shipping_limit_date":
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    if column in {"price", "freight_value", "payment_value"}:
        return Decimal(value)
    if column in {"order_item_id", "payment_sequential", "payment_installments", "review_score"}:
        return int(value)
    if column in {"product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"}:
        return Decimal(value)
    return value


def _records(root: Path, table: str):
    from support_agent.olist.dataset import rows

    cols = FIELDS[table].split()
    for rownum, row in enumerate(rows(root, table)):
        values = [_convert(c, row[c]) for c in cols]
        if table == "reviews":
            values.insert(0, rownum)
        yield tuple(values)


def _db_report(conn) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        database = cur.execute("SELECT pg_database_size(current_database()) AS bytes").fetchone()[
            "bytes"
        ]
        schema = cur.execute("""
            SELECT COALESCE(sum(pg_total_relation_size(c.oid)),0) AS total,
                   COALESCE(sum(pg_indexes_size(c.oid)),0) AS indexes
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='olist_demo' AND c.relkind IN ('r','m')
        """).fetchone()
        tables = cur.execute("""
            SELECT c.relname AS table, pg_total_relation_size(c.oid) AS total,
                   pg_indexes_size(c.oid) AS indexes,
                   pg_relation_size(c.oid) AS heap
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='olist_demo' AND c.relkind='r' ORDER BY c.relname
        """).fetchall()
    return {
        "database_bytes": database,
        "olist_schema_bytes": schema["total"],
        "olist_index_bytes": schema["indexes"],
        "tables": tables,
        "free_budget_bytes": max(0, 1_000_000_000 - database),
    }


def import_dataset(root: Path, *, limit_bytes: int = LIMIT_BYTES) -> dict:
    report = validate(root)
    if report["errors"]:
        raise ValueError("Dataset validation failed: " + "; ".join(report["errors"]))
    settings = get_settings()
    if not settings.persistence_enabled:
        raise RuntimeError("Set PERSISTENCE_ENABLED=1 for an explicit database import.")
    before = _db_report_connection(settings.database_url)
    if before["database_bytes"] >= limit_bytes:
        raise RuntimeError("Database already exceeds the Olist storage budget; import stopped.")
    conn = psycopg.connect(settings.database_url, autocommit=False, connect_timeout=10)
    try:
        with conn.transaction():
            migrate(conn)
            if conn.execute(
                "SELECT 1 FROM olist_demo.imports WHERE fingerprint=%s", (report["fingerprint"],)
            ).fetchone():
                return {"status": "already_imported", "dataset": report, "storage_before": before}
            for table in TABLES:
                # Stable primary-key conflict handling makes retries safe.
                cols = TARGETS[table]
                colnames = cols.split(",")
                if table == "reviews":
                    conflict = "source_row"
                    target = "olist_demo.reviews"
                else:
                    conflict = {
                        "categories": "product_category_name",
                        "customers": "customer_id",
                        "products": "product_id",
                        "sellers": "seller_id",
                        "orders": "order_id",
                        "items": "order_id,order_item_id",
                        "payments": "order_id,payment_sequential",
                    }[table]
                    target = "olist_demo." + table
                placeholders = ",".join(["%s"] * len(colnames))
                sql = f"INSERT INTO {target} ({cols}) VALUES ({placeholders}) ON CONFLICT ({conflict}) DO NOTHING"
                with conn.cursor() as cur:
                    batch = []
                    for record in _records(root, table):
                        batch.append(record)
                        if len(batch) >= 1000:
                            cur.executemany(sql, batch)
                            batch.clear()
                    if batch:
                        cur.executemany(sql, batch)
            # Deterministic opaque aliases contain no source IDs and are useful
            # only after a user selects a curated account in this conversation.
            conn.execute("""
                INSERT INTO olist_demo.accounts(alias,label,customer_unique_id)
                SELECT 'demo-customer-'||lpad(n::text,2,'0'),'Historical demo customer '||lpad(n::text,2,'0'),customer_unique_id
                FROM (SELECT customer_unique_id,row_number() OVER(ORDER BY count(*) DESC,customer_unique_id) n
                      FROM olist_demo.orders o JOIN olist_demo.customers c USING(customer_id)
                      GROUP BY customer_unique_id ORDER BY count(*) DESC,customer_unique_id LIMIT 10) ranked
                ON CONFLICT DO NOTHING
            """)
            conn.execute("""
                INSERT INTO olist_demo.order_aliases(alias,order_id)
                SELECT 'demo-order-'||lpad(n::text,6,'0'),order_id
                FROM (SELECT order_id,row_number() OVER(ORDER BY order_purchase_timestamp,order_id) n FROM olist_demo.orders) ranked
                ON CONFLICT DO NOTHING
            """)
            conn.execute("""
                INSERT INTO olist_demo.product_aliases(alias,product_id)
                SELECT 'demo-product-'||lpad(n::text,5,'0'),product_id
                FROM (SELECT product_id,row_number() OVER(ORDER BY product_id) n FROM olist_demo.products) ranked
                ON CONFLICT DO NOTHING
            """)
            current = _db_report(conn)
            if current["database_bytes"] > limit_bytes:
                raise RuntimeError(
                    "Import exceeded 700 MB database budget; transaction rolled back."
                )
            conn.execute(
                "INSERT INTO olist_demo.imports(fingerprint,report) VALUES(%s,%s)",
                (report["fingerprint"], Jsonb(report)),
            )
        after = _db_report(conn)
    finally:
        conn.close()
    return {
        "status": "imported",
        "dataset": report,
        "storage_before": before,
        "storage_after": after,
        "olist_growth_bytes": after["olist_schema_bytes"] - before["olist_schema_bytes"],
    }


def _db_report_connection(url):
    with psycopg.connect(url, connect_timeout=10) as conn:
        return _db_report(conn)


def main():
    parser = argparse.ArgumentParser(
        description="Import validated Olist CSVs into the olist_demo schema."
    )
    parser.add_argument("--data", type=Path, default=Path("data/raw/olist"))
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--storage-report", action="store_true")
    parser.add_argument(
        "--report",
        type=Path,
        help="Write the validation/import report to this JSON path (creates parents).",
    )
    args = parser.parse_args()
    if args.storage_report:
        settings = get_settings()
        result = _db_report_connection(settings.database_url)
    elif args.validate_only:
        result = validate(args.data)
    else:
        result = import_dataset(args.data)
    rendered = json.dumps(result, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
