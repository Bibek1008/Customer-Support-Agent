"""Reject ambiguous/nonlocal integration targets before opening a connection."""

import re

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict


def test_database_parameters(url: str) -> dict:
    """Require an explicit loopback-only test DSN, never a production fallback."""
    if not url:
        raise ValueError("SUPPORT_TEST_DATABASE_URL must explicitly identify an isolated database")
    try:
        parameters = conninfo_to_dict(url)
    except ProgrammingError:
        raise ValueError("Invalid isolated test database configuration") from None
    if (
        parameters.get("host") not in {"127.0.0.1", "::1"}
        or parameters.get("hostaddr", parameters.get("host")) != parameters.get("host")
        or not re.fullmatch(r"[A-Za-z0-9_]+_test", parameters.get("dbname", ""))
        or not parameters.get("user")
        or not parameters.get("password")
        or not parameters.get("port", "").isdigit()
        or "service" in parameters
    ):
        raise ValueError(
            "Integration tests require explicit loopback host, port, test database and dedicated credentials"
        )
    # Prevent inherited PGHOSTADDR from redirecting even an explicit local host.
    parameters["hostaddr"] = parameters["host"]
    return parameters


def verify_database_identity(connection, target: dict) -> None:
    """Check the client endpoint and server identity across local port forwarding."""
    actual = connection.execute("SELECT current_database(), current_user").fetchone()
    # inet_server_addr()/port() describe the container side of a forwarded
    # connection. libpq reports the endpoint that this client actually used.
    if (
        actual != (target["dbname"], target["user"])
        or connection.info.hostaddr != target["hostaddr"]
        or connection.info.port != int(target["port"])
    ):
        raise ValueError("Isolated test database identity did not match the explicit target")
