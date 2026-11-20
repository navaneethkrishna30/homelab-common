"""MCP tools: the `tool` decorator, the FastMCP server builder and its HTTP app."""

import functools
import time
from collections.abc import Awaitable, Callable, Sequence

from fastmcp import FastMCP
from fastmcp import settings as fastmcp_settings
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.http import StarletteWithLifespan
from opentelemetry.trace import SpanKind

from homelab_common import context, telemetry

_registered: set[str] = set()


def tool[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Mark an async function as an MCP tool for `create_app`'s `tools=[...]`.

    The function itself is returned unchanged, so it stays a plain async function
    usable from REST routes; only its qualified name is recorded in the registry
    that `mcp_server` checks.
    """
    _registered.add(f"{fn.__module__}.{fn.__qualname__}")
    return fn


def mcp_server(name: str, tools: Sequence[Callable[..., Awaitable[object]]]) -> FastMCP:
    """Build the FastMCP server for `tools`, each registered under its own name.

    Every tool runs through the instrumenting wrapper: the docstring becomes the
    description, the type hints the schema, and the return annotation must be a
    Pydantic model or a builtin (never an ORM object).

    Per SPEC section 8 the wrapper owns MCP instrumentation, so FastMCP's own
    spans are switched to `propagation_only`, its documented mode for "another
    instrumentation layer owns the MCP span hierarchy".
    """
    _ensure_registered(tools)
    fastmcp_settings.set_setting("telemetry_mode", "propagation_only")
    server = FastMCP(name)
    for fn in tools:
        server.tool(_instrumented(fn))
    return server


def mcp_app(server: FastMCP, public_host: str) -> StarletteWithLifespan:
    """The MCP endpoint as a Starlette app accepting only `public_host` as Host.

    The endpoint answers at exactly `/mcp`: behind Caddy a redirect to `/mcp/` would lose the
    service prefix and the scheme. Mounting it at the root and combining its lifespan with the
    host app's is `create_app`'s job, not this function's.
    """
    return server.http_app(path="/mcp", allowed_hosts=[public_host])


def _ensure_registered(tools: Sequence[Callable[..., Awaitable[object]]]) -> None:
    """Refuse any function that is not decorated with `tool`."""
    for fn in tools:
        qualified = f"{fn.__module__}.{fn.__qualname__}"
        if qualified not in _registered:
            raise TypeError(f"{qualified} is not a homelab_common tool; decorate it with @tool")


def _instrumented[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Wrap a tool: identity headers in, one span and one duration per call.

    Tool calls may run in another task than the HTTP middleware, so the call
    context is rebuilt from the live request headers on every call; without an
    HTTP request (in-memory client, background task) the headers are empty and
    the actor is `unknown`.
    """
    name = fn.__name__

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        token = context.current.set(
            context.CallContext.from_headers(get_http_headers(include_all=True))
        )
        error_type: str | None = None
        start = time.perf_counter()
        try:
            with telemetry.tracer().start_as_current_span(
                f"tools/call {name}",
                kind=SpanKind.SERVER,
                attributes={
                    "mcp.method.name": "tools/call",
                    "gen_ai.tool.name": name,
                    "gen_ai.operation.name": "execute_tool",
                },
            ):
                return await fn(*args, **kwargs)
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            telemetry.metrics().record_mcp_operation(
                "tools/call", name, time.perf_counter() - start, error_type
            )
            context.current.reset(token)

    return wrapper
