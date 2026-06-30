import re
from dataclasses import dataclass, field

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all|your)\s+", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?(above|previous)", re.IGNORECASE),
    re.compile(r"do\s+not\s+file\s+(a\s+)?sar", re.IGNORECASE),
    re.compile(r"override\s+compliance", re.IGNORECASE),
]

ZERO_WIDTH_CHARS = re.compile(r"[​‌‍⁠﻿]")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class ValidationResult:
    is_safe: bool
    blocked_reason: str | None = None
    sanitised_input: str = ""
    risk_score: float = 0.0
    matched_patterns: list[str] = field(default_factory=list)


class InputValidator:
    def __init__(self, *, block_threshold: int = 2) -> None:
        self._block_threshold = block_threshold

    def validate(self, prompt: str, system_prompt: str | None = None) -> ValidationResult:  # noqa: ARG002
        sanitised = self._sanitise(prompt)
        matched: list[str] = []
        risk = 0.0

        for pattern in INJECTION_PATTERNS:
            if pattern.search(sanitised):
                matched.append(pattern.pattern)
                risk += 1.0

        if ZERO_WIDTH_CHARS.search(prompt):
            matched.append("zero_width_chars")
            risk += 0.5

        is_safe = len(matched) < self._block_threshold

        return ValidationResult(
            is_safe=is_safe,
            blocked_reason=f"Detected {len(matched)} injection patterns" if not is_safe else None,
            sanitised_input=sanitised,
            risk_score=min(risk / len(INJECTION_PATTERNS) * 100, 100.0),
            matched_patterns=matched,
        )

    @staticmethod
    def _sanitise(text: str) -> str:
        text = CONTROL_CHARS.sub("", text)
        return ZERO_WIDTH_CHARS.sub("", text)
