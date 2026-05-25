from opentelemetry import trace


def current_trace_id() -> str:
    """Return current trace id in 32-char hex, or empty when unavailable."""
    span = trace.get_current_span()
    context = span.get_span_context()
    if not context or not context.is_valid:
        return ""
    return format(context.trace_id, "032x")
