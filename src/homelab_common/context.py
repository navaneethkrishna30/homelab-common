"""Who is calling: identity headers parsed once per request, read by `audit`."""

import ipaddress
from collections.abc import Mapping
from contextvars import ContextVar
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict


class CallContext(BaseModel):
    """The caller of the current request or tool call (SPEC sections 4 and 7)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    actor: str = "unknown"
    device: str | None = None
    source_ip: str | None = None
    turn_id: str | None = None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> Self:
        """Build the context from request headers (keys lower-case, as Starlette delivers them).

        `x-homelab-actor` carries the actor and is forwarded unchanged across hops; without it a
        Tailscale user login means `nav`; with neither the actor is `unknown`.
        """
        actor = headers.get("x-homelab-actor")
        if not actor:
            actor = "nav" if headers.get("tailscale-user-login") else "unknown"
        return cls(
            actor=actor,
            device=headers.get("x-homelab-device") or None,
            source_ip=_first_ip(headers.get("x-forwarded-for")),
            turn_id=headers.get("x-hermes-turn") or None,
        )


def _first_ip(forwarded_for: str | None) -> str | None:
    """The first address of an X-Forwarded-For value, or None when absent or not an address."""
    if not forwarded_for:
        return None
    first = forwarded_for.split(",")[0].strip()
    try:
        return str(ipaddress.ip_address(first))
    except ValueError:
        return None


_UNKNOWN_CALLER = CallContext()  # frozen, so safe to share as the default
current: ContextVar[CallContext] = ContextVar("homelab_call_context", default=_UNKNOWN_CALLER)
