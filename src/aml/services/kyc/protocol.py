from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    check_name: str
    passed: bool
    details: str = ""


@dataclass
class VerificationResult:
    verified: bool
    confidence: float
    checks: list[CheckResult] = field(default_factory=list)
    provider_ref: str = ""


class IdentityVerificationProvider(ABC):
    @abstractmethod
    async def verify_identity(
        self,
        *,
        name: str,
        customer_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationResult: ...
