from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

logger = logging.getLogger(__name__)

_OTEL_CONFIGURED = False


def configure_console_tracing() -> bool:
    global _OTEL_CONFIGURED

    if _OTEL_CONFIGURED:
        return True

    exporter_name = os.getenv("OTEL_TRACES_EXPORTER", "").strip().lower()
    if exporter_name != "console":
        return False

    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        logger.debug("OpenTelemetry tracer provider already configured")
        _OTEL_CONFIGURED = True
        return True

    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(
        BatchSpanProcessor(ConsoleSpanExporter())
    )
    trace.set_tracer_provider(tracer_provider)
    logger.info("Configured OpenTelemetry console trace exporter")
    _OTEL_CONFIGURED = True
    return True
