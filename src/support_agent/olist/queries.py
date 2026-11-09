"""Fixed, read-only Olist lookups constrained by the selected demo account."""

import json

from support_agent.db import connection
from support_agent.request_context import current_request


def selected_account(conversation_id: str, owner_hash: str) -> str | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT a.alias FROM public.support_conversations c
            JOIN olist_demo.accounts a ON a.alias=c.olist_account_alias
            WHERE c.id=%s AND c.owner_hash=%s AND c.kb_profile='olist_demo'
        """,
            (conversation_id, owner_hash),
        ).fetchone()
    return row[0] if row else None


def public_accounts() -> list[dict]:
    return dataset_status()["accounts"]


def dataset_status() -> dict:
    with connection() as conn:
        required = (
            "accounts",
            "orders",
            "customers",
            "items",
            "products",
            "sellers",
            "payments",
            "reviews",
            "categories",
            "order_aliases",
            "product_aliases",
            "seller_aliases",
            "review_comments",
            "geolocation_raw",
            "geolocation_prefixes",
        )
        missing = [
            t
            for t in required
            if not conn.execute("SELECT to_regclass(%s)", ("olist_demo." + t,)).fetchone()[0]
        ]
        if missing:
            return {
                "status": "not_initialized",
                "accounts": [],
                "message": "Olist dataset has not been initialized. Complete the reviewed schema migration and full version 3 import before selecting a historical profile.",
            }
        # The release marker prevents old partial imports being presented as ready.
        version = conn.execute("SELECT to_regclass('olist_demo.release_versions')").fetchone()[0]
        if (
            not version
            or not conn.execute(
                "SELECT 1 FROM olist_demo.release_versions WHERE version=3"
            ).fetchone()
        ):
            return {
                "status": "upgrade_required",
                "accounts": [],
                "message": "Olist data upgrade is required. Run the reviewed migration and version 3 importer before selecting a historical profile.",
            }
        accounts = conn.execute(
            "SELECT alias,label FROM olist_demo.accounts ORDER BY alias"
        ).fetchall()
        return {
            "status": "ready" if accounts else "no_accounts",
            "accounts": [{"alias": r[0], "label": r[1]} for r in accounts],
            "message": "Historical accounts available."
            if accounts
            else "No demo accounts exist. Complete the Olist data import before account selection.",
        }


def account_orders(conversation_id: str, owner_hash: str) -> list[dict]:
    with connection() as conn:
        account = conn.execute(
            "SELECT olist_account_alias FROM public.support_conversations WHERE id=%s AND owner_hash=%s AND kb_profile='olist_demo'",
            (conversation_id, owner_hash),
        ).fetchone()
        if not account or not account[0]:
            return []
        rows = conn.execute(
            """
            SELECT oa.alias,o.order_status,o.order_purchase_timestamp
            FROM olist_demo.orders o JOIN olist_demo.customers c USING(customer_id)
            JOIN olist_demo.order_aliases oa USING(order_id)
            WHERE c.customer_unique_id=(SELECT customer_unique_id FROM olist_demo.accounts WHERE alias=%s)
            ORDER BY o.order_purchase_timestamp DESC LIMIT 25
        """,
            (account[0],),
        ).fetchall()
    return [
        {"reference": r[0], "recorded_status": r[1], "purchase_date": r[2].isoformat()}
        for r in rows
    ]


def current_selection(conversation_id: str, owner_hash: str) -> dict:
    with connection() as conn:
        row = conn.execute(
            "SELECT kb_profile,olist_account_alias FROM public.support_conversations WHERE id=%s AND owner_hash=%s",
            (conversation_id, owner_hash),
        ).fetchone()
    if not row:
        return {}
    if row[0] != "olist_demo":
        return {"profile": "office_store"}
    if not row[1]:
        return {"profile": "olist_demo", "account": None, "orders": []}
    status = dataset_status()
    if status["status"] != "ready":
        return {
            "profile": "olist_demo",
            "account": None,
            "orders": [],
            "message": status["message"],
        }
    orders = account_orders(conversation_id, owner_hash)
    return {
        "profile": row[0],
        "account": row[1],
        "orders": orders,
        "disclosure": "Olist Brazilian E-Commerce Public Dataset. Historical records only; no live customer, carrier, or support data.",
    }


def bind_account(conversation_id: str, owner_hash: str, alias: str) -> bool:
    if dataset_status()["status"] != "ready":
        return False
    with connection() as conn, conn.transaction():
        exists = conn.execute(
            "SELECT 1 FROM olist_demo.accounts WHERE alias=%s", (alias,)
        ).fetchone()
        if not exists:
            return False
        updated = conn.execute(
            """
                UPDATE public.support_conversations c SET kb_profile='olist_demo',olist_account_alias=%s
                WHERE c.id=%s AND c.owner_hash=%s
                  AND NOT EXISTS(SELECT 1 FROM public.support_messages m WHERE m.conversation_id=c.id)
                RETURNING c.id
            """,
            (alias, conversation_id, owner_hash),
        ).fetchone()
        return bool(updated)


def reset_profile(conversation_id: str, owner_hash: str) -> bool:
    with connection() as conn, conn.transaction():
        updated = conn.execute(
            """
                UPDATE public.support_conversations c SET kb_profile='office_store',olist_account_alias=NULL
                WHERE c.id=%s AND c.owner_hash=%s
                  AND NOT EXISTS(SELECT 1 FROM public.support_messages m WHERE m.conversation_id=c.id)
                RETURNING c.id
            """,
            (conversation_id, owner_hash),
        ).fetchone()
        return bool(updated)


def _account():
    request = current_request.get()
    if request is None or request.kb_profile != "olist_demo" or not request.olist_account:
        raise PermissionError("Select a historical demo account before asking about Olist records.")
    return request.olist_account


def _records(sql: str, args: tuple = ()) -> list[dict]:
    """Account is always supplied by server context, never by a tool argument."""
    from psycopg.rows import dict_row

    account = _account()
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (*args, account))
        return cur.fetchall()


def _render(records: list[dict], description: str) -> str:
    if not records:
        return "No matching historical records were found for the selected demo account."
    return (
        "Historical transaction record — "
        + description
        + ": "
        + json.dumps(records, default=str, ensure_ascii=False)
        + ". Amounts are BRL; null means not recorded. Historical facts only; no live status or action confirmation."
    )


SCOPE = "c.customer_unique_id=(SELECT customer_unique_id FROM olist_demo.accounts WHERE alias=%s)"
ORDER_FROM = """FROM olist_demo.orders o JOIN olist_demo.customers c USING(customer_id)
    JOIN olist_demo.order_aliases oa USING(order_id)"""


def order_items(alias: str) -> str:
    return _render(
        _records(
            """SELECT oa.alias AS order_reference, i.order_item_id AS item_number,
        pa.alias AS product_reference, sa.alias AS seller_reference,
        COALESCE(ct.product_category_name_english,p.product_category_name) AS category,
        i.price,i.freight_value,i.shipping_limit_date
        """
            + ORDER_FROM
            + """ JOIN olist_demo.items i USING(order_id)
        JOIN olist_demo.products p USING(product_id)
        JOIN olist_demo.product_aliases pa USING(product_id)
        JOIN olist_demo.seller_aliases sa USING(seller_id)
        LEFT JOIN olist_demo.categories ct USING(product_category_name)
        WHERE oa.alias=%s AND """
            + SCOPE
            + " ORDER BY i.order_item_id LIMIT 100",
            (alias,),
        ),
        "order items (up to 100)",
    )


def payment_details(alias: str) -> str:
    return _render(
        _records(
            """SELECT oa.alias AS order_reference,p.payment_sequential AS entry,
        p.payment_type,p.payment_value,p.payment_installments
        """
            + ORDER_FROM
            + """ JOIN olist_demo.payments p USING(order_id)
        WHERE oa.alias=%s AND """
            + SCOPE
            + " ORDER BY p.payment_sequential LIMIT 100",
            (alias,),
        ),
        "payment breakdown and installment counts; no payment schedule or refund record exists",
    )


def delivery_status(alias: str) -> str:
    return _render(
        _records(
            """SELECT oa.alias AS order_reference,o.order_status,
        o.order_purchase_timestamp,o.order_approved_at,o.order_delivered_carrier_date,
        o.order_delivered_customer_date,o.order_estimated_delivery_date,
        (o.order_delivered_customer_date::date-o.order_estimated_delivery_date::date) AS delivery_difference_days,
        CASE WHEN o.order_delivered_customer_date IS NOT NULL AND o.order_estimated_delivery_date IS NOT NULL
        THEN GREATEST(0,o.order_delivered_customer_date::date-o.order_estimated_delivery_date::date) END AS delay_days
        """
            + ORDER_FROM
            + " WHERE oa.alias=%s AND "
            + SCOPE,
            (alias,),
        ),
        "delivery timeline; positive difference is late, negative is early; missing actual/estimate means no comparison",
    )


def delivery_performance() -> str:
    return _render(
        _records(
            """SELECT count(*) AS total_orders,
        count(*) FILTER(WHERE order_status='delivered') AS delivered_orders,
        count(*) FILTER(WHERE order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL) AS comparable_orders,
        count(*) FILTER(WHERE order_delivered_customer_date::date>order_estimated_delivery_date::date) AS late_orders,
        count(*) FILTER(WHERE order_delivered_customer_date IS NULL OR order_estimated_delivery_date IS NULL) AS missing_comparison,
        avg(order_delivered_customer_date::date-order_estimated_delivery_date::date) AS mean_difference_days,
        count(*) FILTER(WHERE order_status='canceled') AS canceled_orders,
        count(*) FILTER(WHERE order_status='unavailable') AS unavailable_orders
        """
            + ORDER_FROM
            + " WHERE "
            + SCOPE
        ),
        "selected-account delivery performance and cancellation/unavailable counts; not marketplace-wide statistics",
    )


def marketplace_summary() -> str:
    return _render(
        _records(
            """SELECT count(*) AS historical_orders,
               count(*) FILTER(WHERE order_status='canceled') AS canceled_orders,
               round(100.0*count(*) FILTER(WHERE order_status='canceled')/NULLIF(count(*),0),2) AS cancellation_percent,
               count(*) FILTER(WHERE order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL) AS comparable_deliveries,
               count(*) FILTER(WHERE order_delivered_customer_date::date>order_estimated_delivery_date::date) AS late_deliveries,
               round(100.0*count(*) FILTER(WHERE order_delivered_customer_date::date>order_estimated_delivery_date::date)/NULLIF(count(*) FILTER(WHERE order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL),0),2) AS late_percent,
               (SELECT round(avg(review_score)::numeric,2) FROM olist_demo.reviews) AS average_review_score
            FROM olist_demo.orders WHERE %s::text IS NOT NULL"""
        ),
        "dataset-wide historical marketplace counts and rates; not current service performance",
    )


def payment_distribution() -> str:
    return _render(
        _records(
            """SELECT payment_type,count(*) AS payment_entries,
               round(100.0*count(*)/sum(count(*)) OVER(),2) AS entry_percent,
               sum(payment_value) AS recorded_amount_brl
            FROM olist_demo.payments WHERE %s::text IS NOT NULL
            GROUP BY payment_type ORDER BY payment_entries DESC"""
        ),
        "dataset-wide historical payment method distribution; amounts are recorded payments, not refunds or current charges",
    )


def category_satisfaction() -> str:
    return _render(
        _records(
            """SELECT COALESCE(ct.product_category_name_english,r.product_category_name,'Uncategorized') AS category,
               count(*) AS review_count,round(avg(r.review_score)::numeric,2) AS average_review_score
            FROM (SELECT DISTINCT r.source_row,r.review_score,p.product_category_name
                  FROM olist_demo.reviews r JOIN olist_demo.items i USING(order_id)
                  JOIN olist_demo.products p USING(product_id)) r
            LEFT JOIN olist_demo.categories ct USING(product_category_name)
            WHERE %s::text IS NOT NULL
            GROUP BY COALESCE(ct.product_category_name_english,r.product_category_name,'Uncategorized')
            HAVING count(*)>=100 ORDER BY review_count DESC LIMIT 30"""
        ),
        "historical category satisfaction from structured review scores, with groups below 100 reviews suppressed; no comment text or sentiment inference",
    )


def regional_statistics() -> str:
    return _render(
        _records(
            """SELECT customer_state AS brazilian_state,count(*) AS historical_orders
            FROM olist_demo.orders o JOIN olist_demo.customers c USING(customer_id)
            WHERE %s::text IS NOT NULL AND customer_state IS NOT NULL
            GROUP BY customer_state HAVING count(*)>=100
            ORDER BY historical_orders DESC LIMIT 30"""
        ),
        "historical order counts by Brazilian state; groups below 100 orders are suppressed and no customer location is returned",
    )


def feedback_history() -> str:
    return _render(
        _records(
            """SELECT oa.alias AS order_reference,r.review_score,
        r.review_creation_date,r.review_answer_timestamp
        """
            + ORDER_FROM
            + """ JOIN olist_demo.reviews r USING(order_id)
        WHERE """
            + SCOPE
            + " ORDER BY r.review_creation_date DESC LIMIT 50"
        ),
        "customer feedback history (up to 50); scores are historical feedback, never policy; comments unavailable",
    )


def seller_info(alias: str) -> str:
    return _render(
        _records(
            """SELECT sa.alias AS seller_reference,s.seller_state AS seller_region,
        count(DISTINCT o.order_id) AS account_orders,count(*) AS account_items,
        sum(i.price) AS account_item_sales_brl,
        market.order_count AS marketplace_orders,market.item_count AS marketplace_items,
        market.sales_brl AS marketplace_sales_brl,feedback.review_count,feedback.average_review_score,
        delivery.delivered_orders,delivery.comparable_orders,delivery.late_orders
        """
            + ORDER_FROM
            + """ JOIN olist_demo.items i USING(order_id)
        JOIN olist_demo.sellers s USING(seller_id)
        JOIN olist_demo.seller_aliases sa USING(seller_id)
        CROSS JOIN LATERAL (
            SELECT count(DISTINCT mi.order_id) AS order_count,count(*) AS item_count,sum(mi.price) AS sales_brl
            FROM olist_demo.items mi WHERE mi.seller_id=s.seller_id
        ) market
        CROSS JOIN LATERAL (
            SELECT count(*) AS review_count,avg(rv.review_score) AS average_review_score
            FROM (SELECT DISTINCT r.source_row,r.review_score
                  FROM olist_demo.reviews r JOIN olist_demo.items ri USING(order_id)
                  WHERE ri.seller_id=s.seller_id) rv
        ) feedback
        CROSS JOIN LATERAL (
            SELECT count(*) FILTER(WHERE so.order_status='delivered') AS delivered_orders,
                   count(*) FILTER(WHERE so.order_delivered_customer_date IS NOT NULL AND so.order_estimated_delivery_date IS NOT NULL) AS comparable_orders,
                   count(*) FILTER(WHERE so.order_delivered_customer_date::date>so.order_estimated_delivery_date::date) AS late_orders
            FROM (SELECT DISTINCT od.order_id,od.order_status,od.order_delivered_customer_date,od.order_estimated_delivery_date
                  FROM olist_demo.orders od JOIN olist_demo.items si USING(order_id)
                  WHERE si.seller_id=s.seller_id) so
        ) delivery
        WHERE sa.alias=%s AND """
            + SCOPE
            + " GROUP BY sa.alias,s.seller_state,market.order_count,market.item_count,market.sales_brl,feedback.review_count,feedback.average_review_score,delivery.delivered_orders,delivery.comparable_orders,delivery.late_orders",
            (alias,),
        ),
        "seller region and selected-account plus whole-dataset historical sales, delivery and review statistics; no seller contact information or current performance claim",
    )


def product_details(alias: str) -> str:
    return _render(
        _records(
            """SELECT pa.alias AS product_reference,
        COALESCE(ct.product_category_name_english,p.product_category_name) AS category,
        p.product_weight_g,p.product_length_cm,p.product_height_cm,p.product_width_cm,
        p.product_photos_qty,p.product_name_lenght,p.product_description_lenght,
        count(DISTINCT o.order_id) AS account_orders,count(*) AS account_units,
        min(i.price) AS minimum_recorded_price_brl,max(i.price) AS maximum_recorded_price_brl,
        avg(i.price) AS mean_recorded_price_brl,market.order_count AS marketplace_orders,
        market.unit_count AS marketplace_units,feedback.review_count,feedback.average_review_score
        """
            + ORDER_FROM
            + """ JOIN olist_demo.items i USING(order_id)
        JOIN olist_demo.products p USING(product_id)
        JOIN olist_demo.product_aliases pa USING(product_id)
        LEFT JOIN olist_demo.categories ct USING(product_category_name)
        CROSS JOIN LATERAL (
            SELECT count(DISTINCT mi.order_id) AS order_count,count(*) AS unit_count
            FROM olist_demo.items mi WHERE mi.product_id=p.product_id
        ) market
        CROSS JOIN LATERAL (
            SELECT count(*) AS review_count,avg(rv.review_score) AS average_review_score
            FROM (SELECT DISTINCT r.source_row,r.review_score
                  FROM olist_demo.reviews r JOIN olist_demo.items ri USING(order_id)
                  WHERE ri.product_id=p.product_id) rv
        ) feedback
        WHERE pa.alias=%s AND """
            + SCOPE
            + """ GROUP BY pa.alias,
        ct.product_category_name_english,p.product_category_name,p.product_weight_g,
        p.product_length_cm,p.product_height_cm,p.product_width_cm,p.product_photos_qty,
        p.product_name_lenght,p.product_description_lenght,market.order_count,
        market.unit_count,feedback.review_count,feedback.average_review_score""",
            (alias,),
        ),
        "product attributes, account-observed historical prices and whole-dataset popularity/review statistics; no current catalog price",
    )


def order_lookup(alias: str) -> str:
    account = _account()
    with connection() as conn:
        row = conn.execute(
            """
            SELECT oa.alias,o.order_status,o.order_purchase_timestamp,
                   o.order_delivered_customer_date,o.order_estimated_delivery_date,
                   count(i.order_item_id),COALESCE(sum(i.price),0),COALESCE(sum(i.freight_value),0),
                   count(DISTINCT i.seller_id)
            FROM olist_demo.order_aliases oa
            JOIN olist_demo.orders o USING(order_id)
            JOIN olist_demo.customers c USING(customer_id)
            LEFT JOIN olist_demo.items i USING(order_id)
            WHERE oa.alias=%s AND c.customer_unique_id=(SELECT customer_unique_id FROM olist_demo.accounts WHERE alias=%s)
            GROUP BY oa.alias,o.order_status,o.order_purchase_timestamp,o.order_delivered_customer_date,o.order_estimated_delivery_date
        """,
            (alias, account),
        ).fetchone()
    if not row:
        return "No order with that reference was found for the selected demo account."
    names = [
        "Order reference",
        "Recorded historical status",
        "Purchase date",
        "Recorded delivery date",
        "Estimated delivery date",
        "Item count",
        "Items total (BRL)",
        "Recorded freight total (BRL)",
        "Seller count",
    ]
    values = [
        row[0],
        row[1],
        *(str(x) if x is not None else "not recorded" for x in row[2:5]),
        str(row[5]),
        f"{row[6]:.2f}",
        f"{row[7]:.2f}",
        str(row[8]),
    ]
    return (
        "; ".join(f"{n}: {v}" for n, v in zip(names, values))
        + ". This is historical dataset information, not live tracking or an action confirmation."
    )


def order_history() -> str:
    account = _account()
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT oa.alias,o.order_status,o.order_purchase_timestamp,count(*) OVER()
            FROM olist_demo.orders o JOIN olist_demo.customers c USING(customer_id)
            JOIN olist_demo.order_aliases oa USING(order_id)
            WHERE c.customer_unique_id=(SELECT customer_unique_id FROM olist_demo.accounts WHERE alias=%s)
            ORDER BY o.order_purchase_timestamp DESC LIMIT 20
        """,
            (account,),
        ).fetchall()
    if not rows:
        return "No historical orders are available for this demo account."
    return (
        f"Historical purchase frequency: {rows[0][3]} orders in the recorded dataset; showing up to 20 newest orders: "
        + "; ".join(f"{r[0]}: {r[1]} (purchased {r[2]})" for r in rows)
        + "."
    )


def product_lookup(alias: str) -> str:
    account = _account()
    with connection() as conn:
        row = conn.execute(
            """
            SELECT pa.alias,p.product_category_name,ct.product_category_name_english,
                   count(DISTINCT i.order_id),COALESCE(avg(i.price),0),count(DISTINCT i.seller_id)
            FROM olist_demo.product_aliases pa JOIN olist_demo.products p USING(product_id)
            LEFT JOIN olist_demo.categories ct USING(product_category_name)
            LEFT JOIN olist_demo.items i USING(product_id)
            JOIN olist_demo.orders o USING(order_id)
            JOIN olist_demo.customers c USING(customer_id)
            WHERE pa.alias=%s AND c.customer_unique_id=(SELECT customer_unique_id FROM olist_demo.accounts WHERE alias=%s)
            GROUP BY pa.alias,p.product_category_name,ct.product_category_name_english
        """,
            (alias, account),
        ).fetchone()
    if not row:
        return "No product record associated with this demo account was found."
    return f"Historical product {row[0]}; category {row[2] or row[1] or 'not recorded'}; observed in {row[3]} of this account's orders; mean recorded item price BRL {row[4]:.2f}; sellers {row[5]}. Historical dataset information only."


def payment_summary(alias: str) -> str:
    account = _account()
    with connection() as conn:
        row = conn.execute(
            """
            SELECT oa.alias,count(p.payment_sequential),COALESCE(sum(p.payment_value),0),
                   string_agg(DISTINCT p.payment_type,', ' ORDER BY p.payment_type)
            FROM olist_demo.order_aliases oa JOIN olist_demo.orders o USING(order_id)
            JOIN olist_demo.customers c USING(customer_id) LEFT JOIN olist_demo.payments p USING(order_id)
            WHERE oa.alias=%s AND c.customer_unique_id=(SELECT customer_unique_id FROM olist_demo.accounts WHERE alias=%s)
            GROUP BY oa.alias
        """,
            (alias, account),
        ).fetchone()
    if not row:
        return "No order with that reference was found for the selected demo account."
    return f"Historical payment summary for {row[0]}: {row[1]} recorded payment entries totaling BRL {row[2]:.2f}; methods {row[3] or 'not recorded'}. This does not verify a live charge or issue a refund."


def review_lookup(alias: str) -> str:
    account = _account()
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT oa.alias,r.review_score,r.review_creation_date,r.review_answer_timestamp
            FROM olist_demo.order_aliases oa JOIN olist_demo.orders o USING(order_id)
            JOIN olist_demo.customers c USING(customer_id) JOIN olist_demo.reviews r USING(order_id)
            WHERE oa.alias=%s AND c.customer_unique_id=(SELECT customer_unique_id FROM olist_demo.accounts WHERE alias=%s)
            ORDER BY r.review_creation_date DESC LIMIT 10
        """,
            (alias, account),
        ).fetchall()
    if not rows:
        return "No review score is available for that order in this demo account."
    return (
        f"Recorded historical review score(s) for {alias} (scale 1–5): "
        + "; ".join(
            f"{r[1]} created {r[2] or 'unknown date'}, answered {r[3] or 'unknown date'}"
            for r in rows
        )
        + ". Review text is not included."
    )
