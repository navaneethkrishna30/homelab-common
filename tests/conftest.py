"""Process-global OTel doubles for the whole suite: one span exporter, one metric reader.

set_tracer_provider / set_meter_provider are once-only per process (the first
call wins, later ones warn and are ignored), so the in-memory providers are
installed here, once, for every module. Nothing else in the suite sets the
globals, no provider is ever shut down, and every module filters the
accumulating streams by instrument name and attributes.
"""

import pytest
from opentelemetry.metrics import set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import set_tracer_provider

from homelab_common import telemetry


@pytest.fixture(autouse=True, scope="session")
def spans() -> InMemorySpanExporter:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    set_tracer_provider(provider)
    return exporter


@pytest.fixture(autouse=True, scope="session")
def metric_reader() -> InMemoryMetricReader:
    reader = InMemoryMetricReader()
    set_meter_provider(MeterProvider(metric_readers=[reader], views=list(telemetry.metric_views())))
    return reader
