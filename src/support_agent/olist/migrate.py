"""Explicit Olist schema migration. No web-startup migrations or data imports."""

import psycopg

from support_agent.config import get_settings
from support_agent.olist.schema import migrate


def main():
    settings = get_settings()
    if not settings.persistence_enabled:
        raise RuntimeError("Set PERSISTENCE_ENABLED=1 before applying database migrations.")
    with psycopg.connect(settings.database_url, connect_timeout=10) as conn:
        migrate(conn)
    print("Olist schema migration applied.")


if __name__ == "__main__":
    main()
