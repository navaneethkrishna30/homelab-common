"""The tool decorator, the MCP server builder and the public_host default."""

import importlib

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from opentelemetry.sdk.metrics.export import (
    Histogram,
    HistogramDataPoint,
    InMemoryMetricReader,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from pydantic import BaseModel

from homelab_common import CommonSettings, context, tool
from homelab_common.tool import mcp_server


class Sum(BaseModel):
    total: int


class Actor(BaseModel):
    name: str


@tool
async def add(a: int, b: int) -> Sum:
    """Add two integers."""
    return Sum(total=a + b)


@tool
async def boom() -> Sum:
    """Always raise."""
    raise ValueError("boom")


@tool
async def whoami() -> Actor:
    """Return the actor of the current call."""
    return Actor(name=context.current.get().actor)


async def plain() -> Sum:
    return Sum(total=0)


# The process-global OTel providers behind the `spans` and `metric_reader`
# fixtures now live in tests/conftest.py: set_*_provider is once-only, and
# test_app needs the same globals, so one session-wide pair serves the suite.


def operation_points(reader: InMemoryMetricReader) -> list[HistogramDataPoint]:
    """Every mcp.server.operation.duration data point recorded so far."""
    data = reader.get_metrics_data()
    assert data is not None
    return [
        point
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == "mcp.server.operation.duration" and isinstance(metric.data, Histogram)
        for point in metric.data.data_points
    ]


def points_for(reader: InMemoryMetricReader, tool_name: str) -> list[HistogramDataPoint]:
    return [
        point
        for point in operation_points(reader)
        if point.attributes is not None and point.attributes.get("gen_ai.tool.name") == tool_name
    ]


async def test_tool_call_span_and_metric(
    spans: InMemorySpanExporter, metric_reader: InMemoryMetricReader
) -> None:
    server = mcp_server("svc", [add])
    async with Client(server) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})
    assert result.structured_content == {"total": 5}
    tool_spans = [span for span in spans.get_finished_spans() if span.name == "tools/call add"]
    assert len(tool_spans) == 1
    span = tool_spans[0]
    assert span.kind == SpanKind.SERVER
    assert span.attributes == {
        "mcp.method.name": "tools/call",
        "gen_ai.tool.name": "add",
        "gen_ai.operation.name": "execute_tool",
    }
    points = points_for(metric_reader, "add")
    assert len(points) == 1
    assert "error.type" not in (points[0].attributes or {})


async def test_raising_tool_records_error_type(metric_reader: InMemoryMetricReader) -> None:
    server = mcp_server("svc", [boom])
    async with Client(server) as client:
        with pytest.raises(ToolError, match="boom"):
            await client.call_tool("boom", {})
    points = points_for(metric_reader, "boom")
    assert len(points) == 1
    assert points[0].attributes is not None
    assert points[0].attributes["error.type"] == "ValueError"


def test_undecorated_function_rejected() -> None:
    with pytest.raises(TypeError, match="plain"):
        mcp_server("svc", [plain])


def test_public_host_default() -> None:
    # model_construct keeps the credential fields out of the picture; the
    # env-vs-Yaml wiring itself is test_config's subject.
    assert CommonSettings.model_construct().public_host == "svc.fin-alkaline.ts.net"


async def test_actor_header_reaches_call_context(monkeypatch: pytest.MonkeyPatch) -> None:
    # The real HTTP transport route was spike-verified (fastmcp's asgi_client
    # carries headers to the tool), but its client is annotated as a bare
    # Client, which pyright strict cannot use without cast; so the header
    # getter is patched instead, exactly as the card allows. The module is
    # imported by name because the package attribute `homelab_common.tool` is
    # the decorator, not the module.
    def actor_headers(**kwargs: object) -> dict[str, str]:
        return {"x-homelab-actor": "jarvis"}

    tool_module = importlib.import_module("homelab_common.tool")
    monkeypatch.setattr(tool_module, "get_http_headers", actor_headers)
    server = mcp_server("svc", [whoami])
    async with Client(server) as client:
        result = await client.call_tool("whoami", {})
    assert result.structured_content == {"name": "jarvis"}
