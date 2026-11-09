import csv
from pathlib import Path

import pytest

from support_agent.olist import queries
from support_agent.olist.dataset import EXPECTED, FILES, validate
from support_agent.request_context import RequestContext, current_request
from support_agent.tools.registry import dispatch


def _write(root, table, rows):
    path = root / FILES[table]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=EXPECTED[table].split())
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def olist_temp_dir():
    root = Path(__file__).resolve().parents[1] / ".cache"
    path = root / "olist-validation-fixtures"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def sample_dataset(olist_temp_dir):
    customer, uid, order, product, seller, review = (
        "a" * 32,
        "b" * 32,
        "c" * 32,
        "d" * 32,
        "e" * 32,
        "f" * 32,
    )
    _write(
        olist_temp_dir,
        "categories",
        [{"product_category_name": "office", "product_category_name_english": "office"}],
    )
    customer_row = {c: "" for c in EXPECTED["customers"].split()}
    customer_row.update(
        customer_id=customer,
        customer_unique_id=uid,
        customer_zip_code_prefix="01234",
        customer_city="sao paulo",
        customer_state="SP",
    )
    _write(olist_temp_dir, "customers", [customer_row])
    product_row = {c: "" for c in EXPECTED["products"].split()}
    product_row.update(
        product_id=product,
        product_category_name="office",
        product_weight_g="100",
        product_length_cm="10",
        product_height_cm="10",
        product_width_cm="10",
    )
    _write(olist_temp_dir, "products", [product_row])
    seller_row = {c: "" for c in EXPECTED["sellers"].split()}
    seller_row.update(
        seller_id=seller,
        seller_zip_code_prefix="00123",
        seller_city="sao paulo",
        seller_state="SP",
    )
    _write(olist_temp_dir, "sellers", [seller_row])
    order_row = {c: "" for c in EXPECTED["orders"].split()}
    order_row.update(
        order_id=order,
        customer_id=customer,
        order_status="delivered",
        order_purchase_timestamp="2018-01-01 00:00:00",
    )
    _write(olist_temp_dir, "orders", [order_row])
    _write(
        olist_temp_dir,
        "items",
        [
            {
                "order_id": order,
                "order_item_id": "1",
                "product_id": product,
                "seller_id": seller,
                "shipping_limit_date": "2018-01-01 00:00:00",
                "price": "10.50",
                "freight_value": "1.00",
            }
        ],
    )
    _write(
        olist_temp_dir,
        "payments",
        [
            {
                "order_id": order,
                "payment_sequential": "1",
                "payment_type": "credit_card",
                "payment_installments": "1",
                "payment_value": "11.50",
            }
        ],
    )
    review_row = {c: "" for c in EXPECTED["reviews"].split()}
    review_row.update(
        review_id=review,
        order_id=order,
        review_score="5",
        review_creation_date="2018-01-02 00:00:00",
        review_answer_timestamp="2018-01-03 00:00:00",
        review_comment_title="private",
        review_comment_message="excluded",
    )
    _write(olist_temp_dir, "reviews", [review_row])
    _write(
        olist_temp_dir,
        "geolocation",
        [
            {
                "geolocation_zip_code_prefix": "01046",
                "geolocation_lat": "-23.5",
                "geolocation_lng": "-46.6",
                "geolocation_city": "sao paulo",
                "geolocation_state": "SP",
            }
        ],
    )
    return olist_temp_dir


def test_validates_required_csvs_and_marks_complete_sources_for_import(sample_dataset):
    report = validate(sample_dataset)
    assert report["errors"] == []
    assert report["tables"]["items"]["rows"] == 1
    assert report["tables"]["geolocation"]["selected_for_import"] is True
    assert "review_comment_message" in report["tables"]["reviews"]["columns"]
    assert "review_comment_message" in report["tables"]["reviews"]["import_columns"]
    assert "customer_city" in report["tables"]["customers"]["import_columns"]
    assert "seller_city" in report["tables"]["sellers"]["import_columns"]
    assert report["fingerprint"]


def test_duplicate_order_keys_fail_validation(sample_dataset):
    row = {c: "" for c in EXPECTED["orders"].split()}
    row.update(
        order_id="c" * 32,
        customer_id="a" * 32,
        order_status="delivered",
        order_purchase_timestamp="2018-01-01 00:00:00",
    )
    _write(sample_dataset, "orders", [row, row.copy()])
    report = validate(sample_dataset)
    assert report["tables"]["orders"]["duplicate_primary_keys"] == 1
    assert "orders: invalid values or duplicate primary keys" in report["errors"]


def test_import_mapping_keeps_location_fields_and_zip_leading_zeroes(sample_dataset):
    from support_agent.olist.dataset import rows
    from support_agent.olist.importer import _records, _records_geo
    from support_agent.olist.schema import SCHEMA

    customer = next(_records(sample_dataset, "customers"))
    seller = next(_records(sample_dataset, "sellers"))
    geo = _records_geo(next(rows(sample_dataset, "geolocation")))
    assert customer[2] == "01234" and len(customer) == len(EXPECTED["customers"].split())
    assert seller[1] == "00123" and len(seller) == len(EXPECTED["sellers"].split())
    assert geo[0] == "01046"
    assert "olist_demo.review_comments" in SCHEMA
    assert "olist_demo.geolocation_raw" in SCHEMA
    assert "olist_demo.geolocation_prefixes" in SCHEMA


def test_olist_tool_rejects_missing_account_context():
    result = dispatch("olist_order_lookup", {"order_reference": "demo-order-000001"})
    assert "Choose a historical customer profile" in result.text


def test_olist_context_requires_selected_account():
    token = current_request.set(
        RequestContext("conversation", "request", "owner", kb_profile="olist_demo")
    )
    try:
        with pytest.raises(PermissionError):
            queries.order_lookup("demo-order-000001")
    finally:
        current_request.reset(token)
