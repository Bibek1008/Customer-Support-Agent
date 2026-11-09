"""Real SQL semantics on an explicit loopback test database only; always rolls back.

Set OLIST_TEST_DATABASE_URL to a dedicated local PostgreSQL database. This test
never loads .env credentials and refuses remote (including Neon) destinations.
"""

import os
from contextlib import contextmanager
from datetime import datetime

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from support_agent.olist import queries
from support_agent.olist.schema import migrate
from support_agent.request_context import RequestContext, current_request

TEST_URL = os.environ.get("OLIST_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="Needs an explicitly configured local Olist PostgreSQL test database"
)


@pytest.fixture
def local_database(monkeypatch):
    options = conninfo_to_dict(TEST_URL)
    assert options.get("host") in {"localhost", "127.0.0.1", "::1"}
    assert options.get("hostaddr", options["host"]) in {"localhost", "127.0.0.1", "::1"}
    assert not any(key in options for key in ("service", "options"))
    assert options.get("dbname") == "support_agent_test"
    assert options.get("port") == "5433"
    with psycopg.connect(TEST_URL) as conn, conn.transaction(force_rollback=True):
        from support_agent.db import SCHEMA

        conn.execute(SCHEMA)
        migrate(conn)
        if conn.execute("SELECT 1 FROM olist_demo.orders LIMIT 1").fetchone():
            pytest.fail(
                "Use an empty dedicated test database; existing Olist rows are never replaced."
            )
        conn.execute("INSERT INTO olist_demo.categories VALUES ('teste','test category')")
        for n in (1, 2):
            customer, unique, product, seller, order = (
                f"{n + offset:032x}" for offset in (0, 10, 20, 30, 40)
            )
            conn.execute("INSERT INTO olist_demo.customers VALUES (%s,%s)", (customer, unique))
            conn.execute(
                "INSERT INTO olist_demo.products(product_id,product_category_name,product_weight_g,product_photos_qty) VALUES(%s,%s,100,2)",
                (product, "teste"),
            )
            conn.execute(
                "INSERT INTO olist_demo.sellers(seller_id,seller_state) VALUES(%s,%s)",
                (seller, "SP"),
            )
            conn.execute(
                "INSERT INTO olist_demo.orders VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    order,
                    customer,
                    "delivered",
                    datetime(2018, 1, 1),
                    None,
                    None,
                    datetime(2018, 1, 15) if n == 1 else None,
                    datetime(2018, 1, 10),
                ),
            )
            conn.execute(
                "INSERT INTO olist_demo.items VALUES(%s,1,%s,%s,NULL,10.50,2.00)",
                (order, product, seller),
            )
            conn.execute(
                "INSERT INTO olist_demo.payments VALUES(%s,1,%s,3,12.50)", (order, "credit_card")
            )
            conn.execute(
                "INSERT INTO olist_demo.accounts VALUES(%s,%s,%s)",
                (f"demo-customer-{n:02}", f"Synthetic {n}", unique),
            )
            for table, key, prefix, size, identifier in [
                ("order_aliases", "order_id", "order", 6, order),
                ("product_aliases", "product_id", "product", 5, product),
                ("seller_aliases", "seller_id", "seller", 5, seller),
            ]:
                conn.execute(
                    f"INSERT INTO olist_demo.{table}(alias,{key}) VALUES(%s,%s)",
                    (f"demo-{prefix}-{n:0{size}}", identifier),
                )
        conn.execute(
            "INSERT INTO olist_demo.items SELECT order_id,2,product_id,seller_id,NULL,5,1 FROM olist_demo.items WHERE order_id=%s",
            (f"{41:032x}",),
        )
        conn.execute(
            "INSERT INTO olist_demo.payments VALUES(%s,2,%s,1,6.00)", (f"{41:032x}", "voucher")
        )
        conn.execute(
            "INSERT INTO olist_demo.reviews VALUES(0,%s,%s,4,%s,%s)",
            ("f" * 32, f"{41:032x}", datetime(2018, 1, 16), datetime(2018, 1, 17)),
        )

        @contextmanager
        def connection():
            yield conn

        monkeypatch.setattr(queries, "connection", connection)
        token = current_request.set(
            RequestContext(
                "synthetic",
                "synthetic",
                "owner",
                kb_profile="olist_demo",
                olist_account="demo-customer-01",
            )
        )
        try:
            yield conn
        finally:
            current_request.reset(token)


def test_actual_joins_counts_dates_and_isolation(local_database):
    import json

    def records(text):
        return json.loads(text.split(": ", 1)[1].split(". Amounts are BRL;", 1)[0])

    assert len(records(queries.order_items("demo-order-000001"))) == 2
    payments = records(queries.payment_details("demo-order-000001"))
    assert len(payments) == 2 and payments[0]["payment_installments"] == 3
    timeline = records(queries.delivery_status("demo-order-000001"))[0]
    assert timeline["delivery_difference_days"] == timeline["delay_days"] == 5
    assert timeline["order_approved_at"] is None
    assert "1 orders" in queries.order_history()
    assert "4 created" in queries.review_lookup("demo-order-000001")
    assert records(queries.product_details("demo-product-00001"))[0]["account_units"] == 2
    assert records(queries.seller_info("demo-seller-00001"))[0]["account_orders"] == 1
    aggregate = records(queries.delivery_performance())[0]
    assert (
        aggregate["total_orders"] == aggregate["late_orders"] == aggregate["comparable_orders"] == 1
    )
    for handler, alias in [
        (queries.order_lookup, "demo-order-000002"),
        (queries.product_details, "demo-product-00002"),
        (queries.order_items, "demo-order-000002"),
        (queries.seller_info, "demo-seller-00002"),
        (queries.payment_details, "demo-order-000002"),
        (queries.review_lookup, "demo-order-000002"),
    ]:
        assert handler(alias).startswith("No ")
    local_database.execute(
        "UPDATE olist_demo.orders SET order_delivered_customer_date=NULL WHERE order_id=%s",
        (f"{41:032x}",),
    )
    assert records(queries.delivery_status("demo-order-000001"))[0]["delay_days"] is None
