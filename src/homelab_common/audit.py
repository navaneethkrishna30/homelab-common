"""The audit log: one append-only `common.audit` table, written in the caller's transaction."""

import ipaddress
import json
import re
from datetime import date, datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Literal

from opentelemetry import trace
from pydantic import BaseModel, JsonValue
from sqlalchemy import BigInteger, DateTime, Identity, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm import class_mapper as _class_mapper

from homelab_common import context

Result = Literal["ok", "denied", "failed", "pending"]

_MASKED = re.compile(r"password|token|secret|key|code|pin", re.IGNORECASE)
_MAX_JSON_BYTES = 8 * 1024
_service_name: str | None = None


class _AuditBase(DeclarativeBase):
    """Separate from any service's models so a service's Alembic never sees `common.audit`."""


class AuditEvent(_AuditBase):
    __tablename__ = "audit"
    __table_args__ = {"schema": "common"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    service: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(40))
    actor_detail: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    device: Mapped[str | None] = mapped_column(String(64))
    source_ip: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)
    turn_id: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    span_id: Mapped[str | None] = mapped_column(String(16))
    target_kind: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(120))
    before: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    result: Mapped[str] = mapped_column(String(12))
    error: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(String(200))
    extra: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)


def configure(service_name: str) -> None:
    """Name the writer (the `service` column); called once by `create_app`."""
    global _service_name
    _service_name = service_name


def changes(before: object | None, after: object | None) -> dict[str, JsonValue]:
    """The fields of `after` whose value differs from `before`, secrets masked.

    With `before=None` every field of `after` is returned (a creation). For the before side of an
    update call it the other way round: `changes(after, before)`.
    """
    new = _snapshot(after)
    old = _snapshot(before)
    return _mask({key: value for key, value in new.items() if key not in old or old[key] != value})


def build_event(
    *,
    action: str,
    target: tuple[str, str] | None = None,
    before: dict[str, JsonValue] | None = None,
    after: dict[str, JsonValue] | None = None,
    result: Result = "ok",
    error: str | None = None,
    summary: str | None = None,
    extra: dict[str, JsonValue] | None = None,
) -> AuditEvent:
    """Assemble one audit row from the arguments, the current call context and the current span."""
    call = context.current.get()
    span = trace.get_current_span().get_span_context()
    return AuditEvent(
        service=_service_name or "unknown",
        action=_fit(action, 80),
        actor=_fit(call.actor, 40),
        device=call.device and _fit(call.device, 64),
        source_ip=ipaddress.ip_address(call.source_ip) if call.source_ip else None,
        turn_id=call.turn_id and _fit(call.turn_id, 64),
        trace_id=f"{span.trace_id:032x}" if span.is_valid else None,
        span_id=f"{span.span_id:016x}" if span.is_valid else None,
        target_kind=_fit(target[0], 40) if target else None,
        target_id=_fit(target[1], 120) if target else None,
        before=_capped(before),
        after=_capped(after),
        result=result,
        error=error and _fit(error, 500),
        summary=summary and _fit(summary, 200),
        extra=extra,
    )


async def record(
    session: AsyncSession,
    *,
    action: str,
    target: tuple[str, str] | None = None,
    before: dict[str, JsonValue] | None = None,
    after: dict[str, JsonValue] | None = None,
    result: Result = "ok",
    error: str | None = None,
    summary: str | None = None,
    extra: dict[str, JsonValue] | None = None,
) -> None:
    """Add one audit row to the caller's transaction (it commits or rolls back with the change)."""
    session.add(
        build_event(
            action=action,
            target=target,
            before=before,
            after=after,
            result=result,
            error=error,
            summary=summary,
            extra=extra,
        )
    )
    await session.flush()


def _snapshot(obj: object | None) -> dict[str, JsonValue]:
    """A JSON-safe dict of an ORM row or a Pydantic model."""
    if obj is None:
        return {}
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    mapper = _class_mapper(type(obj))
    return {attr.key: _jsonable(getattr(obj, attr.key)) for attr in mapper.column_attrs}


def _jsonable(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _mask(fields: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: "***" if _MASKED.search(key) else value for key, value in fields.items()}


def _capped(fields: dict[str, JsonValue] | None) -> dict[str, JsonValue] | None:
    """Replace a payload over 8 KiB by a marker that names the fields."""
    if fields is None:
        return None
    size = len(json.dumps(fields).encode())
    if size <= _MAX_JSON_BYTES:
        return fields
    return {"_truncated": True, "bytes": size, "fields": list(fields)}


def _fit(value: str, length: int) -> str:
    return value[:length]
