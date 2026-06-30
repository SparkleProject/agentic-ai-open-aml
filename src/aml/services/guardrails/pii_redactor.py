import re
from dataclasses import dataclass, field

PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("TFN", re.compile(r"\b\d{3}\s?\d{3}\s?\d{3}\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d{4}[\s-]?){3}\d{1,4}\b")),
    ("BSB_ACCOUNT", re.compile(r"\b\d{3}-?\d{3}\s+\d{6,10}\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
    ("PHONE_AU", re.compile(r"\b(?:\+61|0)\d{1,2}\s?\d{4}\s?\d{4}\b")),
    ("DOB", re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")),
]


@dataclass
class Redaction:
    pii_type: str
    start: int
    end: int
    original_length: int


@dataclass
class RedactedText:
    text: str
    redactions: list[Redaction] = field(default_factory=list)
    pii_found: bool = False


class PIIRedactor:
    def __init__(self, *, mode: str = "mask") -> None:
        self._mode = mode

    def redact(self, text: str) -> RedactedText:
        redactions: list[Redaction] = []
        result = text

        for pii_type, pattern in PII_PATTERNS:
            for match in pattern.finditer(text):
                redactions.append(
                    Redaction(
                        pii_type=pii_type,
                        start=match.start(),
                        end=match.end(),
                        original_length=match.end() - match.start(),
                    )
                )

        if not redactions:
            return RedactedText(text=text, pii_found=False)

        for pii_type, pattern in PII_PATTERNS:
            if self._mode == "mask":
                result = pattern.sub(f"[REDACTED-{pii_type}]", result)
            elif self._mode == "remove":
                result = pattern.sub("", result)

        return RedactedText(text=result, redactions=redactions, pii_found=True)
