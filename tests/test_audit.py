import os
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from pydantic import BaseModel, JsonValue, SecretStr
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from homelab_common import CommonSettings, audit, db
from homelab_common.audit import AuditEvent
from homelab_common.context import CallContext, current


class Task(BaseModel):
    title: str
    due: date | None = None
    api_key: str = "k"


def test_changes_for_a_creation_returns_every_field() -> None:
    result = audit.changes(None, Task(title="a", due=date(2026, 1, 2)))
    assert result == {"title": "a", "due": "2026-01-02", "api_key": "***"}


def test_changes_for_an_update_returns_only_changed_fields() -> None:
    old = Task(title="a")
    new = Task(title="b")
    assert audit.changes(old, new) == {"title": "b"}
    assert audit.changes(new, old) == {"title": "a"}


def test_changes_without_a_difference_is_empty() -> None:
    assert audit.changes(Task(title="a"), Task(title="a")) == {}


def test_masking_is_case_insensitive_substring() -> None:
    class Login(BaseModel):
        UserPassword: str = "p"
        auth_token: str = "t"
        pin: str = "1"
        title: str = "visible"

    assert audit.changes(None, Login()) == {
        "UserPassword": "***",
        "auth_token": "***",
        "pin": "***",
        "title": "visible",
    }


def test_oversized_payload_is_replaced_by_a_marker() -> None:
    big: dict[str, JsonValue] = {"notes": "x" * 9000, "title": "t"}
    event = audit.build_event(action="task.add", after=big)
    assert event.after is not None
    assert event.after["_truncated"] is True
    assert event.after["fields"] == ["notes", "title"]


def test_event_takes_actor_device_and_ip_from_the_call_context() -> None:
    audit.configure("tasks")
    headers = {
        "x-homelab-actor": "agent:builder",
        "x-homelab-device": "d1",
        "x-forwarded-for": "100.64.0.9, 10.0.0.1",
    }
    token = current.set(CallContext.from_headers(headers))
    try:
        event = audit.build_event(action="task.add", target=("task", "7"), summary="Added")
    finally:
        current.reset(token)
    assert (event.service, event.actor, event.device, str(event.source_ip)) == (
        "tasks",
        "agent:builder",
        "d1",
        "100.64.0.9",
    )
    assert (event.target_kind, event.target_id, event.result) == ("task", "7", "ok")


def test_long_text_is_cut_to_the_column_size() -> None:
    event = audit.build_event(action="a" * 200, summary="s" * 300, error="e" * 900)
    assert (len(event.action), len(event.summary or ""), len(event.error or "")) == (80, 200, 500)


def test_actor_comes_from_the_header_first() -> None:
    headers = {"x-homelab-actor": "jarvis", "tailscale-user-login": "n@x"}
    assert CallContext.from_headers(headers).actor == "jarvis"


def test_a_tailscale_login_without_actor_header_is_nav() -> None:
    assert CallContext.from_headers({"tailscale-user-login": "n@x"}).actor == "nav"


def test_no_identity_is_unknown() -> None:
    assert CallContext.from_headers({}).actor == "unknown"


def test_a_bad_forwarded_address_is_dropped() -> None:
    assert CallContext.from_headers({"x-forwarded-for": "not-an-ip"}).source_ip is None


@pytest.mark.integration
class TestWithPostgres:
    """Needs `platform/sql/*.sql` applied to the database in HOMELAB_TEST_DATABASE_URL."""

    @pytest.fixture
    async def url(self) -> AsyncGenerator[str]:
        url = os.environ.get("HOMELAB_TEST_DATABASE_URL")
        if url is None:
            pytest.skip("HOMELAB_TEST_DATABASE_URL not set")
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM common.audit WHERE service = 'audittest'"))
        await engine.dispose()
        yield url
        await db.dispose()

    async def test_row_is_written_with_the_change_and_rolled_back_with_it(self, url: str) -> None:
        parsed = make_url(url)
        db.init(
            CommonSettings(
                service_name="audittest",
                public_path="/audittest",
                database_host=parsed.host or "",
                database_port=parsed.port or 5432,
                database_schema="public",
                database_user=parsed.username or "",
                database_password=SecretStr(parsed.password or ""),
            )
        )
        audit.configure("audittest")
        token = current.set(CallContext.from_headers({"x-forwarded-for": "100.64.0.9"}))
        try:
            async with db.session() as s:
                await audit.record(
                    s,
                    action="task.add",
                    target=("task", "1"),
                    after=audit.changes(None, Task(title="a")),
                    summary="Added a",
                )
            with pytest.raises(ValueError, match="boom"):
                async with db.session() as s:
                    await audit.record(s, action="task.rolled_back")
                    raise ValueError("boom")
        finally:
            current.reset(token)
        async with db.session() as s:
            rows = (
                (await s.execute(select(AuditEvent).where(AuditEvent.service == "audittest")))
                .scalars()
                .all()
            )
        assert [row.action for row in rows] == ["task.add"]
        assert rows[0].after == {"title": "a", "due": None, "api_key": "***"}
        assert str(rows[0].source_ip) == "100.64.0.9"
        assert rows[0].result == "ok"
