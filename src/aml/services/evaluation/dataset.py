from dataclasses import dataclass, field
from typing import Any


@dataclass
class GoldenCase:
    case_id: str
    category: str
    input_data: dict[str, Any]
    expected_outcome: dict[str, Any]
    difficulty: str = "medium"
    tags: list[str] = field(default_factory=list)


@dataclass
class GoldenDataset:
    version: str
    cases: list[GoldenCase]

    @property
    def coverage(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case.category] = counts.get(case.category, 0) + 1
        return counts

    def filter_by_category(self, category: str) -> list[GoldenCase]:
        return [c for c in self.cases if c.category == category]

    def filter_by_difficulty(self, difficulty: str) -> list[GoldenCase]:
        return [c for c in self.cases if c.difficulty == difficulty]


def build_seed_dataset() -> GoldenDataset:
    cases = [
        GoldenCase(
            "GC-001",
            "sanctions",
            {"alert_type": "sanctions_match", "entity": "Test Entity"},
            {"decision": "INVESTIGATE"},
            "easy",
        ),
        GoldenCase(
            "GC-002",
            "structuring",
            {"alert_type": "structuring", "amount_pattern": "sub-threshold"},
            {"decision": "INVESTIGATE"},
            "medium",
        ),
        GoldenCase(
            "GC-003",
            "pep",
            {"alert_type": "pep_match", "name": "Official"},
            {"decision": "INVESTIGATE"},
            "medium",
        ),
        GoldenCase(
            "GC-004",
            "false_positive",
            {"alert_type": "threshold", "amount": 10001},
            {"decision": "AUTO_CLEAR"},
            "easy",
        ),
        GoldenCase(
            "GC-005",
            "adverse_media",
            {"alert_type": "adverse_media", "entity": "Corp"},
            {"decision": "INVESTIGATE"},
            "hard",
        ),
    ]
    return GoldenDataset(version="1.0", cases=cases)
