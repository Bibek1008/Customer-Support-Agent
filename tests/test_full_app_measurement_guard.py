import pytest

from ops.measure_full_app import validate_test_database_url


def test_full_app_measurement_accepts_only_dedicated_local_test_database():
    assert validate_test_database_url(
        "postgresql://support:support@127.0.0.1:5433/support_agent_test"
    ) == ("127.0.0.1", 5433, "support_agent_test")


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:secret@neon.example/support_agent_test",
        "postgresql://support:support@127.0.0.1:5432/support_agent_test",
        "postgresql://support:support@127.0.0.1:5433/postgres",
        "postgresql://support:support@127.0.0.1:5433/support_agent_test?host=neon.example",
        "postgresql://support:support@example.com:5433/support_agent_test",
    ],
)
def test_full_app_measurement_refuses_non_disposable_database_targets(database_url):
    with pytest.raises(ValueError, match="Refusing DB URL"):
        validate_test_database_url(database_url)
