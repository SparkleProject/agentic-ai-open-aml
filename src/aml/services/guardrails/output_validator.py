import re
from dataclasses import dataclass, field

UNSAFE_OUTPUT_PATTERNS = [
    re.compile(r"(recommend|suggest)\s+(not|against)\s+filing\s+(a\s+)?(sar|smr)", re.IGNORECASE),
    re.compile(r"no\s+need\s+to\s+(report|file|investigate)", re.IGNORECASE),
    re.compile(r"this\s+is\s+(not|n't)\s+suspicious", re.IGNORECASE),
    re.compile(r"approve\s+this\s+transaction\s+immediately", re.IGNORECASE),
    re.compile(r"skip\s+(the\s+)?investigation", re.IGNORECASE),
]


@dataclass
class OutputValidationResult:
    is_safe: bool
    flagged_reason: str | None = None
    risk_score: float = 0.0
    matched_patterns: list[str] = field(default_factory=list)


class OutputValidator:
    def validate(self, response: str, context: str | None = None) -> OutputValidationResult:  # noqa: ARG002
        matched: list[str] = []

        for pattern in UNSAFE_OUTPUT_PATTERNS:
            if pattern.search(response):
                matched.append(pattern.pattern)

        is_safe = len(matched) == 0

        return OutputValidationResult(
            is_safe=is_safe,
            flagged_reason=f"Detected {len(matched)} unsafe output patterns" if not is_safe else None,
            risk_score=min(len(matched) * 30.0, 100.0),
            matched_patterns=matched,
        )
