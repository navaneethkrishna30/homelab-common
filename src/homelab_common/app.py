"""The service app: create_app wires config, database, audit, telemetry, REST and MCP."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.telemetry import TelemetryConfig
from fastmcp.utilities.lifespan import combine_lifespans
from opentelemetry import propagate
from opentelemetry.trace import SpanKind
from pydantic import BaseModel
from sqlalchemy import text
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from homelab_common import audit, context, db, telemetry
from homelab_common.config import CommonSettings
from homelab_common.tool import mcp_app, mcp_server

logger = logging.getLogger(__name__)

_ALEMBIC_INI = Path("alembic.ini")

# FastAPI's native HTTP telemetry is off here: SPEC section 8 makes the
# library's middleware the single owner of request spans and duration metrics,
# including the /health and /ready exclusions. Same idea as FastMCP's
# propagation_only mode, which mcp_server() sets for the MCP side.
_NO_NATIVE_TELEMETRY: TelemetryConfig = {
    "tracing": False,
    "metrics": False,
    "logs": False,
    "operation_spans": False,
}


class Health(BaseModel):
    """GET /health answers with the process up; it never touches the database."""

    status: str = "ok"


class Ready(BaseModel):
    """GET /ready answers with the database reachable and migrations current."""

    status: str = "ready"
    reason: str | None = None


Background = Callable[[], Awaitable[None]]


def _lifespan_with(
    background: Sequence[Background],
) -> Callable[[Starlette], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None]:
        """Run the background loops while the app serves; then take down what create_app set up."""
        tasks = [asyncio.create_task(_guarded(job), name=job.__name__) for job in background]
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await db.dispose()
        await telemetry.shutdown()

    return lifespan


async def _guarded(job: Background) -> None:
    """A background loop that raises is logged and started again a minute later, never left dead."""
    while True:
        try:
            await job()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("background job %s failed; restarting in 60 s", job.__name__)
            await asyncio.sleep(60)


def create_app(
    name: str,
    cfg: CommonSettings,
    *,
    routers: Sequence[APIRouter],
    tools: Sequence[Callable[..., Awaitable[object]]],
    background: Sequence[Background] = (),
) -> FastAPI:
    """Build one service app (SPEC section 4): the routers as REST, the tools as MCP.

    `background`: long-running loops (a schedule, a reaper) started with the app and cancelled on
    shutdown; one that raises is restarted after a minute.
    """
    mcp_http_app = mcp_app(mcp_server(name, tools), cfg.public_host) if tools else None
    telemetry.setup(cfg)
    db.init(cfg)
    audit.configure(name)

    own = _lifespan_with(background)
    lifespan = own if mcp_http_app is None else combine_lifespans(own, mcp_http_app.lifespan)
    app = FastAPI(lifespan=lifespan, telemetry=_NO_NATIVE_TELEMETRY)
    app.add_middleware(_Instrument)
    for router in routers:
        app.include_router(router)

    @app.get("/health", response_model=Health)
    async def health() -> Health:
        return Health()

    @app.get("/ready", response_model=Ready, response_model_exclude_none=True)
    async def ready() -> Ready | JSONResponse:
        reason = await _not_ready_reason(cfg.database_schema)
        if reason is not None:
            return JSONResponse(
                Ready(status="not ready", reason=reason).model_dump(), status_code=503
            )
        return Ready()

    if mcp_http_app is not None:
        app.mount("/", mcp_http_app)  # answers at exactly /mcp, never a redirect (see tool.mcp_app)
    return app


async def _not_ready_reason(schema: str) -> str | None:
    """None when the service is ready; otherwise the reason for the 503."""
    if not await db.ping():
        return "database unreachable"
    head = _migrations_head()
    if head is None:
        return None
    current = await _current_revision(schema)
    if current != head:
        return f"migrations behind: {current or 'none'} != {head}"
    return None


def _migrations_head() -> str | None:
    """The head revision of the Alembic script directory, None without alembic.ini.

    The import stays inside the function: services without migrations never
    install Alembic, so importing it here keeps it out of their runtime.
    """
    if not _ALEMBIC_INI.is_file():
        return None
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(str(_ALEMBIC_INI))).get_current_head()


async def _current_revision(schema: str) -> str | None:
    """The applied revision in <schema>.alembic_version, None when migrations never ran."""
    try:
        async with db.session() as session:
            return (
                await session.execute(text(f"SELECT version_num FROM {schema}.alembic_version"))
            ).scalar()
    except Exception:
        return None


def _passes_through(scope: Scope) -> bool:
    """/health, /ready and everything under /mcp skip the middleware entirely."""
    path: str = scope["path"]
    return path == "/health" or path == "/ready" or path.startswith("/mcp")


class _Instrument:
    """Pure-ASGI middleware (SPEC sections 4 and 8), no BaseHTTPMiddleware.

    Every request except /health, /ready and /mcp* runs with the caller's
    identity in context.current, inside a SERVER span named after the route
    template, and is counted on the http.server.request.duration histogram.
    An unhandled exception becomes a 500 JSON response and one log line.
    Raw paths reach only the span (url.path); metric labels carry the template.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or _passes_through(scope):
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        method: str = scope["method"]
        headers = Headers(scope=scope)
        status_code: int | None = None
        route_path: str | None = None
        error_type: str | None = None

        async def tracked_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        context_reset = context.current.set(context.CallContext.from_headers(headers))
        started = time.perf_counter()
        try:
            with telemetry.tracer().start_as_current_span(
                f"{method} unmatched",
                context=propagate.extract(headers),
                kind=SpanKind.SERVER,
                attributes={"url.path": path},
            ) as span:
                try:
                    await self.app(scope, receive, tracked_send)
                except Exception as exc:
                    error_type = type(exc).__name__
                    logger.error("unhandled %s in %s %s", type(exc).__name__, method, path)
                    if status_code is None:
                        await JSONResponse(status_code=500, content={"detail": "internal error"})(
                            scope, receive, send
                        )
                        status_code = 500
                    else:
                        raise
                route = scope.get("route")
                if route is not None:
                    route_path = route.path
                    span.update_name(f"{method} {route_path}")
                    span.set_attribute("http.route", route_path)
        finally:
            context.current.reset(context_reset)
            if error_type is None and (status_code or 0) >= 500:
                error_type = str(status_code)
            telemetry.metrics().record_http_server(
                method,
                route_path or "unmatched",
                status_code or 500,
                time.perf_counter() - started,
                error_type,
            )
