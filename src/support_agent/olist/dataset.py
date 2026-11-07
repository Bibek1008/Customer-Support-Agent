"""Streaming CSV validation. Reports counts/quality, never raw customer rows."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Import only these fields, in dependency order. No location or review comments.
TABLES = {
    "categories": (
        "product_category_name_translation.csv",
        "product_category_name product_category_name_english",
    ),
    "customers": ("olist_customers_dataset.csv", "customer_id customer_unique_id"),
    "products": (
        "olist_products_dataset.csv",
        "product_id product_category_name product_weight_g product_length_cm product_height_cm product_width_cm",
    ),
    "sellers": ("olist_sellers_dataset.csv", "seller_id"),
    "orders": (
        "olist_orders_dataset.csv",
        "order_id customer_id order_status order_purchase_timestamp order_approved_at order_delivered_carrier_date order_delivered_customer_date order_estimated_delivery_date",
    ),
    "items": (
        "olist_order_items_dataset.csv",
        "order_id order_item_id product_id seller_id shipping_limit_date price freight_value",
    ),
    "payments": (
        "olist_order_payments_dataset.csv",
        "order_id payment_sequential payment_type payment_installments payment_value",
    ),
    "reviews": (
        "olist_order_reviews_dataset.csv",
        "review_id order_id review_score review_creation_date review_answer_timestamp",
    ),
}
EXPECTED = {
    "customers": "customer_id customer_unique_id customer_zip_code_prefix customer_city customer_state",
    "orders": TABLES["orders"][1],
    "items": TABLES["items"][1],
    "payments": TABLES["payments"][1],
    "products": "product_id product_category_name product_name_lenght product_description_lenght product_photos_qty product_weight_g product_length_cm product_height_cm product_width_cm",
    "sellers": "seller_id seller_zip_code_prefix seller_city seller_state",
    "reviews": "review_id order_id review_score review_comment_title review_comment_message review_creation_date review_answer_timestamp",
    "categories": TABLES["categories"][1],
    "geolocation": "geolocation_zip_code_prefix geolocation_lat geolocation_lng geolocation_city geolocation_state",
}
FILES = {
    **{t: spec[0] for t, spec in TABLES.items()},
    "geolocation": "olist_geolocation_dataset.csv",
}
KEYS = {
    "customers": "customer_id",
    "orders": "order_id",
    "items": "order_id order_item_id",
    "payments": "order_id payment_sequential",
    "products": "product_id",
    "sellers": "seller_id",
    "categories": "product_category_name",
}
NUMERIC = {
    "order_item_id",
    "price",
    "freight_value",
    "payment_sequential",
    "payment_installments",
    "payment_value",
    "review_score",
    "product_name_lenght",
    "product_description_lenght",
    "product_photos_qty",
    "product_weight_g",
    "product_length_cm",
    "product_height_cm",
    "product_width_cm",
    "geolocation_lat",
    "geolocation_lng",
    "customer_zip_code_prefix",
    "seller_zip_code_prefix",
    "geolocation_zip_code_prefix",
}
DATES = {
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
    "shipping_limit_date",
    "review_creation_date",
    "review_answer_timestamp",
}
RELATIONS = {
    "orders": {"customer_id": "customers"},
    "items": {"order_id": "orders", "product_id": "products", "seller_id": "sellers"},
    "payments": {"order_id": "orders"},
    "reviews": {"order_id": "orders"},
}


def rows(root: Path, table: str):
    with (root / FILES[table]).open(encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def validate(root: Path) -> dict:
    missing = [name for name in FILES.values() if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing required Olist CSVs: " + ", ".join(missing))
    result = {"tables": {}, "errors": [], "warnings": [], "fingerprint": ""}
    fingerprint = hashlib.sha256()
    identities = {}
    for table, filename in FILES.items():
        path = root / filename
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        checksum = digest.hexdigest()
        fingerprint.update((filename + checksum).encode())
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            columns = reader.fieldnames or []
            if set(columns) != set(EXPECTED[table].split()):
                result["errors"].append(f"{table}: unexpected columns")
                continue
            nulls, invalid, keys, full_rows = Counter(), Counter(), set(), set()
            count = duplicates = exact_duplicates = 0
            for row in reader:
                count += 1
                signature = hashlib.sha256(repr(tuple(row.values())).encode()).digest()
                exact_duplicates += signature in full_rows
                full_rows.add(signature)
                if None in row or any(v is None for v in row.values()):
                    invalid["row_shape"] += 1
                    continue
                key = tuple(row.get(c) for c in KEYS.get(table, "").split())
                if key:
                    duplicates += key in keys
                    keys.add(key)
                    if not all(key):
                        invalid["primary_key"] += 1
                for column, value in row.items():
                    if not value:
                        nulls[column] += 1
                        continue
                    try:
                        if column in NUMERIC:
                            number = Decimal(value)
                            if not number.is_finite() or (
                                column not in {"geolocation_lat", "geolocation_lng"} and number < 0
                            ):
                                raise ValueError()
                            if column == "review_score" and (
                                number != int(number) or not 1 <= number <= 5
                            ):
                                raise ValueError()
                            if column in {
                                "order_item_id",
                                "payment_sequential",
                                "payment_installments",
                            } and number != int(number):
                                raise ValueError()
                        elif column in DATES:
                            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                        elif column in {
                            "customer_id",
                            "customer_unique_id",
                            "order_id",
                            "product_id",
                            "seller_id",
                            "review_id",
                        }:
                            if len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
                                raise ValueError()
                    except (ValueError, InvalidOperation):
                        invalid[column] += 1
            identities[table] = {k[0] for k in keys if len(k) == 1}
            result["tables"][table] = {
                "file": filename,
                "bytes": path.stat().st_size,
                "sha256": checksum,
                "rows": count,
                "columns": columns,
                "import_columns": TABLES[table][1].split() if table in TABLES else [],
                "nulls": dict(nulls),
                "invalid": dict(invalid),
                "duplicate_primary_keys": duplicates,
                "duplicate_rows": exact_duplicates,
                "imported": table != "geolocation",
            }
            if duplicates or invalid:
                result["errors"].append(f"{table}: invalid values or duplicate primary keys")
    if result["errors"]:
        return result
    for table, relations in RELATIONS.items():
        orphans = Counter()
        for row in rows(root, table):
            for column, parent in relations.items():
                if row[column] not in identities[parent]:
                    orphans[column] += 1
        result["tables"][table]["orphans"] = dict(orphans)
        if orphans:
            result["errors"].append(f"{table}: orphan foreign keys")
    # Category translation coverage is incomplete in the public release. Keep
    # untranslated categories; do not fabricate labels or reject valid products.
    unknown = sum(
        bool(r["product_category_name"])
        and r["product_category_name"] not in identities["categories"]
        for r in rows(root, "products")
    )
    result["warnings"].append(f"Products without category translation: {unknown}")
    result["fingerprint"] = fingerprint.hexdigest()
    return result
