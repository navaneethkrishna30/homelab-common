"""The `service.yaml` schema: parsed by the library, imported by the generator (SPEC section 5)."""

from pathlib import Path
from typing import Annotated, ClassVar, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SecretName = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]


class _StrictModel(BaseModel):
    """A `service.yaml` node: unknown fields are errors and instances never change."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class RunSpec(_StrictModel):
    port: int = 8000
    network: Literal["homelab", "host"] = "homelab"
    env: list[SecretName] = Field(default_factory=list)


class DatabaseSpec(_StrictModel):
    # `schema` shadows BaseModel.schema, so the attribute is `schema_name` and `schema` is its
    # service.yaml alias.
    schema_name: str = Field(alias="schema", pattern=r"^[a-z_][a-z0-9_]*$")


class GatewaySpec(_StrictModel):
    # ServiceSpec fills this from `name` when the spec omits it.
    path: str = ""

    @field_validator("path")
    @classmethod
    def _is_absolute_and_not_a_prefix(cls, path: str) -> str:
        if not path.startswith("/") or path.endswith("/"):
            raise ValueError("must start with '/' and must not end with '/'")
        return path


class McpSpec(_StrictModel):
    enabled: bool = False
    path: str = "/mcp"
    profiles: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=lambda: ["*"])


class TelemetrySpec(_StrictModel):
    otlp: bool = True


class BootSpec(_StrictModel):
    heal: bool = True
    units: list[str] = Field(default_factory=list)


class ServiceSpec(_StrictModel):
    api_version: Literal["homelab/v1"] = Field(alias="apiVersion")
    name: str = Field(pattern=r"^[a-z]([a-z0-9-]{0,38}[a-z0-9])?$")
    title: str
    description: str
    repo: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    run: RunSpec = Field(default_factory=RunSpec)
    database: DatabaseSpec | None = None
    gateway: GatewaySpec = Field(default_factory=GatewaySpec)
    mcp: McpSpec = Field(default_factory=McpSpec)
    telemetry: TelemetrySpec = Field(default_factory=TelemetrySpec)
    boot: BootSpec = Field(default_factory=BootSpec)

    @model_validator(mode="after")
    def _default_gateway_path(self) -> Self:
        """`gateway.path` defaults to `/<name>`."""
        if self.gateway.path:
            return self
        gateway = self.gateway.model_copy(update={"path": f"/{self.name}"})
        return self.model_copy(update={"gateway": gateway})


def load_service_spec(path: Path) -> ServiceSpec:
    """Read and validate a `service.yaml`; pydantic's ValidationError is raised unchanged."""
    raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ServiceSpec.model_validate(raw)
