import json
import logging
from collections.abc import AsyncGenerator, Mapping

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import Histogram, InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import format_span_id, format_trace_id

from homelab_common import CommonSettings, telemetry


def settings() -> CommonSettings:
    # setup() reads only service_name and otlp_endpoint, so the database fields are left unset.
    return CommonSettings.model_construct(service_name="telemetrytest", otlp_endpoint=None)


@pytest.fixture(autouse=True)
async def reset_telemetry() -> AsyncGenerator[None]:
    yield
    await telemetry.shutdown()


def test_sql_parts_with_table() -> None:
    assert telemetry.sql_parts("SELECT * FROM tasks WHERE id = $1") == ("SELECT", "tasks")


def test_sql_parts_schema_qualified_table() -> None:
    assert telemetry.sql_parts("INSERT INTO common.audit (service, action) VALUES ($1, $2)") == (
        "INSERT",
        "audit",
    )


def test_sql_parts_without_table() -> None:
    assert telemetry.sql_parts("SELECT 1") == ("SELECT", None)


def make_record(message: str, extras: Mapping[str, object]) -> logging.LogRecord:
    record = logging.LogRecord("svc", logging.INFO, "app.py", 7, message, None, None)
    for key, value in extras.items():
        record.__dict__[key] = value
    return record


def test_json_formatter_inside_span() -> None:
    provider = TracerProvider()
    with provider.get_tracer("homelab_common").start_as_current_span("SELECT tasks") as span:
        context = span.get_span_context()
        expected = (format_trace_id(context.trace_id), format_span_id(context.span_id))
        payload = json.loads(telemetry.JsonFormatter().format(make_record("db call", {})))
    assert set(payload) == {"timestamp", "severity", "body", "logger", "trace_id", "span_id"}
    assert (payload["trace_id"], payload["span_id"]) == expected
    assert payload["body"] == "db call"


def test_json_formatter_outside_span() -> None:
    payload = json.loads(telemetry.JsonFormatter().format(make_record("plain", {})))
    assert "trace_id" not in payload
    assert "span_id" not in payload
    assert payload["severity"] == "INFO"
    assert payload["logger"] == "svc"


def test_json_formatter_extra_attributes_keep_names() -> None:
    payload = json.loads(
        telemetry.JsonFormatter().format(
            make_record("calling", {"http.route": "/tasks/{task_id}", "turn_id": "t-9"})
        )
    )
    assert payload["http.route"] == "/tasks/{task_id}"
    assert payload["turn_id"] == "t-9"
    assert "levelname" not in payload


def test_http_histogram_buckets_and_allowlist() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], views=list(telemetry.metric_views()))
    meter = provider.get_meter("homelab_common")
    telemetry.Metrics(meter).record_http_server("GET", "/tasks/{task_id}", 200, 0.42, None)
    # A non-allowlisted attribute the way an id or a raw path would sneak in.
    meter.create_histogram("http.server.request.duration", unit="s").record(
        0.42, {"http.request.method": "GET", "task.id": "7"}
    )
    data = reader.get_metrics_data()
    assert data is not None
    points = [
        point
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == "http.server.request.duration" and isinstance(metric.data, Histogram)
        for point in metric.data.data_points
    ]
    assert len(points) == 2
    for point in points:
        assert list(point.explicit_bounds) == list(telemetry.HTTP_BUCKETS)
        assert "task.id" not in (point.attributes or {})
    smuggled, typed = sorted(points, key=lambda point: len(point.attributes or {}))
    assert typed.attributes == {
        "http.request.method": "GET",
        "http.route": "/tasks/{task_id}",
        "http.response.status_code": 200,
    }
    assert smuggled.attributes == {"http.request.method": "GET"}


def test_setup_twice_raises() -> None:
    telemetry.setup(settings())
    with pytest.raises(RuntimeError, match="already called"):
        telemetry.setup(settings())


def test_resource_instance_id_is_stable_across_restarts() -> None:
    settings = CommonSettings.model_construct(service_name="tasks", host_name="veronica")
    first, second = telemetry.build_resource(settings), telemetry.build_resource(settings)
    assert first.attributes["service.instance.id"] == "tasks@veronica"
    assert first.attributes == second.attributes
    assert first.attributes["deployment.environment"] == "homelab"
