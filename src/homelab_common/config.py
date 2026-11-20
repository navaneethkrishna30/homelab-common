"""Service configuration: pydantic-settings from config/config.yaml plus the environment."""

import os
import socket
from typing import ClassVar
from urllib.parse import quote

from pydantic import Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class CommonSettings(BaseSettings):
    """Settings every service has; a service subclasses it with its own tunables."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(extra="forbid")

    # Field(default=...) stays required at run time; it tells pyright the constructor needs no
    # argument (values come from the environment and YAML).
    service_name: str = Field(default=...)
    public_path: str = Field(default=...)
    # The only host the MCP endpoint accepts: the mcp SDK's DNS-rebinding
    # protection rejects every other Host header with 421, which is what Caddy
    # forwards behind the Tailscale Service.
    public_host: str = "svc.fin-alkaline.ts.net"
    database_host: str = Field(default=...)
    database_port: int = 5432
    database_name: str = "homelab"
    database_schema: str = Field(default=...)
    database_user: str = Field(default=...)
    database_password: SecretStr = Field(default=...)
    db_pool_size: int = 5
    # The machine it runs on (the host_name label); the generated env fragment sets HOST_NAME.
    host_name: str = Field(default_factory=socket.gethostname)
    otlp_endpoint: str | None = Field(default=None, validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT")

    @property
    def database_url(self) -> str:
        user = quote(self.database_user, safe="")
        secret = quote(self.database_password.get_secret_value(), safe="")
        host = f"{self.database_host}:{self.database_port}"
        return f"postgresql+asyncpg://{user}:{secret}@{host}/{self.database_name}"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_file = os.environ.get("HOMELAB_CONFIG_FILE", "config/config.yaml")
        return (init_settings, env_settings, YamlConfigSettingsSource(settings_cls, yaml_file))


def load_config[S: CommonSettings](settings_cls: type[S]) -> S:
    """Load settings; raises pydantic's ValidationError on a typo or a missing value."""
    return settings_cls()
