"""Fixed, read-only Olist lookups constrained by the selected demo account."""

from support_agent.db import connection
from support_agent.request_context import current_request


def selected_account(conversation_id: str, owner_hash: str) -> str | None:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT a.alias FROM public.support_conversations c
            JOIN olist_demo.conversation_accounts ca ON ca.conversation_id=c.id
            JOIN olist_demo.accounts a ON a.alias=ca.account_alias
            WHERE c.id=%s AND c.owner_hash=%s AND c.kb_profile='olist_demo'
        """,
            (conversation_id, owner_hash),
        ).fetchone()
    return row[0] if row else None


def public_accounts() -> list[dict]:
    with connection() as conn:
        if not conn.execute("SELECT to_regclass('olist_demo.accounts')").fetchone()[0]:
            return []
        return conn.execute("SELECT alias,label FROM olist_demo.accounts ORDER BY alias").fetchall()


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
    if row[0] != "olist_demo" or not row[1]:
        return {"profile": "office_store"}
    orders = account_orders(conversation_id, owner_hash)
    return {
        "profile": row[0],
        "account": row[1],
        "orders": orders,
        "disclosure": "Olist Brazilian E-Commerce Public Dataset. Historical records only; no live customer, carrier, or support data.",
    }


def bind_account(conversation_id: str, owner_hash: str, alias: str) -> bool:
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
            SELECT oa.alias,o.order_status,o.order_purchase_timestamp
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
        "Historical orders (newest first): "
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
            SELECT oa.alias,r.review_score,r.review_creation_date
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
        + "; ".join(f"{r[1]} on {r[2] or 'unknown date'}" for r in rows)
        + ". Review text is not included."
    )
