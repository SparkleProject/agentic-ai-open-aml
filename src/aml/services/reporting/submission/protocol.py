from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubmissionResult:
    success: bool
    reference: str | None = None
    error: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubmissionStatus:
    status: str
    details: str = ""


class RegulatorySubmissionAdapter(ABC):
    @abstractmethod
    async def format_payload(self, report_type: str, narrative: dict[str, str]) -> bytes: ...

    @abstractmethod
    async def submit(self, payload: bytes) -> SubmissionResult: ...

    @abstractmethod
    async def check_status(self, reference: str) -> SubmissionStatus: ...
