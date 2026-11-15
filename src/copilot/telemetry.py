"""
Week 6 telemetry: OpenTelemetry to Azure Application Insights.

What gets recorded
- Agent Framework's own spans: each agent run, each model call (tokens, latency) and each tool call.
- One `copilot.turn` span per guarded turn, with the guardrail outcome as attributes, and three
  counters: turns, blocked turns and output problems (by check name).

What does not
- Prompt and completion text. Sensitive capture stays off: questions can quote resume text, and
  traces are kept far longer and read by more people than the app itself. The audit log
  (logs/audit.jsonl) is the place for question text.

Everything here is a no-op until `setup_telemetry()` runs with a connection string, so tests and
offline scripts never send anything.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import metrics, trace

SERVICE_NAME = "recruiting-copilot"
log = logging.getLogger(__name__)
_configured = False

tracer = trace.get_tracer("copilot.guardrails")
_meter = metrics.get_meter("copilot.guardrails")
TURNS = _meter.create_counter("copilot.turns", description="Agent turns handled")
BLOCKED = _meter.create_counter("copilot.turns.blocked", description="Turns blocked before or by the model")
OUTPUT_PROBLEMS = _meter.create_counter("copilot.output_problems", description="Answers redacted or withheld")
HELD = _meter.create_up_down_counter("copilot.resumes.held", description="Resumes currently held for review")


def setup_telemetry(connection_string: str | None = None, credential=None) -> bool:
    """Send traces, metrics and logs to Application Insights. Returns False (and does nothing) without
    a connection string. Safe to call more than once."""
    global _configured
    conn = connection_string or os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    if _configured or not conn:
        return _configured
    from agent_framework.observability import enable_instrumentation
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.sdk.resources import Resource

    configure_azure_monitor(connection_string=conn, credential=credential,
                            resource=Resource.create({"service.name": SERVICE_NAME}),
                            logger_name="copilot")
    # Agent Framework spans/metrics on, but never prompt or completion text (see module docstring).
    enable_instrumentation(enable_sensitive_data=False)
    _configured = True
    log.info("Telemetry enabled: Application Insights")
    return True


@contextmanager
def turn_span(**attributes: Any) -> Iterator[trace.Span]:
    """The span every guarded turn runs in; Agent Framework's agent/model/tool spans nest under it."""
    with tracer.start_as_current_span("copilot.turn", attributes=_clean(attributes)) as span:
        yield span


def record_turn(span: trace.Span, reply) -> None:
    """Attach the guardrail outcome to the turn span and update the counters."""
    checks = [p["check"] for p in reply.input_problems + reply.output_problems]
    attrs = {"copilot.blocked": reply.blocked, "copilot.checks": checks,
             "copilot.tools": getattr(reply, "tool_calls", []), "copilot.cited_count": reply.cited_count}
    span.set_attributes(_clean(attrs))
    TURNS.add(1)
    if reply.blocked:
        stage = next((p["check"] for p in reply.input_problems if not p.get("advisory")), "unknown")
        BLOCKED.add(1, {"stage": stage})
        span.add_event("guardrail.blocked", {"stage": stage})
    for p in reply.output_problems:
        OUTPUT_PROBLEMS.add(1, {"check": p["check"]})


def _clean(attrs: dict[str, Any]) -> dict[str, Any]:
    """OpenTelemetry attributes must be str/bool/int/float or lists of them."""
    out = {}
    for k, v in attrs.items():
        if v is None:
            continue
        out[k] = [str(x) for x in v] if isinstance(v, (list, tuple, set)) else v
    return out
