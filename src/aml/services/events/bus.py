import enum
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class EventType(enum.StrEnum):
    ALERT_CREATED = "alert.created"
    ALERT_RESOLVED = "alert.resolved"
    ALERT_AUTO_CLEARED = "alert.auto_cleared"
    CASE_CREATED = "case.created"
    CASE_CLOSED = "case.closed"
    INVESTIGATION_COMPLETED = "investigation.completed"
    REPORT_DRAFTED = "report.drafted"
    REPORT_SUBMITTED = "report.submitted"
    KYC_ONBOARDING_COMPLETE = "kyc.onboarding_complete"
    KYC_RISK_CHANGED = "kyc.risk_changed"


@dataclass
class PlatformEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.ALERT_CREATED
    tenant_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    payload: dict[str, Any] = field(default_factory=dict)


EventHandler = Callable[[PlatformEvent], Coroutine[Any, Any, None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._event_log: list[PlatformEvent] = []

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def emit(self, event: PlatformEvent) -> None:
        self._event_log.append(event)
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            await handler(event)

    @property
    def event_log(self) -> list[PlatformEvent]:
        return list(self._event_log)
