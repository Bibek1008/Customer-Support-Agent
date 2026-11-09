"""Build public documentation from the offline preflight, without raw records."""

import json
from pathlib import Path

from support_agent.olist.dataset import DATES, NUMERIC

MEANINGS = {
    "customer_id": "Internal per-order customer join key; never displayed.",
    "customer_unique_id": "Internal customer identity across purchases; mapped to curated demo accounts.",
    "order_id": "Internal order join key; replaced by opaque demo-order reference in output.",
    "product_id": "Internal product join key; replaced by opaque demo-product reference.",
    "seller_id": "Internal seller join key; replaced by opaque demo-seller reference.",
    "review_id": "Source review identifier; not unique per source row; never displayed.",
    "customer_zip_code_prefix": "Source postal prefix retained as text to preserve leading zeroes; not shown in customer output.",
    "customer_city": "Source customer city retained for authorized regional analytics; not shown in customer output.",
    "customer_state": "Source customer state retained for authorized regional analytics; not shown in customer output.",
    "seller_zip_code_prefix": "Source postal prefix retained as text to preserve leading zeroes; not shown in public output.",
    "seller_city": "Source seller city retained for authorized regional analytics; not shown in public output.",
    "seller_state": "Seller Brazilian state code; broad region only, no contact information.",
    "order_status": "Recorded historical lifecycle status, including delivered/canceled/unavailable; never live tracking.",
    "order_purchase_timestamp": "Recorded purchase time; also used for order history and purchase frequency.",
    "order_approved_at": "Recorded payment approval time; nullable.",
    "order_delivered_carrier_date": "Recorded carrier handover time; nullable.",
    "order_delivered_customer_date": "Recorded customer delivery time; nullable; used for date difference.",
    "order_estimated_delivery_date": "Historical estimated delivery time; nullable; not a current promise.",
    "order_item_id": "Item sequence within an order; composite key permits multiple item lines.",
    "shipping_limit_date": "Recorded seller shipping deadline; not a current shipping promise.",
    "price": "Historical item price in BRL; multiple lines preserved; no live catalog price.",
    "freight_value": "Historical freight charge per item in BRL; separate from item price.",
    "payment_sequential": "Payment-entry sequence; multiple entries remain separate.",
    "payment_type": "Recorded payment method, including credit card, boleto and voucher.",
    "payment_installments": "Recorded installment count; no installment due-date schedule exists.",
    "payment_value": "Recorded payment-entry amount in BRL; not a live charge or refund ledger.",
    "product_category_name": "Original Portuguese category code; untranslated values retained.",
    "product_category_name_english": "Readable English category translation; incomplete source coverage.",
    "product_name_lenght": "Source-spelled name-length statistic; actual product names are unavailable.",
    "product_description_lenght": "Source-spelled description-length statistic; no actual description text.",
    "product_photos_qty": "Recorded count of product photos; no images or image URLs.",
    "product_weight_g": "Recorded product weight in grams; nullable.",
    "product_length_cm": "Recorded product length in centimeters; nullable.",
    "product_height_cm": "Recorded product height in centimeters; nullable.",
    "product_width_cm": "Recorded product width in centimeters; nullable.",
    "review_score": "Historical post-purchase score from 1 to 5; feedback, not policy.",
    "review_creation_date": "Recorded review creation date/time; nullable.",
    "review_answer_timestamp": "Recorded review response timestamp; not a support-agent reply.",
    "review_comment_title": "Untrusted comment title stored separately from review facts; unavailable to customer tools pending validated Portuguese PII redaction.",
    "review_comment_message": "Untrusted Portuguese feedback stored separately; never embedded or exposed before validated redaction and injection quarantine.",
    "geolocation_zip_code_prefix": "Source postal prefix retained as text, including leading zeroes; groups the aggregate lookup.",
    "geolocation_lat": "Source latitude preserved in the auditable raw table; ZIP-prefix centroid averages unique coordinate pairs.",
    "geolocation_lng": "Source longitude preserved in the auditable raw table; ZIP-prefix centroid averages unique coordinate pairs.",
    "geolocation_city": "Source city label preserved in the auditable raw table; not exposed through customer tools.",
    "geolocation_state": "Source state label preserved in the auditable raw table and aggregate state list.",
}


def main():
    report = json.loads(Path("docs/olist_preflight.json").read_text(encoding="utf-8"))
    lines = [
        "# Olist data dictionary and coverage",
        "",
        "Measured locally on 2026-11-09. All nine source CSVs were inspected. No database import ran.",
        "",
        "All source columns are mapped to relational tables. Review comments are stored separately from review scores. Geolocation raw rows remain auditable and the ZIP-prefix table is deduplicated. SQL facts and reviews never enter the policy vector store. Customer tools remain account-scoped. No current prices, names, live inventory, tracking numbers, official company terms or support transcripts are present.",
        "",
        "| Dataset | Rows | Source bytes | Exact duplicate rows | Selected columns |",
        "|---|---:|---:|---:|---:|",
    ]
    for table, t in report["tables"].items():
        lines.append(
            f"| {table} | {t['rows']:,} | {t['bytes']:,} | {t['duplicate_rows']:,} | {len(t['import_columns'])}/{len(t['columns'])} |"
        )
    lines.extend(
        [
            "",
            "Validation errors: " + str(report["errors"]),
            "",
            *report["warnings"],
            "",
            "All source fields map to the explicit version-3 import; this local report does not mean rows are already in Neon. Internal IDs are retained only for joins and authorization. Original CSV spelling `lenght` is preserved. Review comments use separate untrusted storage; geolocation raw rows and ZIP-prefix aggregates are retained.",
            "",
        ]
    )
    for table, t in report["tables"].items():
        lines.extend(
            [
                f"## {table}",
                "",
                f"Source: `{t['file']}`. SHA-256: `{t['sha256']}`.",
                "",
                "| Field | Value type | Empty rows | Coverage and meaning |",
                "|---|---|---:|---|",
            ]
        )
        for field in t["columns"]:
            kind = (
                "timestamp without timezone"
                if field in DATES
                else "numeric"
                if field in NUMERIC
                else "text"
            )
            coverage = "Prepared SQL column. " if field in t["import_columns"] else "Excluded. "
            lines.append(
                f"| `{field}` | {kind} | {t['nulls'].get(field, 0):,} | {coverage}{MEANINGS[field]} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Derived coverage and limits",
            "",
            "- Order history counts purchases by internal unique-customer identity; displayed orders use opaque references.",
            "- Product price ranges, sales and seller statistics use only selected-account observations; these are not marketplace totals.",
            "- Delivery difference uses actual minus estimated calendar date. Positive means late; delay is max(0, difference). Missing dates remain null. No timezone is invented.",
            "- Aggregate denominators include comparable orders and missing comparisons separately. Cancellation/unavailable counts use recorded statuses.",
            "- Multiple items and payment entries are queried separately to prevent item/payment join multiplication.",
            "- Reviews preserve source-row identity because review IDs and order IDs can recur; review timestamps are not support conversations.",
            "- Customer support chat history belongs exclusively to this application, outside the Olist schema.",
            "- Review comments remain untrusted, separate from review scores and unavailable to tools until Portuguese PII redaction is validated. The bounded first-200 risk sample is not representative.",
            "- Geolocation retains every source row for audit. Its internal ZIP-prefix lookup averages unique coordinate pairs; it is not a household address or delivery route and is not exposed to customers.",
            "",
        ]
    )
    Path("docs/OLIST_DATA_DICTIONARY.md").write_text("\n".join(lines), encoding="utf-8")
    print("Wrote docs/OLIST_DATA_DICTIONARY.md")


if __name__ == "__main__":
    main()
