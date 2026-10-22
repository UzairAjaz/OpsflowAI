from __future__ import annotations

from contextlib import contextmanager

from app.config import settings

_CONFIGURED = False
_MEMORY = None

def _build_exporter():
    if settings.otel_exporter == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    if settings.otel_exporter == "otlp" and settings.otel_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            return OTLPSpanExporter(endpoint=settings.otel_endpoint)
        except Exception:
            pass
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    global _MEMORY
    _MEMORY = InMemorySpanExporter()
    return _MEMORY

def configure_tracing(service_name: str = "opsflow-ai") -> bool:
    global _CONFIGURED
    if _CONFIGURED:
        return True
    if not settings.otel_enabled:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        exporter = _build_exporter()
        if exporter is not None:
            provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _CONFIGURED = True
        return True
    except Exception:
        _CONFIGURED = False
        return False

def get_recorded_spans() -> list:
    if _MEMORY is None:
        return []
    return list(_MEMORY.get_finished_spans())

@contextmanager
def span(name: str, **attributes):
    if not _CONFIGURED:
        yield None
        return
    from opentelemetry import trace

    tracer = trace.get_tracer("opsflow")
    with tracer.start_as_current_span(name) as active:
        for key, value in attributes.items():
            try:
                active.set_attribute(key, value)
            except Exception:
                pass
        yield active
