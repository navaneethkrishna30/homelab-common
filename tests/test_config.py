from pathlib import Path

import pytest
from pydantic import ValidationError

from homelab_common import CommonSettings, load_config

REQUIRED_ENV: dict[str, str] = {
    "SERVICE_NAME": "tasks",
    "PUBLIC_PATH": "/tasks",
    "DATABASE_HOST": "172.29.0.1",
    "DATABASE_SCHEMA": "tasks",
    "DATABASE_USER": "tasks",
    "DATABASE_PASSWORD": "pw",
}


class Settings(CommonSettings):
    reminder_lead: int = 15


def use_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    monkeypatch.setenv("HOMELAB_CONFIG_FILE", str(path))


@pytest.fixture(autouse=True)
def required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)


def test_env_beats_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use_yaml(monkeypatch, tmp_path, "reminder_lead: 30\n")
    monkeypatch.setenv("REMINDER_LEAD", "20")
    assert load_config(Settings).reminder_lead == 20


def test_yaml_used_when_env_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use_yaml(monkeypatch, tmp_path, "reminder_lead: 30\n")
    assert load_config(Settings).reminder_lead == 30


def test_missing_file_means_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOMELAB_CONFIG_FILE", str(tmp_path / "absent.yaml"))
    assert load_config(Settings).reminder_lead == 15


def test_unknown_yaml_key_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use_yaml(monkeypatch, tmp_path, "remnder_lead: 30\n")
    with pytest.raises(ValidationError):
        load_config(Settings)


def test_missing_required_value_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use_yaml(monkeypatch, tmp_path, "")
    monkeypatch.delenv("DATABASE_HOST")
    with pytest.raises(ValidationError):
        load_config(Settings)


def test_database_url_encodes_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use_yaml(monkeypatch, tmp_path, "")
    monkeypatch.setenv("DATABASE_PASSWORD", "p@:/w")
    url = load_config(Settings).database_url
    assert url == "postgresql+asyncpg://tasks:p%40%3A%2Fw@172.29.0.1:5432/homelab"


def test_host_name_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use_yaml(monkeypatch, tmp_path, "")
    monkeypatch.setenv("HOST_NAME", "veronica")
    assert load_config(Settings).host_name == "veronica"
