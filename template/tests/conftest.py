import pytest


@pytest.fixture(autouse=True)
def service_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The values the generated env fragment and the secrets file provide at run time."""
    values = {
        "SERVICE_NAME": "test",
        "PUBLIC_PATH": "/test",
        "DATABASE_HOST": "127.0.0.1",
        "DATABASE_SCHEMA": "test",
        "DATABASE_USER": "test",
        "DATABASE_PASSWORD": "test",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
