"""Lightweight span/metric collection for agent observability (BE-502).

Provides a simple in-process metrics collector. OpenTelemetry SDK integration
is deferred to production deployment — this module captures the same data
shapes so the API layer can serve real metrics immediately.
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class SpanRecord:
    name: str
    start_time: float
    end_time: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "OK"

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


class MetricsCollector:
    _instance: ClassVar["MetricsCollector | None"] = None

    def __init__(self) -> None:
        self.spans: list[SpanRecord] = []
        self.counters: dict[str, float] = {}

    @classmethod
    def get_instance(cls) -> "MetricsCollector":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def record_span(self, span: SpanRecord) -> None:
        self.spans.append(span)

    def increment(self, name: str, value: float = 1.0) -> None:
        self.counters[name] = self.counters.get(name, 0.0) + value

    def get_counter(self, name: str) -> float:
        return self.counters.get(name, 0.0)

    def get_summary(self) -> dict[str, Any]:
        total = len(self.spans)
        if not total:
            return {"total_spans": 0, "counters": dict(self.counters)}

        durations = [s.duration_ms for s in self.spans]
        durations.sort()

        return {
            "total_spans": total,
            "p50_ms": durations[total // 2] if total else 0,
            "p95_ms": durations[int(total * 0.95)] if total else 0,
            "p99_ms": durations[int(total * 0.99)] if total else 0,
            "counters": dict(self.counters),
        }
