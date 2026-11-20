"""create_app: health, ready, the ASGI middleware and the MCP mount (SPEC sections 4 and 8)."""

import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import httpx2
import pytest
from fastapi import APIRouter, FastAPI
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from opentelemetry.sdk.metrics.export import (
    Histogram,
    HistogramDataPoint,
    InMemoryMetricReader,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import format_trace_id
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.types import Message
from test_db import settings_for

from homelab_common import CommonSettings, context, create_app, db, telemetry, tool
from homelab_common import app as app_module

ONE_MIGRATION = (
    '"""the only migration"""\n'
    'revision = "0001"\n'
    "down_revision = None\n"
    "branch_labels = None\n"
    "depends_on = None\n"
    "\n"
    "\n"
    "def upgrade() -> None:\n"
    "    pass\n"
    "\n"
    "\n"
    "def downgrade() -> None:\n"
    "    pass\n"
)


class Actor(BaseModel):
    name: str


router = APIRouter()


@router.get("/notes/{note_id}")
async def note(note_id: int) -> Actor:
    return Actor(name=context.current.get().actor)


@router.get("/whoami")
async def whoami() -> Actor:
    return Actor(name=context.current.get().actor)


@router.get("/boom")
async def boom() -> Actor:
    raise ValueError("boom")


@tool
async def mcp_greet(name: str) -> Actor:
    """Return the caller and the given name."""
    return Actor(name=f"{context.current.get().actor}:{name}")


async def plain() -> Actor:
    return Actor(name="x")


@pytest.fixture(autouse=True)
async def reset_state() -> AsyncGenerator[None]:
    yield
    await db.dispose()
    await telemetry.shutdown()


def app_settings() -> CommonSettings:
    """Settings whose database is never reached; the unit tests never touch it."""
    return settings_for("postgresql+asyncpg://u:x@127.0.0.1:1/none", "apptest")


def app_client(app: FastAPI) -> httpx.AsyncClient:
    """An httpx client that talks to the app in-process."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def http_points(reader: InMemoryMetricReader, route: str) -> list[HistogramDataPoint]:
    """Every http.server.request.duration point recorded for one route template."""
    data = reader.get_metrics_data()
    assert data is not None
    return [
        point
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == "http.server.request.duration" and isinstance(metric.data, Histogram)
        for point in metric.data.data_points
        if point.attributes is not None and point.attributes.get("http.route") == route
    ]


class JsonLines(logging.Handler):
    """Capture log lines as the app's own logger formats them, inside the live span."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(telemetry.JsonFormatter().format(record))


@asynccontextmanager
async def lifespan_running(app: FastAPI) -> AsyncGenerator[None]:
    """Drive the ASGI lifespan protocol the way uvicorn does, for one test."""
    startup_pending = True
    startup_complete = asyncio.Event()
    release = asyncio.Event()
    failure: dict[str, str | None] = {"message": None}

    async def receive() -> Message:
        nonlocal startup_pending
        if startup_pending:
            startup_pending = False
            return {"type": "lifespan.startup"}
        await release.wait()
        return {"type": "lifespan.shutdown"}

    async def send(message: Message) -> None:
        kind = message["type"]
        if kind == "lifespan.startup.complete":
            startup_complete.set()
        elif kind == "lifespan.startup.failed":
            failure["message"] = message.get("message")
            startup_complete.set()

    task = asyncio.create_task(app({"type": "lifespan", "state": {}}, receive, send))
    await startup_complete.wait()
    if failure["message"] is not None:
        await task
        raise RuntimeError(f"lifespan startup failed: {failure['message']}")
    try:
        yield
    finally:
        release.set()
        await task


async def test_health_is_200_without_a_database() -> None:
    app = create_app("apptest", app_settings(), routers=[], tools=[])
    async with app_client(app) as client:
        response = await client.get("/health")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


async def test_ready_is_503_when_the_database_is_unreachable() -> None:
    app = create_app("apptest", app_settings(), routers=[], tools=[])
    await db.dispose()  # ping() answers False with the engine unset
    async with app_client(app) as client:
        response = await client.get("/ready")
    assert (response.status_code, response.json()) == (
        503,
        {"status": "not ready", "reason": "database unreachable"},
    )


async def test_route_template_on_the_histogram_and_span(
    spans: InMemorySpanExporter, metric_reader: InMemoryMetricReader
) -> None:
    app = create_app("apptest", app_settings(), routers=[router], tools=[])
    async with app_client(app) as client:
        response = await client.get("/notes/7")
    assert response.status_code == 200
    assert len(http_points(metric_reader, "/notes/{note_id}")) == 1
    assert http_points(metric_reader, "/notes/7") == []
    matching = [span for span in spans.get_finished_spans() if span.name == "GET /notes/{note_id}"]
    assert len(matching) == 1
    assert matching[0].attributes is not None
    assert matching[0].attributes["http.route"] == "/notes/{note_id}"
    assert matching[0].attributes["url.path"] == "/notes/7"


async def test_actor_header_reaches_the_call_context_in_a_route() -> None:
    app = create_app("apptest", app_settings(), routers=[router], tools=[])
    async with app_client(app) as client:
        response = await client.get("/whoami", headers={"X-Homelab-Actor": "agent:builder"})
    assert response.json() == {"name": "agent:builder"}
    # The middleware resets the call context once the request is done.
    assert context.current.get().actor == "unknown"


async def test_health_and_ready_are_neither_traced_nor_counted(
    spans: InMemorySpanExporter, metric_reader: InMemoryMetricReader
) -> None:
    app = create_app("apptest", app_settings(), routers=[router], tools=[])
    await db.dispose()
    async with app_client(app) as client:
        await client.get("/health")
        await client.get("/ready")
    assert http_points(metric_reader, "/health") == []
    assert http_points(metric_reader, "/ready") == []
    names = [span.name for span in spans.get_finished_spans()]
    assert "GET /health" not in names
    assert "GET /ready" not in names


async def test_unhandled_exception_is_a_500_and_records_error_type(
    spans: InMemorySpanExporter, metric_reader: InMemoryMetricReader
) -> None:
    app = create_app("apptest", app_settings(), routers=[router], tools=[])
    capture = JsonLines()
    app_module.logger.addHandler(capture)
    try:
        async with app_client(app) as client:
            response = await client.get("/boom")
    finally:
        app_module.logger.removeHandler(capture)
    assert (response.status_code, response.json()) == (500, {"detail": "internal error"})
    points = http_points(metric_reader, "/boom")
    assert len(points) == 1
    assert points[0].attributes is not None
    assert points[0].attributes["http.response.status_code"] == 500
    assert points[0].attributes["error.type"] == "ValueError"
    assert len(capture.lines) == 1
    payload = json.loads(capture.lines[0])
    assert payload["body"] == "unhandled ValueError in GET /boom"
    assert payload["severity"] == "ERROR"
    boom = [span for span in spans.get_finished_spans() if span.name == "GET /boom"]
    assert len(boom) == 1
    span_context = boom[0].get_span_context()
    assert span_context is not None
    assert payload["trace_id"] == format_trace_id(span_context.trace_id)


async def test_unmatched_request_is_named_and_counted_unmatched(
    spans: InMemorySpanExporter, metric_reader: InMemoryMetricReader
) -> None:
    app = create_app("apptest", app_settings(), routers=[router], tools=[])
    async with app_client(app) as client:
        await client.get("/nope")
    unmatched = [span for span in spans.get_finished_spans() if span.name == "GET unmatched"]
    assert len(unmatched) == 1
    assert unmatched[0].attributes is not None
    assert "http.route" not in unmatched[0].attributes
    assert unmatched[0].attributes["url.path"] == "/nope"
    assert len(http_points(metric_reader, "unmatched")) == 1


def test_unregistered_tool_is_refused() -> None:
    with pytest.raises(TypeError, match="plain"):
        create_app("apptest", app_settings(), routers=[], tools=[plain])


async def test_mcp_mounted_and_serving_beside_rest() -> None:
    app = create_app("apptest", app_settings(), routers=[], tools=[mcp_greet])
    async with lifespan_running(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport) as http:
            async with streamable_http_client(
                "http://svc.fin-alkaline.ts.net/mcp", http_client=http
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    result = await session.initialize()
                    tools = await session.list_tools()
    assert result.server_info.name == "apptest"
    assert [tool_info.name for tool_info in tools.tools] == ["mcp_greet"]


async def test_mcp_path_without_a_trailing_slash_is_not_redirected() -> None:
    """Behind Caddy a redirect would drop the service prefix, so /mcp must answer itself."""
    app = create_app("apptest", app_settings(), routers=[], tools=[mcp_greet])
    async with lifespan_running(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, follow_redirects=False) as http:
            response = await http.post(
                "http://svc.fin-alkaline.ts.net/mcp",
                headers={"accept": "application/json, text/event-stream"},
                json={},
            )
    assert response.status_code not in (307, 308)


@pytest.mark.integration
class TestReadyMigrations:
    """Needs a real Postgres in HOMELAB_TEST_DATABASE_URL."""

    @pytest.fixture
    async def url(self) -> AsyncGenerator[str]:
        url = os.environ.get("HOMELAB_TEST_DATABASE_URL")
        if url is None:
            pytest.skip("HOMELAB_TEST_DATABASE_URL not set")
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS apptest CASCADE"))
            await conn.execute(text("CREATE SCHEMA apptest"))
        yield url
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA apptest CASCADE"))
        await engine.dispose()
        await db.dispose()

    async def test_ready_follows_the_alembic_version_row(
        self, url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        versions = tmp_path / "migrations" / "versions"
        versions.mkdir(parents=True)
        (versions / "0001_one.py").write_text(ONE_MIGRATION)
        (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = migrations\n")
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.execute(
                text("CREATE TABLE apptest.alembic_version (version_num varchar(32) NOT NULL)")
            )
            await conn.execute(text("INSERT INTO apptest.alembic_version VALUES ('zzzz')"))
        await engine.dispose()
        monkeypatch.chdir(tmp_path)

        app = create_app("apptest", settings_for(url, "apptest"), routers=[], tools=[])
        async with app_client(app) as client:
            behind = await client.get("/ready")
        assert (behind.status_code, behind.json()) == (
            503,
            {"status": "not ready", "reason": "migrations behind: zzzz != 0001"},
        )

        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE apptest.alembic_version SET version_num = '0001'"))
        await engine.dispose()
        async with app_client(app) as client:
            ready = await client.get("/ready")
        assert (ready.status_code, ready.json()) == (200, {"status": "ready"})
