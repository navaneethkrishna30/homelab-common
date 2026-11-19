"""OpenTelemetry setup, the SPEC section 8 instruments, JSON logging and DB instrumentation."""

import asyncio
import json
import logging
import os
import platform
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.metrics import (
    CallbackOptions,
    Histogram,
    Meter,
    Observation,
    get_meter,
    set_meter_provider,
)
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import (
    Span,
    SpanKind,
    Status,
    StatusCode,
    Tracer,
    format_span_id,
    format_trace_id,
    get_current_span,
    get_tracer,
    set_tracer_provider,
)
from sqlalchemy import event
from sqlalchemy.engine.interfaces import (
    DBAPIConnection,
    DBAPICursor,
    ExceptionContext,
    ExecutionContext,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from homelab_common.config import CommonSettings

# SPEC section 8 histogram bucket boundaries (seconds); units live in metadata, never in names.
HTTP_BUCKETS: Sequence[float] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1,
    2.5,
    5,
    7.5,
    10,
)
DB_BUCKETS: Sequence[float] = (
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1,
    2.5,
    5,
    10,
)
MCP_BUCKETS: Sequence[float] = (
    0.01,
    0.02,
    0.05,
    0.1,
    0.2,
    0.5,
    1,
    2,
    5,
    10,
    30,
    60,
    120,
    300,
)

# The metric attribute allowlist (SPEC section 8 cardinality rule), split per instrument.
_HTTP_ATTRIBUTE_KEYS = frozenset(
    {"http.request.method", "http.route", "http.response.status_code", "error.type"}
)
_DB_ATTRIBUTE_KEYS = frozenset({"db.operation.name", "db.collection.name", "error.type"})
_MCP_ATTRIBUTE_KEYS = frozenset({"mcp.method.name", "gen_ai.tool.name", "error.type"})
_POOL_ATTRIBUTE_KEYS = frozenset({"db.client.connection.state", "db.client.connection.pool.name"})

# Only the two SPEC-named process metrics; system.* ones stay off.
_SYSTEM_METRICS_CONFIG: dict[str, list[str] | None] = {
    "process.cpu.time": ["user", "system"],
    "process.memory.usage": None,
}


def metric_views() -> Sequence[View]:
    """The SPEC section 8 views: explicit histogram buckets and the attribute allowlist."""
    return (
        View(
            instrument_name="http.server.request.duration",
            aggregation=ExplicitBucketHistogramAggregation(boundaries=HTTP_BUCKETS),
            attribute_keys=set(_HTTP_ATTRIBUTE_KEYS),
        ),
        View(
            instrument_name="http.client.request.duration",
            aggregation=ExplicitBucketHistogramAggregation(boundaries=HTTP_BUCKETS),
            attribute_keys=set(_HTTP_ATTRIBUTE_KEYS),
        ),
        View(
            instrument_name="db.client.operation.duration",
            aggregation=ExplicitBucketHistogramAggregation(boundaries=DB_BUCKETS),
            attribute_keys=set(_DB_ATTRIBUTE_KEYS),
        ),
        View(
            instrument_name="db.client.connection.count",
            attribute_keys=set(_POOL_ATTRIBUTE_KEYS),
        ),
        View(
            instrument_name="mcp.server.operation.duration",
            aggregation=ExplicitBucketHistogramAggregation(boundaries=MCP_BUCKETS),
            attribute_keys=set(_MCP_ATTRIBUTE_KEYS),
        ),
    )


def tracer() -> Tracer:
    """The library's tracer (the API proxy until setup sets a provider)."""
    return get_tracer("homelab_common")


class Metrics:
    """Typed record methods for the SPEC section 8 duration histograms.

    Attributes stay inside the view allowlists; ids, raw paths and SQL text go to spans
    and logs only, never to metric labels.
    """

    def __init__(self, meter: Meter | None = None) -> None:
        """Bind to the global meter unless a caller provides its own (tests do)."""
        self._meter = get_meter("homelab_common") if meter is None else meter
        self._histograms: dict[str, Histogram] = {}

    def _histogram(self, name: str) -> Histogram:
        histogram = self._histograms.get(name)
        if histogram is None:
            histogram = self._meter.create_histogram(name, unit="s")
            self._histograms[name] = histogram
        return histogram

    def record_http_server(
        self, method: str, route: str, status: int, seconds: float, error_type: str | None
    ) -> None:
        """Record http.server.request.duration for one served request."""
        attributes: dict[str, str | int] = {
            "http.request.method": method,
            "http.route": route,
            "http.response.status_code": status,
        }
        if error_type is not None:
            attributes["error.type"] = error_type
        self._histogram("http.server.request.duration").record(seconds, attributes)

    def record_db_operation(
        self, operation: str, collection: str | None, seconds: float, error_type: str | None
    ) -> None:
        """Record db.client.operation.duration for one executed statement."""
        attributes: dict[str, str] = {"db.operation.name": operation}
        if collection is not None:
            attributes["db.collection.name"] = collection
        if error_type is not None:
            attributes["error.type"] = error_type
        self._histogram("db.client.operation.duration").record(seconds, attributes)

    def record_mcp_operation(
        self, method_name: str, tool_name: str | None, seconds: float, error_type: str | None
    ) -> None:
        """Record mcp.server.operation.duration for one MCP operation."""
        attributes: dict[str, str] = {"mcp.method.name": method_name}
        if tool_name is not None:
            attributes["gen_ai.tool.name"] = tool_name
        if error_type is not None:
            attributes["error.type"] = error_type
        self._histogram("mcp.server.operation.duration").record(seconds, attributes)


_metrics: Metrics | None = None


def metrics() -> Metrics:
    """The process's metric recorders, created on first use."""
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics


# Standard LogRecord attributes (logging docs); never part of the JSON payload's extras.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "id",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """One JSON object per line: the OTel log keys plus every extra= attribute under its name."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "severity": record.levelname,
            "body": record.getMessage(),
            "logger": record.name,
        }
        span_context = get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = format_trace_id(span_context.trace_id)
            payload["span_id"] = format_span_id(span_context.span_id)
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str)


_TABLE_RE = re.compile(
    r"\b(?:from|into|update|join)\s+(?:[a-z_][\w$]*\.)?\"?([a-z_][\w$]*)\"?", re.IGNORECASE
)


def sql_parts(statement: str) -> tuple[str, str | None]:
    """The SQL verb (first keyword, uppercased) and the table it touches, if any.

    A schema-qualified name is stripped to the table; statements without a
    FROM/INTO/UPDATE/JOIN table have no collection.
    """
    verb = statement.split(None, 1)[0].strip("()\"'").upper()
    match = _TABLE_RE.search(statement)
    return verb, match.group(1) if match is not None else None


@dataclass
class _DbCall:
    """One cursor execution in flight, from before_cursor_execute to its end."""

    span: Span
    operation: str
    collection: str | None
    start: float


_db_calls: dict[int, _DbCall] = {}


def _before_cursor_execute(
    conn: DBAPIConnection,
    cursor: DBAPICursor,
    statement: str,
    parameters: object,
    context: ExecutionContext,
    executemany: bool,
) -> None:
    operation, collection = sql_parts(statement)
    span = tracer().start_span(
        f"{operation} {collection}" if collection is not None else operation,
        kind=SpanKind.CLIENT,
    )
    span.set_attribute("db.operation.name", operation)
    if collection is not None:
        span.set_attribute("db.collection.name", collection)
    span.set_attribute("db.query.text", statement)
    _db_calls[id(context.connection)] = _DbCall(
        span=span, operation=operation, collection=collection, start=time.perf_counter()
    )


def _after_cursor_execute(
    conn: DBAPIConnection,
    cursor: DBAPICursor,
    statement: str,
    parameters: object,
    context: ExecutionContext,
    executemany: bool,
) -> None:
    call = _db_calls.pop(id(context.connection), None)
    if call is None:
        return
    call.span.end()
    metrics().record_db_operation(
        call.operation, call.collection, time.perf_counter() - call.start, None
    )


def _handle_db_error(exception_context: ExceptionContext) -> None:
    execution_context = exception_context.execution_context
    if execution_context is None:
        return
    call = _db_calls.pop(id(execution_context.connection), None)
    if call is None:
        return
    error_type = type(exception_context.original_exception).__name__
    call.span.set_status(Status(StatusCode.ERROR))
    call.span.set_attribute("error.type", error_type)
    call.span.end()
    metrics().record_db_operation(
        call.operation, call.collection, time.perf_counter() - call.start, error_type
    )


def _register_pool_gauge(pool: QueuePool, pool_name: str) -> None:
    def observations(options: CallbackOptions) -> Sequence[Observation]:
        return (
            Observation(
                pool.checkedout(),
                {"db.client.connection.state": "used", "db.client.connection.pool.name": pool_name},
            ),
            Observation(
                pool.checkedin(),
                {"db.client.connection.state": "idle", "db.client.connection.pool.name": pool_name},
            ),
        )

    get_meter("homelab_common").create_observable_gauge(
        name="db.client.connection.count",
        callbacks=[observations],
        unit="{connection}",
        description="Connections in the pool, by state.",
    )


def instrument_engine(engine: AsyncEngine) -> None:
    """Span, duration metric and pool gauge for every statement the engine executes.

    A no-op until telemetry.setup() ran. SQL text goes on the span (db.query.text),
    never to metrics.
    """
    if _telemetry is None or _service_name is None:
        return
    pool = engine.sync_engine.pool
    if isinstance(pool, QueuePool):
        _register_pool_gauge(pool, _service_name)
    event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine.sync_engine, "after_cursor_execute", _after_cursor_execute)
    event.listen(engine.sync_engine, "handle_error", _handle_db_error)


@dataclass
class _Telemetry:
    """Everything setup() installed, so shutdown() can take it down again."""

    json_handler: logging.Handler
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    logger_provider: LoggerProvider | None = None
    otel_handler: logging.Handler | None = None
    httpx_instrumentor: HTTPXClientInstrumentor | None = None
    system_instrumentor: SystemMetricsInstrumentor | None = None


_telemetry: _Telemetry | None = None
_service_name: str | None = None


def setup(settings: CommonSettings) -> None:
    """Install JSON logging and, when otlp_endpoint is set, OTLP export and instrumentors.

    Without otlp_endpoint nothing is exported (tests, local runs) but the instruments
    still work. A second call raises RuntimeError.
    """
    global _telemetry, _service_name
    if _telemetry is not None:
        raise RuntimeError("telemetry.setup() already called")
    _service_name = settings.service_name

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    json_handler = logging.StreamHandler(sys.stdout)
    json_handler.setFormatter(JsonFormatter())
    root.addHandler(json_handler)
    root.setLevel(logging.INFO)

    endpoint = settings.otlp_endpoint
    if endpoint is None:
        _telemetry = _Telemetry(json_handler=json_handler)
        return

    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "host.name": platform.node(),
            "deployment.environment": "production",
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    set_tracer_provider(tracer_provider)
    meter_provider = MeterProvider(
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"), export_interval_millis=15_000
            )
        ],
        resource=resource,
        views=list(metric_views()),
    )
    set_meter_provider(meter_provider)
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
    )
    set_logger_provider(logger_provider)
    otel_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    root.addHandler(otel_handler)

    # The instrumentor emits http.client.request.duration only under the new HTTP semconv.
    os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "http"
    httpx_instrumentor = HTTPXClientInstrumentor()
    httpx_instrumentor.instrument()
    system_instrumentor = SystemMetricsInstrumentor(config=_SYSTEM_METRICS_CONFIG)
    system_instrumentor.instrument()
    _telemetry = _Telemetry(
        json_handler=json_handler,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        otel_handler=otel_handler,
        httpx_instrumentor=httpx_instrumentor,
        system_instrumentor=system_instrumentor,
    )


def _shutdown_providers(state: _Telemetry) -> None:
    for provider in (state.logger_provider, state.meter_provider, state.tracer_provider):
        if provider is not None:
            provider.shutdown()


async def shutdown() -> None:
    """Flush and stop everything setup() installed; a no-op when setup never ran."""
    global _telemetry, _metrics, _service_name
    state = _telemetry
    _telemetry = None
    _metrics = None
    _service_name = None
    if state is None:
        return
    root = logging.getLogger()
    root.removeHandler(state.json_handler)
    if state.otel_handler is not None:
        root.removeHandler(state.otel_handler)
    for instrumentor in (state.httpx_instrumentor, state.system_instrumentor):
        if instrumentor is not None:
            instrumentor.uninstrument()
    await asyncio.to_thread(_shutdown_providers, state)
