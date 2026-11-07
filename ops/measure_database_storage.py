"""Run the approved read-only database/relation storage measurement query."""

from __future__ import annotations

import json

import psycopg

from support_agent.config import get_settings

QUERY = """WITH relation_sizes AS (
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
ORDER BY scope DESC, schema_name NULLS FIRST, relation_name NULLS FIRST"""


def main() -> None:
    settings = get_settings()
    # Server-side read-only mode adds a safety boundary without issuing another SQL statement.
    with psycopg.connect(
        settings.database_url,
        connect_timeout=10,
        options="-c default_transaction_read_only=on",
    ) as conn:
        cursor = conn.execute(QUERY)
        columns = [column.name for column in cursor.description]
        print(json.dumps([dict(zip(columns, row)) for row in cursor.fetchall()], indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - do not print a possibly secret-bearing DB exception
        print(
            f"Storage measurement failed ({type(error).__name__}); "
            "exception details were suppressed to protect credentials."
        )
        raise SystemExit(2) from None
