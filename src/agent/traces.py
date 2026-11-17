"""Traces of the agent, one JSON line per span, in a file under the data directory.

There is no collector and no backend: ``JsonLinesExporter`` is an OpenTelemetry span
exporter that appends every finished span to one file, by default
``<data dir>/agent/traces.jsonl``. All the spans of one question share a ``trace_id``, so
``grep`` on that id gives the whole question: the question itself, every model call and
every tool call, each with when it started and how long it took.

What a line holds is plain data: names, numbers, the SQL the model wrote and the status of
the question. Nothing in a span comes from a secrets file, and no span carries a URL.
"""

from __future__ import annotations

import datetime
import json
import threading
from collections.abc import Sequence
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from univ3_indexer import config

TRACES_NAME = "traces.jsonl"


def default_traces_file() -> Path:
    """``<data dir>/agent/traces.jsonl``. The data directory is never inside the repository."""
    return config.data_dir() / "agent" / TRACES_NAME


def _time(nanoseconds: int | None) -> str | None:
    if nanoseconds is None:
        return None
    moment = datetime.datetime.fromtimestamp(nanoseconds / 1e9, datetime.UTC)
    return moment.isoformat(timespec="microseconds")


def _hex(number: int, width: int) -> str:
    return format(number, f"0{width}x")


def trace_id_hex(trace_id: int) -> str:
    """The 32 hex digits OpenTelemetry writes a trace id with."""
    return _hex(trace_id, 32)


def span_to_dict(span: ReadableSpan) -> dict:
    """One finished span as the plain data of one line."""
    context = span.context
    started, ended = span.start_time, span.end_time
    return {
        "name": span.name,
        "trace_id": trace_id_hex(context.trace_id),
        "span_id": _hex(context.span_id, 16),
        "parent_id": _hex(span.parent.span_id, 16) if span.parent else None,
        "start": _time(started),
        "end": _time(ended),
        "seconds": None if started is None or ended is None else (ended - started) / 1e9,
        "status": span.status.status_code.name,
        "attributes": dict(span.attributes or {}),
        "events": [
            {"name": event.name, "at": _time(event.timestamp), **dict(event.attributes or {})}
            for event in span.events
        ],
    }


class JsonLinesExporter(SpanExporter):
    """Appends each finished span to ``path`` as one JSON line. The directory is created."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        lines = "".join(json.dumps(span_to_dict(s), ensure_ascii=False) + "\n" for s in spans)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(lines)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def tracer_provider(path: Path) -> TracerProvider:
    """A provider of its own that writes to ``path``, span by span as each one ends.

    It is not made the global provider: whoever builds it passes it on, so tests and the
    service never share one by accident.
    """
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(JsonLinesExporter(path)))
    return provider
